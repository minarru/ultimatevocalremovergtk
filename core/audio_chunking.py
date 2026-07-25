"""Whole-file time slicing and crossfade concat for long-audio runs."""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

DEFAULT_SAMPLE_RATE = 44100


def clamp_overlap_seconds(chunk_seconds: float, overlap_seconds: float) -> float:
    """Return a non-negative overlap strictly less than half the chunk length."""
    try:
        chunk = float(chunk_seconds)
    except (TypeError, ValueError):
        chunk = 0.0
    try:
        overlap = float(overlap_seconds)
    except (TypeError, ValueError):
        overlap = 0.0
    if chunk <= 0:
        return 0.0
    return max(0.0, min(overlap, chunk * 0.5 - 1e-6))


def slice_mix(
    mix: np.ndarray,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    chunk_seconds: float,
    overlap_seconds: float = 0.0,
) -> List[Tuple[int, int, np.ndarray]]:
    """Split a channel-first mix into overlapping wall-clock chunks.

    Returns a list of ``(start_sample, end_sample, chunk_array)``. When
    ``chunk_seconds`` is ``<= 0`` or the mix fits in one chunk, returns a single
    entry covering the full mix (no copy when possible).
    """
    audio = np.asarray(mix)
    if audio.ndim == 1:
        audio = np.asfortranarray([audio, audio])
    if audio.shape[0] > audio.shape[1] and audio.shape[0] != 2:
        # Time-major fallback → channel-first.
        audio = audio.T
    total = int(audio.shape[1])
    if total <= 0:
        return [(0, 0, audio)]

    try:
        chunk_s = float(chunk_seconds)
    except (TypeError, ValueError):
        chunk_s = 0.0
    if chunk_s <= 0:
        return [(0, total, audio)]

    chunk_samples = max(1, int(round(chunk_s * sample_rate)))
    if total <= chunk_samples:
        return [(0, total, audio)]

    overlap_s = clamp_overlap_seconds(chunk_s, overlap_seconds)
    overlap_samples = max(0, int(round(overlap_s * sample_rate)))
    if overlap_samples >= chunk_samples:
        overlap_samples = max(0, chunk_samples // 2)
    step = max(1, chunk_samples - overlap_samples)

    chunks: List[Tuple[int, int, np.ndarray]] = []
    start = 0
    while start < total:
        end = min(total, start + chunk_samples)
        if end - start < chunk_samples and chunks:
            # Final short remainder: pull a full window ending at ``total``.
            start = max(0, total - chunk_samples)
            end = total
            chunks.append((start, end, np.array(audio[:, start:end], copy=True)))
            break
        chunks.append((start, end, np.array(audio[:, start:end], copy=True)))
        if end >= total:
            break
        start += step
    return chunks


def concat_stems(
    parts: Sequence[np.ndarray],
    *,
    overlap_samples: int = 0,
) -> np.ndarray:
    """Concatenate channel-first stem chunks with a linear crossfade on overlap."""
    if not parts:
        raise ValueError("concat_stems requires at least one part")
    arrays = [np.asarray(part) for part in parts]
    if len(arrays) == 1:
        return arrays[0]

    overlap = max(0, int(overlap_samples))
    result = arrays[0]
    for nxt in arrays[1:]:
        result = _crossfade_join(result, nxt, overlap)
    return result


def _crossfade_join(left: np.ndarray, right: np.ndarray, overlap: int) -> np.ndarray:
    if overlap <= 0 or left.shape[1] == 0 or right.shape[1] == 0:
        return np.concatenate([left, right], axis=1)

    ov = min(overlap, left.shape[1], right.shape[1])
    if ov <= 0:
        return np.concatenate([left, right], axis=1)

    fade_out = np.linspace(1.0, 0.0, ov, dtype=np.float64)
    fade_in = 1.0 - fade_out
    mixed = left[:, -ov:] * fade_out + right[:, :ov] * fade_in
    return np.concatenate([left[:, :-ov], mixed, right[:, ov:]], axis=1)


def overlap_samples_for(
    *,
    sample_rate: int,
    chunk_seconds: float,
    overlap_seconds: float,
) -> int:
    """Sample count used for concat crossfade given the active chunk settings."""
    overlap_s = clamp_overlap_seconds(chunk_seconds, overlap_seconds)
    return max(0, int(round(overlap_s * sample_rate)))
