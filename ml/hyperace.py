"""HyperACE segmentation branch for BS-Roformer mask estimators.

Ported from the reference implementation shipped alongside the weights at
``pcunwa/BS-Roformer-HyperACE`` (``v2_inst/bs_roformer.py``). The checkpoints
attach this whole tree under ``mask_estimators.N.segm.*``; without it,
``load_state_dict`` rejects ~471 keys.

Structure, mirroring the checkpoint's names exactly:

- :class:`Backbone` — depthwise-separable CSP encoder (``stem``, ``p2``…``p5``).
- :class:`HyperACE` — hypergraph attention over the fused pyramid.
- :class:`Decoder` — gated top-down fusion back to the finest level.
- :class:`ProgressiveUpsampleHead` — frequency pixel-shuffle to full bins.

Attribute names are load-bearing: they *are* the ``state_dict`` keys. The
norms are ``InstanceNorm2d`` named ``bn`` — that is upstream's naming, and it
is why the checkpoint carries no running statistics.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple, Union

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch.nn import Module

_Size = Union[int, Tuple[int, int]]


def autopad(k: _Size, p: _Size | None = None) -> _Size:
    """Padding that keeps the spatial size for an odd kernel."""
    if p is None:
        return k // 2 if isinstance(k, int) else (k[0] // 2, k[1] // 2)
    return p


class Conv(Module):
    """1x1/3x3 conv + InstanceNorm + SiLU."""

    def __init__(
        self, c1: int, c2: int, k: _Size = 1, s: _Size = 1,
        p: _Size | None = None, g: int = 1, act: bool = True,
    ) -> None:
        super().__init__()
        self.conv = nn.Conv2d(c1, c2, k, s, autopad(k, p), groups=g, bias=False)
        self.bn = nn.InstanceNorm2d(c2, affine=True, eps=1e-8)
        self.act = nn.SiLU() if act else nn.Identity()

    def forward(self, x: Tensor) -> Tensor:
        return self.act(self.bn(self.conv(x)))


class DSConv(Module):
    """Depthwise-separable conv: depthwise, pointwise, norm, activation."""

    def __init__(
        self, c1: int, c2: int, k: _Size = 3, s: _Size = 1,
        p: _Size | None = None, act: bool = True,
    ) -> None:
        super().__init__()
        self.dwconv = nn.Conv2d(c1, c1, k, s, autopad(k, p), groups=c1, bias=False)
        self.pwconv = nn.Conv2d(c1, c2, 1, 1, 0, bias=False)
        self.bn = nn.InstanceNorm2d(c2, affine=True, eps=1e-8)
        self.act = nn.SiLU() if act else nn.Identity()

    def forward(self, x: Tensor) -> Tensor:
        return self.act(self.bn(self.pwconv(self.dwconv(x))))


class DS_Bottleneck(Module):
    def __init__(self, c1: int, c2: int, k: _Size = 3, shortcut: bool = True) -> None:
        super().__init__()
        self.dsconv1 = DSConv(c1, c1, k=3, s=1)
        self.dsconv2 = DSConv(c1, c2, k=k, s=1)
        self.shortcut = shortcut and c1 == c2

    def forward(self, x: Tensor) -> Tensor:
        out = self.dsconv2(self.dsconv1(x))
        return x + out if self.shortcut else out


class DS_C3k(Module):
    """CSP block: split, run bottlenecks on one half, concat, project."""

    def __init__(self, c1: int, c2: int, n: int = 1, k: _Size = 3, e: float = 0.5) -> None:
        super().__init__()
        c_ = int(c2 * e)
        self.cv1 = Conv(c1, c_, 1, 1)
        self.cv2 = Conv(c1, c_, 1, 1)
        self.cv3 = Conv(2 * c_, c2, 1, 1)
        self.m = nn.Sequential(
            *[DS_Bottleneck(c_, c_, k=k, shortcut=True) for _ in range(n)]
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.cv3(torch.cat((self.m(self.cv1(x)), self.cv2(x)), dim=1))


class DS_C3k2(Module):
    def __init__(self, c1: int, c2: int, n: int = 1, k: _Size = 3, e: float = 0.5) -> None:
        super().__init__()
        c_ = int(c2 * e)
        self.cv1 = Conv(c1, c_, 1, 1)
        self.m = DS_C3k(c_, c_, n=n, k=k, e=1.0)
        self.cv2 = Conv(c_, c2, 1, 1)

    def forward(self, x: Tensor) -> Tensor:
        return self.cv2(self.m(self.cv1(x)))


class AdaptiveHyperedgeGeneration(Module):
    """Build a soft vertex→hyperedge assignment from global context."""

    def __init__(self, in_channels: int, num_hyperedges: int, num_heads: int = 8) -> None:
        super().__init__()
        self.num_hyperedges = num_hyperedges
        self.num_heads = num_heads
        self.head_dim = in_channels // num_heads

        self.global_proto = nn.Parameter(torch.randn(num_hyperedges, in_channels))
        self.context_mapper = nn.Linear(
            2 * in_channels, num_hyperedges * in_channels, bias=False
        )
        self.query_proj = nn.Linear(in_channels, in_channels, bias=False)
        self.scale = self.head_dim ** -0.5

    def forward(self, x: Tensor) -> Tensor:
        B, N, C = x.shape

        f_avg = F.adaptive_avg_pool1d(x.permute(0, 2, 1), 1).squeeze(-1)
        f_max = F.adaptive_max_pool1d(x.permute(0, 2, 1), 1).squeeze(-1)
        f_ctx = torch.cat((f_avg, f_max), dim=1)

        delta_P = self.context_mapper(f_ctx).view(B, self.num_hyperedges, C)
        P = self.global_proto.unsqueeze(0) + delta_P

        z = self.query_proj(x)
        z = z.view(B, N, self.num_heads, self.head_dim).permute(0, 2, 1, 3)
        P = P.view(
            B, self.num_hyperedges, self.num_heads, self.head_dim
        ).permute(0, 2, 3, 1)

        sim = (z @ P) * self.scale
        s_bar = sim.mean(dim=1)
        return F.softmax(s_bar.permute(0, 2, 1), dim=-1)


class HypergraphConvolution(Module):
    """Vertex → hyperedge → vertex message passing, residual."""

    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.W_e = nn.Linear(in_channels, in_channels, bias=False)
        self.W_v = nn.Linear(in_channels, out_channels, bias=False)
        self.act = nn.SiLU()

    def forward(self, x: Tensor, A: Tensor) -> Tensor:
        f_m = torch.bmm(A, x)
        f_m = self.act(self.W_e(f_m))

        x_out = torch.bmm(A.transpose(1, 2), f_m)
        x_out = self.act(self.W_v(x_out))
        return x + x_out


class AdaptiveHypergraphComputation(Module):
    def __init__(
        self, in_channels: int, out_channels: int,
        num_hyperedges: int = 8, num_heads: int = 8,
    ) -> None:
        super().__init__()
        self.adaptive_hyperedge_gen = AdaptiveHyperedgeGeneration(
            in_channels, num_hyperedges, num_heads
        )
        self.hypergraph_conv = HypergraphConvolution(in_channels, out_channels)

    def forward(self, x: Tensor) -> Tensor:
        B, _C, H, W = x.shape
        x_flat = x.flatten(2).permute(0, 2, 1)

        A = self.adaptive_hyperedge_gen(x_flat)
        x_out_flat = self.hypergraph_conv(x_flat, A)
        return x_out_flat.permute(0, 2, 1).view(B, -1, H, W)


class C3AH(Module):
    """CSP block whose transformed half goes through hypergraph attention."""

    def __init__(
        self, c1: int, c2: int, num_hyperedges: int = 8,
        num_heads: int = 8, e: float = 0.5,
    ) -> None:
        super().__init__()
        c_ = int(c1 * e)
        self.cv1 = Conv(c1, c_, 1, 1)
        self.cv2 = Conv(c1, c_, 1, 1)
        self.ahc = AdaptiveHypergraphComputation(c_, c_, num_hyperedges, num_heads)
        self.cv3 = Conv(2 * c_, c2, 1, 1)

    def forward(self, x: Tensor) -> Tensor:
        x_lateral = self.cv1(x)
        x_ahc = self.ahc(self.cv2(x))
        return self.cv3(torch.cat((x_ahc, x_lateral), dim=1))


class HyperACE(Module):
    """Fuse the pyramid, then split into high-order, low-order and skip paths."""

    def __init__(
        self, in_channels: Sequence[int], out_channels: int,
        num_hyperedges: int = 8, num_heads: int = 8,
        k: int = 2, l: int = 1, c_h: float = 0.5, c_l: float = 0.25,
    ) -> None:
        super().__init__()
        c2, c3, c4, c5 = in_channels
        c_mid = c4

        self.fuse_conv = Conv(c2 + c3 + c4 + c5, c_mid, 1, 1)

        self.c_h = int(c_mid * c_h)
        self.c_l = int(c_mid * c_l)
        self.c_s = c_mid - self.c_h - self.c_l
        assert self.c_s > 0, "Channel split error"

        self.high_order_branch = nn.ModuleList(
            [C3AH(self.c_h, self.c_h, num_hyperedges, num_heads, e=1.0) for _ in range(k)]
        )
        self.high_order_fuse = Conv(self.c_h * k, self.c_h, 1, 1)
        self.low_order_branch = nn.Sequential(
            *[DS_C3k(self.c_l, self.c_l, n=1, k=3, e=1.0) for _ in range(l)]
        )
        self.final_fuse = Conv(self.c_h + self.c_l + self.c_s, out_channels, 1, 1)

    def forward(self, x: List[Tensor]) -> Tensor:
        B2, B3, B4, B5 = x
        _B, _C, H4, W4 = B4.shape

        size = (H4, W4)
        x_b = self.fuse_conv(torch.cat((
            F.interpolate(B2, size=size, mode="bilinear", align_corners=False),
            F.interpolate(B3, size=size, mode="bilinear", align_corners=False),
            B4,
            F.interpolate(B5, size=size, mode="bilinear", align_corners=False),
        ), dim=1))

        x_h, x_l, x_s = torch.split(x_b, [self.c_h, self.c_l, self.c_s], dim=1)

        x_h_outs = [m(x_h) for m in self.high_order_branch]
        x_h_fused = self.high_order_fuse(torch.cat(x_h_outs, dim=1))
        x_l_out = self.low_order_branch(x_l)

        return self.final_fuse(torch.cat((x_h_fused, x_l_out, x_s), dim=1))


class GatedFusion(Module):
    """Add a HyperACE feature into a decoder level through a learned gate."""

    def __init__(self, in_channels: int) -> None:
        super().__init__()
        self.gamma = nn.Parameter(torch.zeros(1, in_channels, 1, 1))

    def forward(self, f_in: Tensor, h: Tensor) -> Tensor:
        if f_in.shape[1] != h.shape[1]:
            raise ValueError(f"Channel mismatch: f_in={f_in.shape}, h={h.shape}")
        return f_in + self.gamma * h


class Backbone(Module):
    """Depthwise-separable CSP encoder.

    The first three stages stride time only (``(2, 1)``) so the band axis stays
    wide; the last two stride both. Stage widths are fixed upstream —
    ``base_channels`` only sizes the stem.
    """

    def __init__(
        self, in_channels: int = 256, base_channels: int = 64, base_depth: int = 3
    ) -> None:
        super().__init__()
        c2 = base_channels
        c3, c4, c5, c6 = 256, 384, 512, 768

        self.stem = DSConv(in_channels, c2, k=3, s=(2, 1), p=1)
        self.p2 = nn.Sequential(
            DSConv(c2, c3, k=3, s=(2, 1), p=1), DS_C3k2(c3, c3, n=base_depth)
        )
        self.p3 = nn.Sequential(
            DSConv(c3, c4, k=3, s=(2, 1), p=1), DS_C3k2(c4, c4, n=base_depth * 2)
        )
        self.p4 = nn.Sequential(
            DSConv(c4, c5, k=3, s=2, p=1), DS_C3k2(c5, c5, n=base_depth * 2)
        )
        self.p5 = nn.Sequential(
            DSConv(c5, c6, k=3, s=2, p=1), DS_C3k2(c6, c6, n=base_depth)
        )
        self.out_channels = [c3, c4, c5, c6]

    def forward(self, x: Tensor) -> List[Tensor]:
        x = self.stem(x)
        x2 = self.p2(x)
        x3 = self.p3(x2)
        x4 = self.p4(x3)
        x5 = self.p5(x4)
        return [x2, x3, x4, x5]


class Decoder(Module):
    """Top-down FPN decoder, gated at every level by the HyperACE feature."""

    def __init__(
        self, encoder_channels: Sequence[int], hyperace_out_c: int,
        decoder_channels: Sequence[int],
    ) -> None:
        super().__init__()
        c_p2, c_p3, c_p4, c_p5 = encoder_channels
        c_d2, c_d3, c_d4, c_d5 = decoder_channels

        self.h_to_d5 = Conv(hyperace_out_c, c_d5, 1, 1)
        self.h_to_d4 = Conv(hyperace_out_c, c_d4, 1, 1)
        self.h_to_d3 = Conv(hyperace_out_c, c_d3, 1, 1)
        self.h_to_d2 = Conv(hyperace_out_c, c_d2, 1, 1)

        self.fusion_d5 = GatedFusion(c_d5)
        self.fusion_d4 = GatedFusion(c_d4)
        self.fusion_d3 = GatedFusion(c_d3)
        self.fusion_d2 = GatedFusion(c_d2)

        self.skip_p5 = Conv(c_p5, c_d5, 1, 1)
        self.skip_p4 = Conv(c_p4, c_d4, 1, 1)
        self.skip_p3 = Conv(c_p3, c_d3, 1, 1)
        self.skip_p2 = Conv(c_p2, c_d2, 1, 1)

        self.up_d5 = DS_C3k2(c_d5, c_d4, n=1)
        self.up_d4 = DS_C3k2(c_d4, c_d3, n=1)
        self.up_d3 = DS_C3k2(c_d3, c_d2, n=1)
        self.final_d2 = DS_C3k2(c_d2, c_d2, n=1)

    def forward(self, enc_feats: List[Tensor], h_ace: Tensor) -> Tensor:
        p2, p3, p4, p5 = enc_feats

        d5 = self.skip_p5(p5)
        h_d5 = self.h_to_d5(F.interpolate(h_ace, size=d5.shape[2:], mode="bilinear"))
        d5 = self.fusion_d5(d5, h_d5)

        d5_up = F.interpolate(d5, size=p4.shape[2:], mode="bilinear")
        d4 = self.up_d5(d5_up) + self.skip_p4(p4)
        h_d4 = self.h_to_d4(F.interpolate(h_ace, size=d4.shape[2:], mode="bilinear"))
        d4 = self.fusion_d4(d4, h_d4)

        d4_up = F.interpolate(d4, size=p3.shape[2:], mode="bilinear")
        d3 = self.up_d4(d4_up) + self.skip_p3(p3)
        h_d3 = self.h_to_d3(F.interpolate(h_ace, size=d3.shape[2:], mode="bilinear"))
        d3 = self.fusion_d3(d3, h_d3)

        d3_up = F.interpolate(d3, size=p2.shape[2:], mode="bilinear")
        d2 = self.up_d3(d3_up) + self.skip_p2(p2)
        h_d2 = self.h_to_d2(F.interpolate(h_ace, size=d2.shape[2:], mode="bilinear"))
        d2 = self.fusion_d2(d2, h_d2)

        return self.final_d2(d2)


class _TfcTdfBlock(Module):
    """One time-frequency conv + time-distributed fully-connected residual."""

    def __init__(self, in_c: int, c: int, f: int, bn: int) -> None:
        super().__init__()
        self.tfc1 = nn.Sequential(
            nn.InstanceNorm2d(in_c, affine=True, eps=1e-8),
            nn.SiLU(),
            nn.Conv2d(in_c, c, 3, 1, 1, bias=False),
        )
        self.tdf = nn.Sequential(
            nn.InstanceNorm2d(c, affine=True, eps=1e-8),
            nn.SiLU(),
            nn.Linear(f, f // bn, bias=False),
            nn.InstanceNorm2d(c, affine=True, eps=1e-8),
            nn.SiLU(),
            nn.Linear(f // bn, f, bias=False),
        )
        self.tfc2 = nn.Sequential(
            nn.InstanceNorm2d(c, affine=True, eps=1e-8),
            nn.SiLU(),
            nn.Conv2d(c, c, 3, 1, 1, bias=False),
        )
        self.shortcut = nn.Conv2d(in_c, c, 1, 1, 0, bias=False)

    def forward(self, x: Tensor) -> Tensor:
        s = self.shortcut(x)
        x = self.tfc1(x)
        x = x + self.tdf(x)
        x = self.tfc2(x)
        return x + s


class TFC_TDF(Module):
    """Stack of :class:`_TfcTdfBlock`. Distinct from ``ml.tfc_tdf_v3``'s MDX23C block."""

    def __init__(self, in_c: int, c: int, l: int, f: int, bn: int = 4) -> None:
        super().__init__()
        blocks = []
        for _ in range(l):
            blocks.append(_TfcTdfBlock(in_c, c, f, bn))
            in_c = c
        self.blocks = nn.ModuleList(blocks)

    def forward(self, x: Tensor) -> Tensor:
        for block in self.blocks:
            x = block(x)
        return x


