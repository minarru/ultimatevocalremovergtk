from __future__ import annotations

from functools import partial
from typing import Any, Callable, Optional, Tuple, TypeVar, cast

import torch
from torch import nn, einsum, Tensor
from torch.nn import Module, ModuleList, Sequential
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

from .attend import Attend

from beartype.typing import Tuple as BeartypeTuple, Optional as BeartypeOptional, List, Callable as BeartypeCallable
from beartype import BeartypeConf, beartype as _beartype

# Model yamls write integer literals for float hyper-parameters
# (``attn_dropout: 0``). PEP 484's implicit numeric tower accepts int where
# float is annotated; beartype's default configuration does not.
beartype = _beartype(conf=BeartypeConf(is_pep484_tower=True))

from rotary_embedding_torch import RotaryEmbedding
from PoPE_pytorch import PoPE, flash_attn_with_pope

from einops import rearrange, pack, unpack
from einops.layers.torch import Rearrange

from ml.stft_device import needs_cpu_stft, torch_istft, torch_stft

# helper functions

T = TypeVar('T')

def exists(val: object) -> bool:
    return val is not None


def default(v: T | None, d: T) -> T:
    if v is not None:
        return v
    return d


def pack_one(t: Tensor, pattern: str) -> tuple[Tensor, list[Any]]:
    return pack([t], pattern)


def unpack_one(t: Tensor, ps: list[Any], pattern: str) -> Tensor:
    return unpack(t, ps, pattern)[0]


# norm

def l2norm(t: Tensor) -> Tensor:
    return F.normalize(t, dim = -1, p = 2)


class RMSNorm(Module):
    def __init__(self, dim: int) -> None:
        super().__init__()
        self.scale = dim ** 0.5
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x: Tensor) -> Tensor:
        x = x.to(self.gamma.device)
        return F.normalize(x, dim=-1) * self.scale * self.gamma


# attention

class FeedForward(Module):
    def __init__(
            self,
            dim: int,
            mult: int = 4,
            dropout: float = 0.
    ) -> None:
        super().__init__()
        dim_inner = int(dim * mult)
        self.net = nn.Sequential(
            RMSNorm(dim),
            nn.Linear(dim, dim_inner),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(dim_inner, dim),
            nn.Dropout(dropout)
        )

    def forward(self, x: Tensor) -> Tensor:
        return self.net(x)


class Attention(Module):
    def __init__(
            self,
            dim: int,
            heads: int = 8,
            dim_head: int = 64,
            dropout: float = 0.,
            rotary_embed: RotaryEmbedding | None = None,
            pope_embed: PoPE | None = None,
            flash: bool = True,
            learned_value_residual_mix: bool = False
    ) -> None:
        super().__init__()
        self.heads = heads
        self.scale = dim_head ** -0.5
        dim_inner = heads * dim_head

        self.rotary_embed = rotary_embed
        self.pope_embed = pope_embed
        assert not (self.rotary_embed is not None and self.pope_embed is not None), \
            'cannot have both rotary and pope embeddings'

        self.attend = Attend(flash=flash, dropout=dropout)

        self.norm = RMSNorm(dim)
        self.to_qkv = nn.Linear(dim, dim_inner * 3, bias=False)

        # Value Residual Learning (arXiv:2410.17897): later layers mix their
        # own value projection with the first layer's, gated per head. Only
        # present on checkpoints trained with it (e.g. Inst-EXP-Value-Residual),
        # which is why this is a subtree that may simply not exist.
        self.to_value_residual_mix = nn.Linear(dim, heads) if learned_value_residual_mix else None

        self.to_gates = nn.Linear(dim, heads)

        self.to_out = nn.Sequential(
            nn.Linear(dim_inner, dim, bias=False),
            nn.Dropout(dropout)
        )

    def forward(self, x: Tensor, value_residual: Tensor | None = None) -> tuple[Tensor, Tensor]:
        x = self.norm(x)

        q, k, v = rearrange(self.to_qkv(x), 'b n (qkv h d) -> qkv b h n d', qkv=3, h=self.heads)
        orig_v = v

        if self.to_value_residual_mix is not None:
            assert value_residual is not None
            mix = self.to_value_residual_mix(x)
            mix = rearrange(mix, 'b n h -> b h n 1').sigmoid()
            v = v.lerp(value_residual, mix)

        if self.pope_embed is not None:
            out = flash_attn_with_pope(q, k, v, pos_emb=self.pope_embed(q.shape[-2]), softmax_scale=self.scale)
        else:
            if self.rotary_embed is not None:
                q = self.rotary_embed.rotate_queries_or_keys(q)
                k = self.rotary_embed.rotate_queries_or_keys(k)

            out = self.attend(q, k, v)

        gates = self.to_gates(x)
        out = out * rearrange(gates, 'b n h -> b h n 1').sigmoid()

        out = rearrange(out, 'b h n d -> b n (h d)')
        return self.to_out(out), orig_v


