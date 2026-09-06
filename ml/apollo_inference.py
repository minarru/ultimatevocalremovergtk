"""Apollo tensor windowing and overlap-add; execution is owned by engines."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import torch


def _getWindowingArray(window_size: int, fade_size: int) -> torch.Tensor:
    """Build a chunk window with real fade-in / fade-out ramps."""
    fade_size = max(0, min(int(fade_size), int(window_size) // 2))
    window = torch.ones(window_size, dtype=torch.float32)
    if fade_size <= 0:
        return window
    fadein = torch.linspace(0, 1, fade_size, dtype=torch.float32)
    fadeout = torch.linspace(1, 0, fade_size, dtype=torch.float32)
    window[:fade_size] *= fadein
    window[-fade_size:] *= fadeout
    return window


def dBgain(audio: torch.Tensor, volume_gain_dB: float) -> torch.Tensor:
    gain = 10 ** (volume_gain_dB / 20)
    gained_audio = audio * gain
    return gained_audio


def restore_audio(
    audio_data: torch.Tensor,
    samplerate: int,
    *,
    overlap: int,
    chunk_size: int,
    infer_chunk: Callable[[torch.Tensor], torch.Tensor],
    on_chunk_complete: Callable[[int], None] | None = None,
) -> np.ndarray:
    """Restore CPU samples using the original Apollo chunk/overlap math."""
    C = int(chunk_size * samplerate)
    N = overlap

    step = C // N if overlap else C
    step_ui = int(step)

    fade_sec = 3 if chunk_size >= 3 else chunk_size
    # Clamp once so start/finish overrides cannot wipe the whole window.
    fade_size = max(0, min(int(fade_sec * samplerate), C // 2))
    border = int(C - step)

    if len(audio_data.shape) == 1:
        audio_data = audio_data.unsqueeze(0)

    if audio_data.shape[1] > 2 * border and (border > 0):
        audio_data = torch.nn.functional.pad(audio_data, (border, border), mode='reflect')

    window_middle = _getWindowingArray(C, fade_size)
    window_start = window_middle.clone()
    window_finish = window_middle.clone()
    if fade_size > 0:
        window_start[:fade_size] = 1
        window_finish[-fade_size:] = 1

    result = torch.zeros((1,) + tuple(audio_data.shape), dtype=torch.float32)
    counter = torch.zeros((1,) + tuple(audio_data.shape), dtype=torch.float32)

    i = 0

    batch_len = max(1, int(audio_data.shape[1] / step_ui))

    while i < audio_data.shape[1]:
        part = audio_data[:, i : i + C]
        length = part.shape[-1]
        if length < C:
            if length > C // 2 + 1:
                part = torch.nn.functional.pad(input=part, pad=(0, C - length), mode='reflect')
            else:
                part = torch.nn.functional.pad(
                    input=part, pad=(0, C - length, 0, 0), mode='constant', value=0
                )

        out = infer_chunk(part)

        if i == 0:
            window = window_start
        elif i + C >= audio_data.shape[1]:
            window = window_finish
        else:
            window = window_middle

        result[..., i : i + length] += out[..., :length] * window[..., :length]
        counter[..., i : i + length] += window[..., :length]

        i += step

        if on_chunk_complete:
            on_chunk_complete(batch_len)

    final_output = result / counter
    final_output = final_output.squeeze(0).numpy()
    np.nan_to_num(final_output, copy=False, nan=0.0)

    if audio_data.shape[1] > 2 * border and (border > 0):
        final_output = final_output[..., border:-border]

    return final_output


def restore_process(
    input_wav: str | Path,
    ckpt_path: str | Path,
    overlap: int = 2,
    chunk_size: int = 10,
    set_progress_bar: Callable[[float, float], None] | None = None,
    device: str | torch.device | None = None,
    extracted_params: dict[str, Any] | None = None,
    config: Any = None,
    settings: Any = None,
) -> np.ndarray:

    from engines.apollo import restore_process as restore

    return restore(
        input_wav,
        ckpt_path,
        overlap,
        chunk_size,
        set_progress_bar,
        device,
        extracted_params,
        config,
        settings,
    )


def load_audio(file_path: str | Path) -> tuple[torch.Tensor, int]:
    from engines.apollo import load_audio as load

    return load(file_path)


def _apollo_param_fingerprint(extracted_params: dict[str, Any] | None, config: Any) -> str:
    from engines.apollo import _apollo_param_fingerprint as fingerprint

    return fingerprint(extracted_params, config)