class FreqPixelShuffle(Module):
    """Double the frequency axis by folding channels into it."""

    def __init__(self, in_channels: int, out_channels: int, scale: int, f: int) -> None:
        super().__init__()
        self.scale = scale
        self.conv = DSConv(in_channels, out_channels * scale)
        self.out_conv = TFC_TDF(out_channels, out_channels, 2, f)

    def forward(self, x: Tensor) -> Tensor:
        x = self.conv(x)
        B, C_r, H, W = x.shape
        out_c = C_r // self.scale

        x = x.view(B, out_c, self.scale, H, W)
        x = x.permute(0, 1, 3, 4, 2).contiguous()
        x = x.view(B, out_c, H, W * self.scale)
        return self.out_conv(x)


class ProgressiveUpsampleHead(Module):
    """Four pixel-shuffle stages from band resolution up to full STFT bins."""

    def __init__(
        self, in_channels: int, out_channels: int,
        target_bins: int = 1025, in_bands: int = 62,
    ) -> None:
        super().__init__()
        self.target_bins = target_bins
        c = in_channels

        self.block1 = FreqPixelShuffle(c, c // 2, scale=2, f=in_bands * 2)
        self.block2 = FreqPixelShuffle(c // 2, c // 4, scale=2, f=in_bands * 4)
        self.block3 = FreqPixelShuffle(c // 4, c // 8, scale=2, f=in_bands * 8)
        self.block4 = FreqPixelShuffle(c // 8, c // 16, scale=2, f=in_bands * 16)
        self.final_conv = nn.Conv2d(
            c // 16, out_channels, kernel_size=3, stride=1, padding="same", bias=False
        )

    def forward(self, x: Tensor) -> Tensor:
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        x = self.block4(x)

        if x.shape[-1] != self.target_bins:
            x = F.interpolate(
                x, size=(x.shape[2], self.target_bins),
                mode="bilinear", align_corners=False,
            )
        return self.final_conv(x)


class SegmModel(Module):
    """The ``segm`` branch a HyperACE mask estimator adds to its band MLPs."""

    def __init__(
        self, in_bands: int = 62, in_dim: int = 256, out_bins: int = 1025,
        out_channels: int = 4, base_channels: int = 64, base_depth: int = 2,
        num_hyperedges: int = 32, num_heads: int = 8,
    ) -> None:
        super().__init__()
        self.backbone = Backbone(
            in_channels=in_dim, base_channels=base_channels, base_depth=base_depth
        )
        enc_channels = self.backbone.out_channels
        _c2, _c3, c4, _c5 = enc_channels

        self.hyperace = HyperACE(
            enc_channels, c4, num_hyperedges, num_heads, k=2, l=1
        )
        self.decoder = Decoder(enc_channels, c4, enc_channels)
        self.upsample_head = ProgressiveUpsampleHead(
            in_channels=enc_channels[0],
            out_channels=out_channels,
            target_bins=out_bins,
            in_bands=in_bands,
        )

    def forward(self, x: Tensor) -> Tensor:
        H = x.shape[2]

        enc_feats = self.backbone(x)
        h_ace_feats = self.hyperace(enc_feats)
        dec_feat = self.decoder(enc_feats, h_ace_feats)

        # The backbone strided time away; restore it before the frequency head.
        feat_time_restored = F.interpolate(
            dec_feat, size=(H, dec_feat.shape[-1]), mode="bilinear", align_corners=False
        )
        return self.upsample_head(feat_time_restored)