class LinearAttention(Module):
    """
    this flavor of linear attention proposed in https://arxiv.org/abs/2106.09681 by El-Nouby et al.
    """

    @beartype
    def __init__(
            self,
            *,
            dim: int,
            dim_head: int = 32,
            heads: int = 8,
            scale: int = 8,
            flash: bool = False,
            dropout: float = 0.
    ) -> None:
        super().__init__()
        dim_inner = dim_head * heads
        self.norm = RMSNorm(dim)

        self.to_qkv = nn.Sequential(
            nn.Linear(dim, dim_inner * 3, bias=False),
            Rearrange('b n (qkv h d) -> qkv b h d n', qkv=3, h=heads)
        )

        self.temperature = nn.Parameter(torch.ones(heads, 1, 1))

        self.attend = Attend(
            dropout=dropout,
            flash=flash
        )

        self.to_out = nn.Sequential(
            Rearrange('b h d n -> b n (h d)'),
            nn.Linear(dim_inner, dim, bias=False)
        )

    def forward(
            self,
            x: Tensor
    ) -> Tensor:
        x = self.norm(x)

        q, k, v = self.to_qkv(x)

        q, k = map(l2norm, (q, k))
        q = q * self.temperature.exp()

        out = self.attend(q, k, v)

        return self.to_out(out)


AttnModule = Attention | LinearAttention


class Transformer(Module):
    def __init__(
            self,
            *,
            dim: int,
            depth: int,
            dim_head: int = 64,
            heads: int = 8,
            attn_dropout: float = 0.,
            ff_dropout: float = 0.,
            ff_mult: int = 4,
            norm_output: bool = True,
            rotary_embed: RotaryEmbedding | None = None,
            pope_embed: PoPE | None = None,
            flash_attn: bool = True,
            linear_attn: bool = False,
            add_value_residual: bool = False
    ) -> None:
        super().__init__()
        self.layers = ModuleList([])
        self.linear_attn = linear_attn

        for _ in range(depth):
            if linear_attn:
                attn: AttnModule = LinearAttention(dim=dim, dim_head=dim_head, heads=heads, dropout=attn_dropout, flash=flash_attn)
            else:
                attn = Attention(dim=dim, dim_head=dim_head, heads=heads, dropout=attn_dropout,
                                 rotary_embed=rotary_embed, pope_embed=pope_embed, flash=flash_attn,
                                 learned_value_residual_mix=add_value_residual)

            self.layers.append(ModuleList([
                attn,
                FeedForward(dim=dim, mult=ff_mult, dropout=ff_dropout)
            ]))

        self.norm = RMSNorm(dim) if norm_output else nn.Identity()

    def forward(self, x: Tensor, value_residual: Tensor | None = None) -> tuple[Tensor, Tensor | None]:
        first_values: Tensor | None = None

        for layer in self.layers:
            layer_pair = cast(ModuleList, layer)
            attn, ff = cast(tuple[AttnModule, FeedForward], (layer_pair[0], layer_pair[1]))
            if self.linear_attn:
                x = cast(Tensor, attn(x)) + x
            else:
                attn_out, next_values = cast(Tuple[Tensor, Tensor], attn(x, value_residual=value_residual))
                x = attn_out + x
                first_values = default(first_values, next_values)
            x = ff(x) + x

        return self.norm(x), first_values


# bandsplit module

