"""Apollo execution: acquisition, decoding, device calls and run-local progress."""

from __future__ import annotations

import gc
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import torch

import ml.apollo_model_data as models
from ml.apollo_inference import restore_audio

from .model_weight_cache import ModelWeightCache, materialize_module, weight_cache_key


def load_audio(file_path: str | Path) -> tuple[torch.Tensor, int]:
    audio, samplerate = librosa.load(file_path, mono=False, sr=44100)
    return torch.from_numpy(audio), int(samplerate)


def _apollo_param_fingerprint(extracted_params: dict[str, Any] | None, config: Any) -> str:
    payload = {
        "params": extracted_params or {},
        "config": str(config) if config is not None else "",
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def acquire_apollo_model(
    ckpt_path: str | Path,
    device: str | torch.device,
    extracted_params: dict[str, Any] | None,
    config: Any,
    *,
    cache: ModelWeightCache,
) -> torch.nn.Module:
    from core.torch_checkpoint import load_torch_checkpoint

    key = weight_cache_key(
        "apollo",
        str(ckpt_path),
        device,
        _apollo_param_fingerprint(extracted_params, config),
    )
    cached = cache.get(key)
    if cached is not None and cached.module is not None:
        model = materialize_module(cached.module, device)
    else:
        conf = load_torch_checkpoint(ckpt_path, map_location="cpu")
        model = models.BaseModel.from_checkpoint(conf, **(extracted_params or {})).to(device)
        cache.put(key, module=model)
        model = materialize_module(model, device)

    return model


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

    from .model_weight_cache import get_weight_cache

    if device is None:
        device = "cpu"
    progress_value = 0
    model = acquire_apollo_model(
        ckpt_path, device, extracted_params, config, cache=get_weight_cache()
    )

    def process_chunk(chunk: torch.Tensor) -> torch.Tensor:
        # Apollo's STFT sizes are often not powers of two. CUDA fp16 autocast
        # then fails inside cuFFT ("only supports dimensions whose sizes are
        # powers of two"). Demucs has the same restriction; keep float32 here
        # regardless of the process.autocast setting.
        chunk = chunk.unsqueeze(0).to(device)
        with torch.inference_mode():
            out = model(chunk).squeeze(0).squeeze(0)
            return out.float().cpu()

    def progress_bar_ui(length: int) -> None:
        nonlocal progress_value
        progress_value += 1

        if length <= 0:
            length = 1

        iter_val = 0.90 / length * progress_value
        iter_val = 0.99 if iter_val >= 1.0 else iter_val
        if set_progress_bar is not None:
            set_progress_bar(0.1, iter_val)

    audio_data, samplerate = load_audio(input_wav)
    final_output = restore_audio(
        audio_data,
        samplerate,
        overlap=overlap,
        chunk_size=chunk_size,
        infer_chunk=process_chunk,
        on_chunk_complete=progress_bar_ui if set_progress_bar else None,
    )
    # Keep cached weights resident; preserve successful-run-only collection.
    del audio_data
    gc.collect()
    return final_output
