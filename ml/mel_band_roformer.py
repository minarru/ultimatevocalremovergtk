from __future__ import annotations

from functools import partial
from typing import Any, Callable, Tuple, TypeVar, cast

import torch
from torch import nn, einsum, Tensor
from torch.nn import Module, ModuleList, Sequential
import torch.nn.functional as F

from .attend import Attend

from beartype.typing import Tuple as BeartypeTuple, Optional as BeartypeOptional, Callable as BeartypeCallable
from beartype import beartype

from rotary_embedding_torch import RotaryEmbedding

from einops import rearrange, pack, unpack, reduce, repeat

from librosa import filters

from ml.stft_device import needs_cpu_stft, torch_istft, torch_stft

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


def pad_at_dim(t: Tensor, pad: tuple[int, ...], dim: int = -1, value: float = 0.) -> Tensor:
    dims_from_right = (- dim - 1) if dim < 0 else (t.ndim - dim - 1)
    zeros = ((0, 0) * dims_from_right)
    return F.pad(t, (*zeros, *pad), value=value)

class RMSNorm(Module):
    def __init__(self, dim: int) -> None:
        super().__init__()
        self.scale = dim ** 0.5
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x: Tensor) -> Tensor:
        x = x.to(self.gamma.device)
        return F.normalize(x, dim=-1) * self.scale * self.gamma

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
            flash: bool = True
    ) -> None:
        super().__init__()
        self.heads = heads
        self.scale = dim_head ** -0.5
        dim_inner = heads * dim_head

        self.rotary_embed = rotary_embed

        self.attend = Attend(flash=flash, dropout=dropout)

        self.norm = RMSNorm(dim)
        self.to_qkv = nn.Linear(dim, dim_inner * 3, bias=False)

        self.to_gates = nn.Linear(dim, heads)

        self.to_out = nn.Sequential(
            nn.Linear(dim_inner, dim, bias=False),
            nn.Dropout(dropout)
        )

    def forward(self, x: Tensor) -> Tensor:
        x = self.norm(x)

        q, k, v = rearrange(self.to_qkv(x), 'b n (qkv h d) -> qkv b h n d', qkv=3, h=self.heads)

        if self.rotary_embed is not None:
            q = self.rotary_embed.rotate_queries_or_keys(q)
            k = self.rotary_embed.rotate_queries_or_keys(k)

        out = self.attend(q, k, v)

        gates = self.to_gates(x)
        out = out * rearrange(gates, 'b n h -> b h n 1').sigmoid()

        out = rearrange(out, 'b h n d -> b n (h d)')
        return self.to_out(out)


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
            flash_attn: bool = True
    ) -> None:
        super().__init__()
        self.layers = ModuleList([])

        for _ in range(depth):
            self.layers.append(ModuleList([
                Attention(dim=dim, dim_head=dim_head, heads=heads, dropout=attn_dropout, rotary_embed=rotary_embed,
                          flash=flash_attn),
                FeedForward(dim=dim, mult=ff_mult, dropout=ff_dropout)
            ]))

        self.norm = RMSNorm(dim) if norm_output else nn.Identity()

    def forward(self, x: Tensor) -> Tensor:

        for layer in self.layers:
            layer_pair = cast(ModuleList, layer)
            attn, ff = cast(tuple[Attention, FeedForward], (layer_pair[0], layer_pair[1]))
            x = attn(x) + x
            x = ff(x) + x

        return self.norm(x)

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
    dims = (dim_in, *((resolved_dim_hidden,) * depth), dim_out)

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
            mlp_expansion_factor: int = 4
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

    def forward(self, x: Tensor) -> Tensor:
        bands = x.unbind(dim=-2)

        outs = []

        for band_features, mlp in zip(bands, cast(list[Sequential], list(self.to_freqs))):
            freq_out = mlp(band_features)
            outs.append(freq_out)

        return torch.cat(outs, dim=-1)