class BandSplit(Module):
    @beartype
    def __init__(
            self,
            dim: int,
            dim_inputs: BeartypeTuple[int, ...]
    ) -> None:
        super().__init__()
        self.dim_inputs = dim_inputs
        self.to_features = ModuleList([])

        for dim_in in dim_inputs:
            net = nn.Sequential(
                RMSNorm(dim_in),
                nn.Linear(dim_in, dim)
            )

            self.to_features.append(net)

    def forward(self, x: Tensor) -> Tensor:
        splits = x.split(self.dim_inputs, dim=-1)

        outs = []
        for split_input, to_feature in zip(splits, cast(list[Sequential], list(self.to_features))):
            split_output = to_feature(split_input)
            outs.append(split_output)

        return torch.stack(outs, dim=-2)


def MLP(
        dim_in: int,
        dim_out: int,
        dim_hidden: int | None = None,
        depth: int = 1,
        activation: type[Module] = nn.Tanh
) -> Sequential:
    resolved_dim_hidden = default(dim_hidden, dim_in)

    net: list[Module] = []
    dims = (dim_in, *((resolved_dim_hidden,) * (depth - 1)), dim_out)

    for ind, (layer_dim_in, layer_dim_out) in enumerate(zip(dims[:-1], dims[1:])):
        is_last = ind == (len(dims) - 2)

        net.append(nn.Linear(layer_dim_in, layer_dim_out))

        if is_last:
            continue

        net.append(activation())

    return nn.Sequential(*net)


class MaskEstimator(Module):
    @beartype
    def __init__(
            self,
            dim: int,
            dim_inputs: BeartypeTuple[int, ...],
            depth: int,
            mlp_expansion_factor: int = 4,
            hyperace: bool | str = False,
    ) -> None:
        super().__init__()
        self.dim_inputs = dim_inputs
        self.to_freqs = ModuleList([])
        dim_hidden = dim * mlp_expansion_factor

        for dim_in in dim_inputs:
            mlp = nn.Sequential(
                MLP(dim, dim_in * 2, dim_hidden=dim_hidden, depth=depth),
                nn.GLU(dim=-1)
            )

            self.to_freqs.append(mlp)

        # HyperACE checkpoints add a segmentation branch whose output is summed
        # onto the per-band MLP masks. Absent unless the config asks for it —
        # the parameter names are ``segm.*`` and must not appear otherwise.
        self.segm = None
        if hyperace:
            from ml.hyperace import VARIANT_V2, SegmModel

            self.segm = SegmModel(
                in_bands=len(dim_inputs),
                in_dim=dim,
                out_bins=sum(dim_inputs) // 4,
                variant=hyperace if isinstance(hyperace, str) else VARIANT_V2,
            )

    def forward(self, x: Tensor) -> Tensor:
        segm_out = None
        if self.segm is not None:
            y = rearrange(x, 'b t f c -> b c t f')
            y = self.segm(y)
            segm_out = rearrange(y, 'b c t f -> b t (f c)')

        bands = x.unbind(dim=-2)

        outs = []

        for band_features, mlp in zip(bands, cast(list[Sequential], list(self.to_freqs))):
            freq_out = mlp(band_features)
            outs.append(freq_out)

        masks = torch.cat(outs, dim=-1)
        return masks if segm_out is None else masks + segm_out


# main class

DEFAULT_FREQS_PER_BANDS = (
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2,
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4,
    12, 12, 12, 12, 12, 12, 12, 12,
    24, 24, 24, 24, 24, 24, 24, 24,
    48, 48, 48, 48, 48, 48, 48, 48,
    128, 129,
)


