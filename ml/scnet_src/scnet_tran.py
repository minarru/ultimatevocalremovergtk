"""SCNet Tran: dual-path-Transformer variant of SCNet (ported from MSST ``SCNet_Tran``).

Replaces the dual-path LSTM separation network with dual-path Transformers using
rotary position embeddings, reusing ``ml.attend.Attend`` for the attention kernel
and the shared SDblock/FusionLayer/SUlayer encoder-decoder blocks from ``scnet.py``.
"""

from __future__ import annotations

from collections import deque
from typing import TypedDict, cast

import torch
import torch.nn as nn
import torch.nn.functional as F
from einops import rearrange
from rotary_embedding_torch import RotaryEmbedding

from ml.attend import Attend

from .scnet import BandConfigs, ConvConfig, FusionLayer, SDblock, SUlayer
from .separation import FeatureConversion


class TranParams(TypedDict):
    rotary_embedding_dim: int
    depth: int
    heads: int
    dim_head: int
    attn_dropout: float
    ff_dropout: float
    flash_attn: bool


class RMSNorm(nn.Module):
    def __init__(self, dim: int) -> None:
        super().__init__()
        self.scale = dim**0.5
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.normalize(x, dim=-1) * self.scale * self.gamma


class FeedForward(nn.Module):
    def __init__(self, dim: int, mult: int = 4, dropout: float = 0.0) -> None:
        super().__init__()
        dim_inner = int(dim * mult)
        self.net = nn.Sequential(
            RMSNorm(dim),
            nn.Linear(dim, dim_inner),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(dim_inner, dim),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class Attention(nn.Module):
    def __init__(
        self,
        dim: int,
        heads: int = 8,
        dim_head: int = 64,
        dropout: float = 0.0,
        rotary_embed: RotaryEmbedding | None = None,
        flash: bool = True,
    ) -> None:
        super().__init__()
        self.heads = heads
        dim_inner = heads * dim_head

        self.rotary_embed = rotary_embed
        self.attend = Attend(flash=flash, dropout=dropout)

        self.norm = RMSNorm(dim)
        self.to_qkv = nn.Linear(dim, dim_inner * 3, bias=False)
        self.to_gates = nn.Linear(dim, heads)
        self.to_out = nn.Sequential(
            nn.Linear(dim_inner, dim, bias=False),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.norm(x)

        q, k, v = rearrange(self.to_qkv(x), "b n (qkv h d) -> qkv b h n d", qkv=3, h=self.heads)

        if self.rotary_embed is not None:
            q = self.rotary_embed.rotate_queries_or_keys(q)
            k = self.rotary_embed.rotate_queries_or_keys(k)

        out = self.attend(q, k, v)

        gates = self.to_gates(x)
        out = out * rearrange(gates, "b n h -> b h n 1").sigmoid()

        out = rearrange(out, "b h n d -> b n (h d)")
        return self.to_out(out)


class Transformer(nn.Module):
    def __init__(
        self,
        *,
        dim: int,
        depth: int,
        dim_head: int = 64,
        heads: int = 8,
        attn_dropout: float = 0.0,
        ff_dropout: float = 0.0,
        ff_mult: int = 4,
        norm_output: bool = True,
        rotary_embed: RotaryEmbedding | None = None,
        flash_attn: bool = True,
    ) -> None:
        super().__init__()
        self.layers = nn.ModuleList()

        for _ in range(depth):
            attn = Attention(
                dim=dim,
                dim_head=dim_head,
                heads=heads,
                dropout=attn_dropout,
                rotary_embed=rotary_embed,
                flash=flash_attn,
            )
            ff = FeedForward(dim=dim, mult=ff_mult, dropout=ff_dropout)
            self.layers.append(nn.ModuleList([attn, ff]))

        self.norm: nn.Module = RMSNorm(dim) if norm_output else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for layer in self.layers:
            pair = cast(nn.ModuleList, layer)
            attn = cast(Attention, pair[0])
            ff = cast(FeedForward, pair[1])
            x = attn(x) + x
            x = ff(x) + x

        return self.norm(x)


class DualPathTran(nn.Module):
    """
    Dual-Path Transformer in Separation Network.

    Args:
        d_model (int): The number of expected features in the input (input_size).
        time_rotary_embed (RotaryEmbedding): Rotary embedding shared across time-path layers.
        freq_rotary_embed (RotaryEmbedding): Rotary embedding shared across frequency-path layers.
        tran_params (TranParams): Transformer hyper-parameters.
    """

    def __init__(
        self,
        d_model: int,
        time_rotary_embed: RotaryEmbedding,
        freq_rotary_embed: RotaryEmbedding,
        tran_params: TranParams,
    ) -> None:
        super().__init__()

        self.d_model = d_model

        self.norm_layers = nn.ModuleList([nn.GroupNorm(1, d_model) for _ in range(2)])
        self.time_layer = Transformer(
            dim=d_model,
            depth=tran_params["depth"],
            heads=tran_params["heads"],
            dim_head=tran_params["dim_head"],
            attn_dropout=tran_params["attn_dropout"],
            ff_dropout=tran_params["ff_dropout"],
            flash_attn=tran_params["flash_attn"],
            rotary_embed=time_rotary_embed,
        )
        self.freq_layer = Transformer(
            dim=d_model,
            depth=tran_params["depth"],
            heads=tran_params["heads"],
            dim_head=tran_params["dim_head"],
            attn_dropout=tran_params["attn_dropout"],
            ff_dropout=tran_params["ff_dropout"],
            flash_attn=tran_params["flash_attn"],
            rotary_embed=freq_rotary_embed,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, C, Fr, T = x.shape

        # Frequency-path
        original_x = x
        x = self.norm_layers[0](x)
        x = x.transpose(1, 3).contiguous().view(B * T, Fr, C)
        x = self.freq_layer(x)
        x = x.view(B, T, Fr, C).transpose(1, 3)
        x = x + original_x

        # Time-path
        original_x = x
        x = self.norm_layers[1](x)
        x = x.transpose(1, 2).contiguous().view(B * Fr, C, T).transpose(1, 2)
        x = self.time_layer(x)
        x = x.transpose(1, 2).contiguous().view(B, Fr, C, T).transpose(1, 2)
        x = x + original_x

        return x


class SeparationNetTran(nn.Module):
    """
    Dual-path-Transformer separation network, matching ``SeparationNet``'s
    encoder/decoder-facing shape contract but replacing the LSTM dual-path
    blocks with ``DualPathTran``.

    Args:
    - channels (int): Number input channels.
    - num_layers (int): Number of dual-path layers.
    - tran_params (TranParams): Transformer hyper-parameters shared across layers.
    """

    def __init__(self, channels: int, num_layers: int, tran_params: TranParams) -> None:
        super().__init__()

        self.num_layers = num_layers

        time_rotary_embed = RotaryEmbedding(dim=tran_params["rotary_embedding_dim"])
        freq_rotary_embed = RotaryEmbedding(dim=tran_params["rotary_embedding_dim"])

        self.dp_modules = nn.ModuleList([
            DualPathTran(channels * (2 if i % 2 == 1 else 1), time_rotary_embed, freq_rotary_embed, tran_params)
            for i in range(num_layers)
        ])

        self.feature_conversion = nn.ModuleList([
            FeatureConversion(channels * 2, inverse=i % 2 != 0) for i in range(num_layers)
        ])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        for i in range(self.num_layers):
            x = self.dp_modules[i](x)
            x = self.feature_conversion[i](x)
        return x


class SCNetTran(nn.Module):
    """
    MSST "Tran" variant of SCNet: the LSTM dual-path separation network is replaced
    by dual-path Transformers with rotary position embeddings. See:
    https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/models/scnet/scnet_tran.py

    Args:
    - sources (List[str]): List of sources to be separated.
    - audio_channels (int): Number of audio channels.
    - nfft (int): Number of FFTs to determine the frequency dimension of the input.
    - hop_size (int): Hop size for the STFT.
    - win_size (int): Window size for STFT.
    - normalized (bool): Whether to normalize the STFT.
    - dims (List[int]): List of channel dimensions for each block.
    - band_SR (List[float]): The proportion of each frequency band.
    - band_stride (List[int]): The down-sampling ratio of each frequency band.
    - band_kernel (List[int]): The kernel sizes for down-sampling convolution in each frequency band
    - conv_depths (List[int]): List specifying the number of convolution modules in each SD block.
    - compress (int): Compression factor for convolution module.
    - conv_kernel (int): Kernel size for convolution layer in convolution module.
    - num_dplayer (int): Number of dual-path layers.
    - expand (int): Accepted for config parity with SCNet's dual-path RNN; unused by the
      Transformer-based separation network.
    - tran_rotary_embedding_dim (int): Rotary embedding dimension shared by time/freq layers.
    - tran_depth (int): Number of Transformer blocks per dual-path layer.
    - tran_heads (int): Number of attention heads.
    - tran_dim_head (int): Per-head dimension.
    - tran_attn_dropout (float): Attention dropout.
    - tran_ff_dropout (float): Feed-forward dropout.
    - tran_flash_attn (bool): Whether to use PyTorch's scaled-dot-product-attention backend.
    """

    def __init__(
        self,
        sources: list[str] = ["drums", "bass", "other", "vocals"],  # noqa: B006 — upstream default
        audio_channels: int = 2,
        # Main structure
        dims: list[int] = [4, 32, 64, 128],  # noqa: B006 — upstream default
        # STFT
        nfft: int = 4096,
        hop_size: int = 1024,
        win_size: int = 4096,
        normalized: bool = True,
        # SD/SU layer
        band_SR: list[float] = [0.175, 0.392, 0.433],  # noqa: B006 — upstream default
        band_stride: list[int] = [1, 4, 16],  # noqa: B006 — upstream default
        band_kernel: list[int] = [3, 4, 16],  # noqa: B006 — upstream default
        # Convolution Module
        conv_depths: list[int] = [3, 2, 1],  # noqa: B006 — upstream default
        compress: int = 4,
        conv_kernel: int = 3,
        # Dual-path Transformer
        num_dplayer: int = 6,
        expand: int = 1,
        tran_rotary_embedding_dim: int = 64,
        tran_depth: int = 1,
        tran_heads: int = 8,
        tran_dim_head: int = 64,
        tran_attn_dropout: float = 0.0,
        tran_ff_dropout: float = 0.0,
        tran_flash_attn: bool = False,
    ) -> None:
        super().__init__()
        del expand  # unused by the Transformer-based separation network; kept for config parity
        self.sources = sources
        self.audio_channels = audio_channels
        self.dims = dims
        band_keys = ["low", "mid", "high"]
        self.band_configs: BandConfigs = {
            band_keys[i]: {"SR": band_SR[i], "stride": band_stride[i], "kernel": band_kernel[i]}
            for i in range(len(band_keys))
        }
        self.hop_length = hop_size
        self.win_size = win_size
        self.conv_config: ConvConfig = {
            "compress": compress,
            "kernel": conv_kernel,
        }
        self.tran_params: TranParams = {
            "rotary_embedding_dim": tran_rotary_embedding_dim,
            "depth": tran_depth,
            "heads": tran_heads,
            "dim_head": tran_dim_head,
            "attn_dropout": tran_attn_dropout,
            "ff_dropout": tran_ff_dropout,
            "flash_attn": tran_flash_attn,
        }

        self.stft_config = {
            "n_fft": nfft,
            "hop_length": hop_size,
            "win_length": win_size,
            "center": True,
            "normalized": normalized,
        }

        self.encoder = nn.ModuleList()
        self.decoder = nn.ModuleList()

        for index in range(len(dims) - 1):
            enc = SDblock(
                channels_in=dims[index],
                channels_out=dims[index + 1],
                band_configs=self.band_configs,
                conv_config=self.conv_config,
                depths=conv_depths,
            )
            self.encoder.append(enc)

            dec = nn.Sequential(
                FusionLayer(channels=dims[index + 1]),
                SUlayer(
                    channels_in=dims[index + 1],
                    channels_out=dims[index] if index != 0 else dims[index] * len(sources),
                    band_configs=self.band_configs,
                ),
            )
            self.decoder.insert(0, dec)

        self.separation_net = SeparationNetTran(
            channels=dims[-1],
            num_layers=num_dplayer,
            tran_params=self.tran_params,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # B, C, L = x.shape
        B = x.shape[0]
        # In the initial padding, ensure that the number of frames after the STFT (the length of the T dimension) is even,
        # so that the RFFT operation can be used in the separation network.
        padding = self.hop_length - x.shape[-1] % self.hop_length
        if (x.shape[-1] + padding) // self.hop_length % 2 == 0:
            padding += self.hop_length
        x = F.pad(x, (0, padding))

        # STFT
        L = x.shape[-1]
        x = x.reshape(-1, L)
        stft_kwargs = dict(self.stft_config)
        stft_kwargs["window"] = torch.hann_window(self.win_size, device=x.device, dtype=x.dtype)
        x = torch.stft(x, **stft_kwargs, return_complex=True)
        x = torch.view_as_real(x)
        x = x.permute(0, 3, 1, 2).reshape(
            x.shape[0] // self.audio_channels, x.shape[3] * self.audio_channels, x.shape[1], x.shape[2]
        )

        B, _C, Fr, T = x.shape

        save_skip: deque[torch.Tensor] = deque()
        save_lengths: deque[list[int]] = deque()
        save_original_lengths: deque[list[int]] = deque()
        # encoder
        for sd_layer in self.encoder:
            x, skip, lengths, original_lengths = sd_layer(x)
            save_skip.append(skip)
            save_lengths.append(lengths)
            save_original_lengths.append(original_lengths)

        # separation
        x = self.separation_net(x)

        # decoder
        for dec in self.decoder:
            assert isinstance(dec, nn.Sequential)
            fusion_layer = dec[0]
            su_layer = dec[1]
            assert isinstance(fusion_layer, FusionLayer)
            assert isinstance(su_layer, SUlayer)
            x = fusion_layer(x, save_skip.pop())
            x = su_layer(x, save_lengths.pop(), save_original_lengths.pop())

        # output
        n = self.dims[0]
        x = x.view(B, n, -1, Fr, T)
        x = x.reshape(-1, 2, Fr, T).permute(0, 2, 3, 1)
        x = torch.view_as_complex(x.contiguous())
        istft_kwargs = dict(self.stft_config)
        istft_kwargs["window"] = torch.hann_window(self.win_size, device=x.device, dtype=x.real.dtype)
        x = torch.istft(x, **istft_kwargs)
        x = x.reshape(B, len(self.sources), self.audio_channels, -1)

        x = x[:, :, :, :-padding]

        return x
