"""Torch-native STFT helpers for Bandit inference (no torchaudio dependency)."""

from __future__ import annotations

from typing import Dict, Optional

import torch
from torch import nn


class SpectralComponent(nn.Module):
    """STFT / iSTFT pair matching UVR Bandit yaml spectrogram settings."""

    def __init__(
        self,
        n_fft: int = 2048,
        win_length: Optional[int] = 2048,
        hop_length: int = 512,
        window_fn: str = "hann_window",
        wkwargs: Optional[Dict] = None,
        power: Optional[int] = None,
        center: bool = True,
        normalized: bool = True,
        pad_mode: str = "constant",
        onesided: bool = True,
        **kwargs,
    ) -> None:
        super().__init__()
        del kwargs, wkwargs, window_fn, pad_mode, onesided
        if power is not None:
            raise ValueError("Bandit models require complex spectrograms (power=None).")

        self.n_fft = n_fft
        self.win_length = win_length or n_fft
        self.hop_length = hop_length
        self.center = center
        self.normalized = normalized
        self.register_buffer("window", torch.hann_window(self.win_length), persistent=False)

    def _window_for(self, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
        return self.window.to(device=device, dtype=dtype)

    def stft(self, audio: torch.Tensor) -> torch.Tensor:
        """Return complex spectrogram ``(batch, channels, freq, time)``."""
        if audio.ndim != 3:
            raise ValueError(f"Expected audio shape (B, C, L), got {tuple(audio.shape)}")
        batch, channels, _length = audio.shape
        flat = audio.reshape(batch * channels, -1)
        spec = torch.stft(
            flat,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
            win_length=self.win_length,
            window=self._window_for(flat.device, flat.dtype),
            center=self.center,
            normalized=self.normalized,
            return_complex=True,
        )
        freq, time = spec.shape[1], spec.shape[2]
        return spec.reshape(batch, channels, freq, time)

    def istft(self, spec: torch.Tensor, length: int) -> torch.Tensor:
        """Invert complex spectrogram back to ``(batch, channels, length)``."""
        if spec.ndim != 4:
            raise ValueError(f"Expected spectrogram shape (B, C, F, T), got {tuple(spec.shape)}")
        batch, channels, _freq, _time = spec.shape
        flat = spec.reshape(batch * channels, spec.shape[2], spec.shape[3])
        audio = torch.istft(
            flat,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
            win_length=self.win_length,
            window=self._window_for(flat.device, flat.real.dtype),
            center=self.center,
            normalized=self.normalized,
            length=length,
        )
        return audio.reshape(batch, channels, -1)