class BSRoformer(Module):

    @beartype
    def __init__(
            self,
            dim: int,
            *,
            depth: int,
            stereo: bool = False,
            num_stems: int = 1,
            time_transformer_depth: int = 2,
            freq_transformer_depth: int = 2,
            linear_transformer_depth: int = 0,
            freqs_per_bands: BeartypeTuple[int, ...] = DEFAULT_FREQS_PER_BANDS,
            # in the paper, they divide into ~60 bands, test with 1 for starters
            dim_head: int = 64,
            heads: int = 8,
            attn_dropout: float = 0.,
            ff_dropout: float = 0.,
            flash_attn: bool = True,
            dim_freqs_in: int = 1025,
            stft_n_fft: int = 2048,
            stft_hop_length: int = 512,
            # 10ms at 44100Hz, from sections 4.1, 4.4 in the paper - @faroit recommends // 2 or // 4 for better reconstruction
            stft_win_length: int = 2048,
            stft_normalized: bool = False,
            stft_window_fn: BeartypeOptional[BeartypeCallable[..., Tensor]] = None,
            mask_estimator_depth: int = 2,
            multi_stft_resolution_loss_weight: float = 1.,
            multi_stft_resolutions_window_sizes: BeartypeTuple[int, ...] = (4096, 2048, 1024, 512, 256),
            multi_stft_hop_size: int = 147,
            multi_stft_normalized: bool = False,
            multi_stft_window_fn: BeartypeCallable[..., Tensor] = torch.hann_window,
            mlp_expansion_factor: int = 4,
            use_torch_checkpoint: bool = False,
            skip_connection: bool = False,
            # HyperACE checkpoints attach a segmentation branch to every mask
            # estimator. Enabled from the config's top-level ``hyperace2`` flag,
            # not from the ``model:`` section — see engines.mdx_c._build_mdx_c_model.
            # Accepts a variant name (``"v1"``/``"v2"``) or a bool meaning v2.
            hyperace: bool | str = False,
            # Value Residual Learning (arXiv:2410.17897). Detected from the
            # checkpoint's own ``to_value_residual_mix`` keys in
            # engines.mdx_c._build_mdx_c_model, not read from the yaml.
            value_residual: bool = False,
            # Polar Coordinate Positional Embedding (arXiv:2509.10534), a
            # RoPE replacement used by some community "BS PolarFormer"
            # checkpoints. Unlike hyperace/value_residual above, this one
            # yaml keys line up with the constructor arg directly, so no
            # checkpoint-key detection is needed.
            use_pope: bool = False,
    ) -> None:
        super().__init__()

        self.stereo = stereo
        self.audio_channels = 2 if stereo else 1
        self.num_stems = num_stems
        self.use_torch_checkpoint = use_torch_checkpoint
        self.skip_connection = skip_connection

        self.layers = ModuleList([])

        transformer_kwargs: dict[str, Any] = dict(
            dim=dim,
            heads=heads,
            dim_head=dim_head,
            attn_dropout=attn_dropout,
            ff_dropout=ff_dropout,
            flash_attn=flash_attn,
            norm_output=False
        )

        time_rotary_embed: RotaryEmbedding | None
        freq_rotary_embed: RotaryEmbedding | None
        time_pope_embed: PoPE | None
        freq_pope_embed: PoPE | None
        if use_pope:
            time_pope_embed = PoPE(dim=dim_head, heads=heads)
            freq_pope_embed = PoPE(dim=dim_head, heads=heads)
            time_rotary_embed = freq_rotary_embed = None
        else:
            time_rotary_embed = RotaryEmbedding(dim=dim_head)
            freq_rotary_embed = RotaryEmbedding(dim=dim_head)
            time_pope_embed = freq_pope_embed = None

        for layer_index in range(depth):
            # The first layer has no prior value stream to mix with.
            is_first = layer_index == 0
            tran_modules: list[Transformer] = []
            if linear_transformer_depth > 0:
                tran_modules.append(Transformer(depth=linear_transformer_depth, linear_attn=True, **transformer_kwargs))
            tran_modules.append(
                Transformer(depth=time_transformer_depth, rotary_embed=time_rotary_embed, pope_embed=time_pope_embed,
                            add_value_residual=value_residual and not is_first, **transformer_kwargs)
            )
            tran_modules.append(
                Transformer(depth=freq_transformer_depth, rotary_embed=freq_rotary_embed, pope_embed=freq_pope_embed,
                            add_value_residual=value_residual and not is_first, **transformer_kwargs)
            )
            self.layers.append(nn.ModuleList(tran_modules))

        self.final_norm = RMSNorm(dim)

        self.stft_kwargs: dict[str, Any] = dict(
            n_fft=stft_n_fft,
            hop_length=stft_hop_length,
            win_length=stft_win_length,
            normalized=stft_normalized
        )

        _stft_window_fn = default(stft_window_fn, torch.hann_window)
        self.stft_window_fn: Callable[..., Tensor] = partial(_stft_window_fn, stft_win_length)

        freqs = torch.stft(
            torch.randn(1, 4096), **self.stft_kwargs, window=self.stft_window_fn(), return_complex=True
        ).shape[1]

        assert len(freqs_per_bands) > 1
        assert sum(
            freqs_per_bands) == freqs, f'the number of freqs in the bands must equal {freqs} based on the STFT settings, but got {sum(freqs_per_bands)}'

        freqs_per_bands_with_complex = tuple(2 * f * self.audio_channels for f in freqs_per_bands)

        self.band_split = BandSplit(
            dim=dim,
            dim_inputs=freqs_per_bands_with_complex
        )

        self.mask_estimators = nn.ModuleList([])

        for _ in range(num_stems):
            mask_estimator = MaskEstimator(
                dim=dim,
                dim_inputs=freqs_per_bands_with_complex,
                depth=mask_estimator_depth,
                mlp_expansion_factor=mlp_expansion_factor,
                hyperace=hyperace,
            )

            self.mask_estimators.append(mask_estimator)

        # for the multi-resolution stft loss

        self.multi_stft_resolution_loss_weight = multi_stft_resolution_loss_weight
        self.multi_stft_resolutions_window_sizes = multi_stft_resolutions_window_sizes
        self.multi_stft_n_fft = stft_n_fft
        self.multi_stft_window_fn = multi_stft_window_fn

        self.multi_stft_kwargs: dict[str, Any] = dict(
            hop_length=multi_stft_hop_size,
            normalized=multi_stft_normalized
        )

    def forward(
            self,
            raw_audio: Tensor,
            target: Tensor | None = None,
            return_loss_breakdown: bool = False
    ) -> Tensor | tuple[Tensor, tuple[Tensor, Tensor | float]]:
        """
        einops

        b - batch
        f - freq
        t - time
        s - audio channel (1 for mono, 2 for stereo)
        n - number of 'stems'
        c - complex (2)
        d - feature dimension
        """

        original_device = raw_audio.device
        bounce = needs_cpu_stft(original_device)
        device = original_device

        if raw_audio.ndim == 2:
            raw_audio = rearrange(raw_audio, 'b t -> b 1 t')

        channels = raw_audio.shape[1]
        assert (not self.stereo and channels == 1) or (
                    self.stereo and channels == 2), 'stereo needs to be set to True if passing in audio signal that is stereo (channel dimension of 2). also need to be False if mono (channel dimension of 1)'

        # to stft (CPU bounce only for the STFT call)

        raw_audio, batch_audio_channel_packed_shape = pack_one(raw_audio, '* t')
        istft_length = raw_audio.shape[-1]

        stft_window = self.stft_window_fn(device=device)

        stft_repr = torch_stft(raw_audio, **self.stft_kwargs, window=stft_window, return_complex=True)
        stft_repr = torch.view_as_real(stft_repr)
        if bounce:
            stft_repr = stft_repr.to(device)

        stft_repr = unpack_one(stft_repr, batch_audio_channel_packed_shape, '* f t c')
        stft_repr = rearrange(stft_repr,
                              'b s f t c -> b (f s) t c')  # merge stereo / mono into the frequency, with frequency leading dimension, for band splitting

        x = rearrange(stft_repr, 'b f t c -> b t (f c)')

        if self.use_torch_checkpoint:
            x = cast(Tensor, checkpoint(self.band_split, x, use_reentrant=False))
        else:
            x = self.band_split(x)

        # axial / hierarchical attention (stays on accelerator)

        store: list[Tensor | None] = [None] * len(self.layers)
        # Value residual anchors: the first layer's un-mixed value projection,
        # reused by every later layer's ``to_value_residual_mix`` gate. Stay
        # None on checkpoints without that subtree, where nothing reads them.
        time_v_residual: Tensor | None = None
        freq_v_residual: Tensor | None = None
        for i, transformer_block in enumerate(self.layers):
            block_list = cast(ModuleList, transformer_block)
            block = cast(list[Transformer], [block_list[j] for j in range(len(block_list))])

            if len(block) == 3:
                linear_transformer, time_transformer, freq_transformer = block

                x, ft_ps = pack([x], 'b * d')
                if self.use_torch_checkpoint:
                    x = cast(Tuple[Tensor, Optional[Tensor]], checkpoint(linear_transformer, x, None, use_reentrant=False))[0]
                else:
                    x, _ = linear_transformer(x)
                x, = unpack(x, ft_ps, 'b * d')
            else:
                time_transformer, freq_transformer = block

            # MSST: skip-sum after optional linear block, before time/freq.
            if self.skip_connection:
                for j in range(i):
                    previous = store[j]
                    if previous is not None:
                        x = x + previous

            x = rearrange(x, 'b t f d -> b f t d')
            x, ps = pack([x], '* t d')

            if self.use_torch_checkpoint:
                x, next_time_v_residual = cast(
                    Tuple[Tensor, Optional[Tensor]],
                    checkpoint(time_transformer, x, time_v_residual, use_reentrant=False),
                )
            else:
                x, next_time_v_residual = time_transformer(x, value_residual=time_v_residual)
            time_v_residual = default(time_v_residual, next_time_v_residual)

            x, = unpack(x, ps, '* t d')
            x = rearrange(x, 'b f t d -> b t f d')
            x, ps = pack([x], '* f d')

            if self.use_torch_checkpoint:
                x, next_freq_v_residual = cast(
                    Tuple[Tensor, Optional[Tensor]],
                    checkpoint(freq_transformer, x, freq_v_residual, use_reentrant=False),
                )
            else:
                x, next_freq_v_residual = freq_transformer(x, value_residual=freq_v_residual)
            freq_v_residual = default(freq_v_residual, next_freq_v_residual)

            x, = unpack(x, ps, '* f d')
            if self.skip_connection:
                store[i] = x

        x = self.final_norm(x)

        num_stems = len(self.mask_estimators)

        mask = torch.stack([fn(x) for fn in cast(list[MaskEstimator], list(self.mask_estimators))], dim=1)
        mask = rearrange(mask, 'b n t (f c) -> b n f t c', c=2)

        # Complex multiply + iSTFT are unreliable on MPS — finish on CPU.
        if bounce:
            mask = mask.cpu()
            stft_repr = stft_repr.cpu()
            stft_window = stft_window.cpu()

        # modulate frequency representation

        stft_repr = rearrange(stft_repr, 'b f t c -> b 1 f t c')

        # complex number multiplication

        stft_repr = torch.view_as_complex(stft_repr)
        mask = torch.view_as_complex(mask)

        stft_repr = stft_repr * mask

        # istft

        stft_repr = rearrange(stft_repr, 'b n (f s) t -> (b n s) f t', s=self.audio_channels)

        recon_audio = torch_istft(
            stft_repr,
            **self.stft_kwargs,
            window=stft_window,
            return_complex=False,
            length=istft_length,
        )

        recon_audio = rearrange(recon_audio, '(b n s) t -> b n s t', s=self.audio_channels, n=num_stems)

        if num_stems == 1:
            recon_audio = rearrange(recon_audio, 'b 1 s t -> b s t')

        if bounce:
            recon_audio = recon_audio.to(original_device)

        # if a target is passed in, calculate loss for learning

        if not exists(target):
            return recon_audio

        assert target is not None

        if self.num_stems > 1:
            assert target.ndim == 4 and target.shape[1] == self.num_stems

        if target.ndim == 2:
            target = rearrange(target, '... t -> ... 1 t')

        target = target[..., :recon_audio.shape[-1]]

        loss = F.l1_loss(recon_audio, target)

        multi_stft_resolution_loss = 0.

        for window_size in self.multi_stft_resolutions_window_sizes:
            res_window = self.multi_stft_window_fn(window_size, device=device)
            res_stft_kwargs: dict[str, Any] = dict(
                n_fft=max(window_size, self.multi_stft_n_fft),
                win_length=window_size,
                return_complex=True,
                window=res_window,
                **self.multi_stft_kwargs,
            )

            recon_Y = torch_stft(rearrange(recon_audio, '... s t -> (... s) t'), **res_stft_kwargs)
            target_Y = torch_stft(rearrange(target, '... s t -> (... s) t'), **res_stft_kwargs)

            multi_stft_resolution_loss = multi_stft_resolution_loss + F.l1_loss(recon_Y, target_Y)

        weighted_multi_resolution_loss = multi_stft_resolution_loss * self.multi_stft_resolution_loss_weight

        total_loss = loss + weighted_multi_resolution_loss

        if not return_loss_breakdown:
            return total_loss

        return total_loss, (loss, multi_stft_resolution_loss)
