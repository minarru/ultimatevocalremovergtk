from __future__ import annotations

import math
from collections import deque

import torch
import torch.nn as nn
import torch.nn.functional as F

from .scnet import BandConfigs, ConvConfig, FusionLayer, SDblock, SUlayer
from .separation import SeparationNet


class SCNetMasked(nn.Module):
    """
    MSST "masked" variant of SCNet: the decoder predicts a complex mask over the
    repeated mixture spectrogram (``mixture * mask``) instead of predicting the
    separated spectrogram directly. See:
    https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/models/scnet/scnet_masked.py

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
    - expand (int): Expansion factor in the dual-path RNN, default is 1.
    """

    def __init__(
        self,
        sources: list[str] = ['drums', 'bass', 'other', 'vocals'],  # noqa: B006 — upstream default
        audio_channels: int = 2,
        # Main structure
        dims: list[int] = [4, 32, 64, 128],  # dims = [4, 64, 128, 256] in SCNet-large
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
        # Dual-path RNN
        num_dplayer: int = 6,
        expand: int = 1,
    ) -> None:
        super().__init__()
        self.sources = sources
        self.audio_channels = audio_channels
        self.dims = dims
        band_keys = ['low', 'mid', 'high']
        self.band_configs: BandConfigs = {
            band_keys[i]: {'SR': band_SR[i], 'stride': band_stride[i], 'kernel': band_kernel[i]}
            for i in range(len(band_keys))
        }
        self.hop_length = hop_size
        self.win_size = win_size
        self.conv_config: ConvConfig = {
            'compress': compress,
            'kernel': conv_kernel,
        }

        self.embed_dim = dims[0]
        self.max_f = nfft // 2 + 1
        self.pos_embed_f = nn.Parameter(torch.zeros(1, self.embed_dim, self.max_f, 1))
        nn.init.trunc_normal_(self.pos_embed_f, std=.02)

        self.stft_config = {
            'n_fft': nfft,
            'hop_length': hop_size,
            'win_length': win_size,
            'center': True,
            'normalized': normalized,
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

        self.separation_net = SeparationNet(
            channels=dims[-1],
            expand=expand,
            num_layers=num_dplayer,
        )

        self.mask_layer = nn.Sequential(
            nn.Conv2d(
                4 * len(self.sources),
                64,
                kernel_size=3,
                padding="same",
            ),
            nn.GELU(),
            nn.Conv2d(
                64,
                4 * len(self.sources),
                kernel_size=1,
                padding="same",
            ),
            nn.Tanh(),
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

        B, C, Fr, T = x.shape

        assert C == self.embed_dim, (
            f"Input channel dimension {C} after STFT/reshape doesn't match self.embed_dim {self.embed_dim}"
        )
        mixture = x.repeat(1, len(self.sources), 1, 1)

        if Fr > self.max_f:
            repeats = math.ceil(Fr / self.max_f)
            pos_f = self.pos_embed_f.repeat(1, 1, repeats, 1)[:, :, :Fr, :]
        else:
            pos_f = self.pos_embed_f[:, :, :Fr, :]
        x = x + pos_f

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

        mask = self.mask_layer(x)

        # output
        n = self.dims[0]

        mixture = mixture.view(B, n, -1, Fr, T)
        mixture = mixture.reshape(-1, 2, Fr, T).permute(0, 2, 3, 1)
        mixture_c = torch.view_as_complex(mixture.contiguous())

        mask = mask.view(B, n, -1, Fr, T)
        mask = mask.reshape(-1, 2, Fr, T).permute(0, 2, 3, 1)
        mask_c = torch.view_as_complex(mask.contiguous())

        x = mixture_c * mask_c

        istft_kwargs = dict(self.stft_config)
        istft_kwargs["window"] = torch.hann_window(self.win_size, device=x.device, dtype=x.real.dtype)
        x = torch.istft(x, **istft_kwargs)
        x = x.reshape(B, len(self.sources), self.audio_channels, -1)

        x = x[:, :, :, :-padding]

        return x