class MelBandRoformer(Module):

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
            num_bands: int = 60,
            dim_head: int = 64,
            heads: int = 8,
            attn_dropout: float = 0.1,
            ff_dropout: float = 0.1,
            flash_attn: bool = True,
            dim_freqs_in: int = 1025,
            sample_rate: int = 44100,
            stft_n_fft: int = 2048,
            stft_hop_length: int = 512,
            stft_win_length: int = 2048,
            stft_normalized: bool = False,
            stft_window_fn: BeartypeOptional[BeartypeCallable[..., Tensor]] = None,
            mask_estimator_depth: int = 1,
            multi_stft_resolution_loss_weight: float = 1.,
            multi_stft_resolutions_window_sizes: BeartypeTuple[int, ...] = (4096, 2048, 1024, 512, 256),
            multi_stft_hop_size: int = 147,
            multi_stft_normalized: bool = False,
            multi_stft_window_fn: BeartypeCallable[..., Tensor] = torch.hann_window,
            match_input_audio_length: bool = False,
    ) -> None:
        super().__init__()

        self.stereo = stereo
        self.audio_channels = 2 if stereo else 1
        self.num_stems = num_stems

        self.layers = ModuleList([])

        transformer_kwargs: dict[str, Any] = dict(
            dim=dim,
            heads=heads,
            dim_head=dim_head,
            attn_dropout=attn_dropout,
            ff_dropout=ff_dropout,
            flash_attn=flash_attn
        )

        time_rotary_embed = RotaryEmbedding(dim=dim_head)
        freq_rotary_embed = RotaryEmbedding(dim=dim_head)

        for _ in range(depth):
            self.layers.append(nn.ModuleList([
                Transformer(depth=time_transformer_depth, rotary_embed=time_rotary_embed, **transformer_kwargs),
                Transformer(depth=freq_transformer_depth, rotary_embed=freq_rotary_embed, **transformer_kwargs)
            ]))

        _stft_window_fn = cast(Callable[..., Tensor], default(stft_window_fn, torch.hann_window))
        self.stft_window_fn: Callable[..., Tensor] = partial(_stft_window_fn, stft_win_length)

        self.stft_kwargs: dict[str, Any] = dict(
            n_fft=stft_n_fft,
            hop_length=stft_hop_length,
            win_length=stft_win_length,
            normalized=stft_normalized
        )

        freqs = torch.stft(torch.randn(1, 4096), **self.stft_kwargs, return_complex=True).shape[1]

        mel_filter_bank_numpy = filters.mel(sr=sample_rate, n_fft=stft_n_fft, n_mels=num_bands)

        mel_filter_bank = torch.from_numpy(mel_filter_bank_numpy)

        mel_filter_bank[0][0] = 1.

        mel_filter_bank[-1, -1] = 1.

        freqs_per_band = mel_filter_bank > 0
        assert freqs_per_band.any(dim=0).all(), 'all frequencies need to be covered by all bands for now'

        repeated_freq_indices = repeat(torch.arange(freqs), 'f -> b f', b=num_bands)
        freq_indices = repeated_freq_indices[freqs_per_band]

        if stereo:
            freq_indices = repeat(freq_indices, 'f -> f s', s=2)
            freq_indices = freq_indices * 2 + torch.arange(2)
            freq_indices = rearrange(freq_indices, 'f s -> (f s)')

        self.register_buffer('freq_indices', freq_indices, persistent=False)
        self.register_buffer('freqs_per_band', freqs_per_band, persistent=False)

        num_freqs_per_band = reduce(freqs_per_band, 'b f -> b', 'sum')
        num_bands_per_freq = reduce(freqs_per_band, 'b f -> f', 'sum')

        self.register_buffer('num_freqs_per_band', num_freqs_per_band, persistent=False)
        self.register_buffer('num_bands_per_freq', num_bands_per_freq, persistent=False)

        freqs_per_bands_with_complex = tuple(2 * f * self.audio_channels for f in num_freqs_per_band.tolist())

        self.band_split = BandSplit(
            dim=dim,
            dim_inputs=freqs_per_bands_with_complex
        )

        self.mask_estimators = nn.ModuleList([])

        for _ in range(num_stems):
            mask_estimator = MaskEstimator(
                dim=dim,
                dim_inputs=freqs_per_bands_with_complex,
                depth=mask_estimator_depth
            )

            self.mask_estimators.append(mask_estimator)

        self.multi_stft_resolution_loss_weight = multi_stft_resolution_loss_weight
        self.multi_stft_resolutions_window_sizes = multi_stft_resolutions_window_sizes
        self.multi_stft_n_fft = stft_n_fft
        self.multi_stft_window_fn = multi_stft_window_fn

        self.multi_stft_kwargs: dict[str, Any] = dict(
            hop_length=multi_stft_hop_size,
            normalized=multi_stft_normalized
        )

        self.match_input_audio_length = match_input_audio_length

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

        batch, channels, raw_audio_length = raw_audio.shape

        istft_length = raw_audio_length if self.match_input_audio_length else None

        assert (not self.stereo and channels == 1) or (
                    self.stereo and channels == 2), 'stereo needs to be set to True if passing in audio signal that is stereo (channel dimension of 2). also need to be False if mono (channel dimension of 1)'

        raw_audio, batch_audio_channel_packed_shape = pack_one(raw_audio, '* t')

        stft_window = self.stft_window_fn(device=device)

        stft_repr = torch_stft(raw_audio, **self.stft_kwargs, window=stft_window, return_complex=True)
        stft_repr = torch.view_as_real(stft_repr)
        if bounce:
            stft_repr = stft_repr.to(device)

        stft_repr = unpack_one(stft_repr, batch_audio_channel_packed_shape, '* f t c')
        stft_repr = rearrange(stft_repr,
                              'b s f t c -> b (f s) t c')  # merge stereo / mono into the frequency, with frequency leading dimension, for band splitting

        batch_arange = torch.arange(batch, device=device)[..., None]
        freq_indices = cast(Tensor, self.freq_indices).to(device)

        x = stft_repr[batch_arange, freq_indices]

        x = rearrange(x, 'b f t c -> b t (f c)')

        x = self.band_split(x)

        for layer in self.layers:
            layer_pair = cast(ModuleList, layer)
            time_transformer, freq_transformer = cast(
                tuple[Transformer, Transformer], (layer_pair[0], layer_pair[1])
            )
            x = rearrange(x, 'b t f d -> b f t d')
            x, ps = pack([x], '* t d')

            x = time_transformer(x)

            x, = unpack(x, ps, '* t d')
            x = rearrange(x, 'b f t d -> b t f d')
            x, ps = pack([x], '* f d')

            x = freq_transformer(x)

            x, = unpack(x, ps, '* f d')

        num_stems = len(self.mask_estimators)

        masks = torch.stack([fn(x) for fn in cast(list[MaskEstimator], list(self.mask_estimators))], dim=1)
        masks = rearrange(masks, 'b n t (f c) -> b n f t c', c=2)

        # Complex scatter / multiply / iSTFT finish on CPU when needed.
        if bounce:
            masks = masks.cpu()
            stft_repr = stft_repr.cpu()
            stft_window = stft_window.cpu()
            freq_indices_scatter = cast(Tensor, self.freq_indices).cpu()
            num_bands_per_freq = cast(Tensor, self.num_bands_per_freq).cpu()
            denom = repeat(num_bands_per_freq, 'f -> (f r) 1', r=channels)
        else:
            freq_indices_scatter = cast(Tensor, self.freq_indices)
            num_bands_per_freq = cast(Tensor, self.num_bands_per_freq)
            denom = repeat(num_bands_per_freq, 'f -> (f r) 1', r=channels)

        stft_repr = rearrange(stft_repr, 'b f t c -> b 1 f t c')

        stft_repr = torch.view_as_complex(stft_repr)
        masks = torch.view_as_complex(masks)

        masks = masks.type(stft_repr.dtype)

        scatter_indices = repeat(
            freq_indices_scatter, 'f -> b n f t', b=batch, n=num_stems, t=stft_repr.shape[-1]
        )
        stft_repr_expanded_stems = repeat(stft_repr, 'b 1 ... -> b n ...', n=num_stems)
        masks_summed = torch.zeros_like(stft_repr_expanded_stems).scatter_add_(2, scatter_indices, masks)

        masks_averaged = masks_summed / denom.clamp(min=1e-8)

        stft_repr = stft_repr * masks_averaged

        stft_repr = rearrange(stft_repr, 'b n (f s) t -> (b n s) f t', s=self.audio_channels)

        recon_audio = torch_istft(
            stft_repr,
            **self.stft_kwargs,
            window=stft_window,
            return_complex=False,
            length=istft_length,
        )

        recon_audio = rearrange(recon_audio, '(b n s) t -> b n s t', b=batch, s=self.audio_channels, n=num_stems)

        if num_stems == 1:
            recon_audio = rearrange(recon_audio, 'b 1 s t -> b s t')

        if bounce:
            recon_audio = recon_audio.to(original_device)

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
