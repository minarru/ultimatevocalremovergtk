"""CPU bounce helpers for ``torch.stft`` / ``torch.istft`` on non-CUDA accelerators.

Apple MPS (and similar backends) historically lack reliable STFT support.
These helpers keep the surrounding network on the accelerator and only move
tensors for the STFT / iSTFT calls themselves.
"""

from __future__ import annotations

import torch


def device_type(device) -> str:
    if isinstance(device, torch.device):
        return device.type
    return torch.device(device).type


def needs_cpu_stft(device) -> bool:
    """Return True when STFT should run on CPU for this device."""
    return device_type(device) not in ("cuda", "cpu")


def torch_stft(input: torch.Tensor, *, window=None, **kwargs) -> torch.Tensor:
    """``torch.stft`` with an automatic CPU bounce.

    Real spectrograms are restored to ``input.device``. Complex results stay on
    CPU when bouncing (MPS complex tensors are unreliable); callers should call
    ``view_as_real`` / band math on CPU, then ``.to(device)`` for the network.
    """
    device = input.device
    if not needs_cpu_stft(device):
        return torch.stft(input, window=window, **kwargs)
    win = None if window is None else window.to("cpu")
    out = torch.stft(input.cpu(), window=win, **kwargs)
    if torch.is_complex(out):
        return out
    return out.to(device)


def torch_istft(input: torch.Tensor, *, window=None, **kwargs) -> torch.Tensor:
    """``torch.istft`` with an automatic CPU bounce.

    When ``input`` is already on CPU (typical after a complex-mask path), the
    waveform is moved back to the caller's intended device via ``kwargs`` only
    if needed — pass a real ``target_device`` through restoring at the call site.
    """
    device = input.device
    if not needs_cpu_stft(device):
        return torch.istft(input, window=window, **kwargs)
    win = None if window is None else window.to("cpu")
    return torch.istft(input.cpu(), window=win, **kwargs)


def to_stft_compute_device(tensor: torch.Tensor) -> torch.Tensor:
    """Move ``tensor`` to CPU when the current device cannot run STFT ops."""
    if needs_cpu_stft(tensor.device):
        return tensor.cpu()
    return tensor
