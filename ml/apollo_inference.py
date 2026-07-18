"""Apollo restore inference (torch; device supplied by caller)."""

from __future__ import annotations

import gc
import hashlib
import json
from typing import Any, Optional

import librosa
import numpy as np
import torch

import ml.apollo_model_data as models


def load_audio(file_path):
    audio, samplerate = librosa.load(file_path, mono=False, sr=44100)
    return torch.from_numpy(audio), samplerate


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


def _apollo_param_fingerprint(extracted_params: Optional[dict], config: Any) -> str:
    payload = {
        "params": extracted_params or {},
        "config": str(config) if config is not None else "",
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def dBgain(audio, volume_gain_dB):
    gain = 10 ** (volume_gain_dB / 20)
    gained_audio = audio * gain
    return gained_audio


def restore_process(
    input_wav,
    ckpt_path,
    overlap=2,
    chunk_size=10,
    set_progress_bar=None,
    device=None,
    extracted_params=None,
    config=None,
):

    if device is None:
        device = "cpu"

    global progress_value
    progress_value = 0

    from engines.model_weight_cache import get_weight_cache, weight_cache_key

    cache = get_weight_cache()
    key = weight_cache_key(
        "apollo",
        str(ckpt_path),
        device,
        _apollo_param_fingerprint(extracted_params, config),
    )
    cached = cache.get(key)
    if cached is not None and cached.module is not None:
        model = cached.module
        model.to(device)
    else:
        model = models.BaseModel.from_pretrain(ckpt_path, **(extracted_params or {})).to(device)
        cache.put(key, module=model)

    def process_chunk(chunk):
        chunk = chunk.unsqueeze(0).to(device)
        with torch.no_grad():
            return model(chunk).squeeze(0).squeeze(0).cpu()

    def progress_bar_ui(length):
        global progress_value
        progress_value += 1

        if length <= 0:
            length = 1

        iter_val = (0.90 / length * progress_value)
        iter_val = 0.99 if iter_val >= 1.0 else iter_val
        set_progress_bar(0.1, iter_val)

    audio_data, samplerate = load_audio(input_wav)

    C = chunk_size * samplerate
    N = overlap

    step = C // N if overlap else C
    step_ui = int(step)

    fade_sec = 3 if chunk_size >= 3 else chunk_size
    fade_size = int(fade_sec * samplerate)
    border = C - step

    if len(audio_data.shape) == 1:
        audio_data = audio_data.unsqueeze(0)

    if audio_data.shape[1] > 2 * border and (border > 0):
        audio_data = torch.nn.functional.pad(audio_data, (border, border), mode='reflect')

    window_middle = _getWindowingArray(C, fade_size)
    window_start = window_middle.clone()
    window_start[:fade_size] = 1
    window_finish = window_middle.clone()
    window_finish[-fade_size:] = 1

    result = torch.zeros((1,) + tuple(audio_data.shape), dtype=torch.float32)
    counter = torch.zeros((1,) + tuple(audio_data.shape), dtype=torch.float32)

    i = 0

    batch_len = max(1, int(audio_data.shape[1] / step_ui))

    while i < audio_data.shape[1]:
        part = audio_data[:, i:i + C]
        length = part.shape[-1]
        if length < C:
            if length > C // 2 + 1:
                part = torch.nn.functional.pad(input=part, pad=(0, C - length), mode='reflect')
            else:
                part = torch.nn.functional.pad(input=part, pad=(0, C - length, 0, 0), mode='constant', value=0)

        out = process_chunk(part)

        if i == 0:
            window = window_start
        elif i + C >= audio_data.shape[1]:
            window = window_finish
        else:
            window = window_middle

        result[..., i:i+length] += out[..., :length] * window[..., :length]
        counter[..., i:i+length] += window[..., :length]

        i += step

        if set_progress_bar:
            progress_bar_ui(batch_len)

    final_output = result / counter
    final_output = final_output.squeeze(0).numpy()
    np.nan_to_num(final_output, copy=False, nan=0.0)

    if audio_data.shape[1] > 2 * border and (border > 0):
        final_output = final_output[..., border:-border]

    # Keep weights in the process LRU; only drop local references.
    del result, counter, audio_data
    gc.collect()

    return final_output
