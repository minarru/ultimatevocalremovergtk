"""Whole-file time slicing and crossfade concat for long-audio runs."""

from __future__ import annotations

from typing import List, Sequence, Tuple, Union

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


def chunk_bounds_for_samples(
    total_samples: int,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    chunk_seconds: float,
    overlap_seconds: float = 0.0,
) -> List[Tuple[int, int]]:
    """Return ``(start, end)`` sample windows matching :func:`slice_mix`.

    When ``chunk_seconds`` is ``<= 0`` or the mix fits in one chunk, returns a
    single window covering ``[0, total_samples]``.
    """
    total = int(total_samples)
    if total <= 0:
        return [(0, 0)]

    try:
        chunk_s = float(chunk_seconds)
    except (TypeError, ValueError):
        chunk_s = 0.0
    if chunk_s <= 0:
        return [(0, total)]

    chunk_samples = max(1, int(round(chunk_s * sample_rate)))
    if total <= chunk_samples:
        return [(0, total)]

    overlap_s = clamp_overlap_seconds(chunk_s, overlap_seconds)
    overlap_samples = max(0, int(round(overlap_s * sample_rate)))
    if overlap_samples >= chunk_samples:
        overlap_samples = max(0, chunk_samples // 2)
    step = max(1, chunk_samples - overlap_samples)

    bounds: List[Tuple[int, int]] = []
    start = 0
    while start < total:
        end = min(total, start + chunk_samples)
        if end - start < chunk_samples and bounds:
            # Final short remainder: pull a full window ending at ``total``.
            start = max(0, total - chunk_samples)
            end = total
            bounds.append((start, end))
            break
        bounds.append((start, end))
        if end >= total:
            break
        start += step
    return bounds


def chunk_count_for_samples(
    total_samples: int,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    chunk_seconds: float,
    overlap_seconds: float = 0.0,
) -> int:
    """Number of windows :func:`slice_mix` would emit for ``total_samples``."""
    return len(
        chunk_bounds_for_samples(
            total_samples,
            sample_rate=sample_rate,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
        )
    )


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
    bounds = chunk_bounds_for_samples(
        total,
        sample_rate=sample_rate,
        chunk_seconds=chunk_seconds,
        overlap_seconds=overlap_seconds,
    )
    if len(bounds) == 1:
        start, end = bounds[0]
        return [(start, end, audio)]
    return [
        (start, end, np.array(audio[:, start:end], copy=True))
        for start, end in bounds
    ]


def concat_stems(
    parts: Sequence[np.ndarray],
    *,
    overlap_samples: Union[int, Sequence[int]] = 0,
) -> np.ndarray:
    """Concatenate channel-first stem chunks with a linear crossfade on overlap.

    ``overlap_samples`` is either a single count applied to every join, or a
    sequence with one entry per join (``len(parts) - 1``). A sequence is
    required when chunk boundaries are unevenly spaced — e.g. ``slice_mix``
    pulls the final chunk back to end exactly at the mix length, so the last
    join's actual overlap differs from the configured overlap used elsewhere.
    Use :func:`overlaps_for_chunks` to derive it from ``slice_mix`` output.
    """
    if not parts:
        raise ValueError("concat_stems requires at least one part")
    arrays = [np.asarray(part) for part in parts]
    if len(arrays) == 1:
        return arrays[0]

    if isinstance(overlap_samples, (int, np.integer)):
        overlaps = [max(0, int(overlap_samples))] * (len(arrays) - 1)
    else:
        overlaps = [max(0, int(v)) for v in overlap_samples]
        if len(overlaps) != len(arrays) - 1:
            raise ValueError("overlap_samples sequence must have len(parts) - 1 entries")

    result = arrays[0]
    for nxt, ov in zip(arrays[1:], overlaps):
        result = _crossfade_join(result, nxt, ov)
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


def overlaps_for_chunks(chunks: Sequence[Tuple[int, int, np.ndarray]]) -> List[int]:
    """Actual per-join sample overlap between consecutive ``slice_mix`` chunks.

    Regular joins overlap by the configured ``overlap_seconds``, but the
    final join can differ because ``slice_mix`` pulls the last chunk's start
    back so it ends exactly at the mix length. Deriving overlap directly from
    each chunk's ``(start, end)`` keeps every join correct regardless.
    """
    return [
        max(0, chunks[i][1] - chunks[i + 1][0]) for i in range(len(chunks) - 1)
    ]


def overlap_samples_for(
    *,
    sample_rate: int,
    chunk_seconds: float,
    overlap_seconds: float,
) -> int:
    """Sample count used for concat crossfade given the active chunk settings."""
    overlap_s = clamp_overlap_seconds(chunk_seconds, overlap_seconds)
    return max(0, int(round(overlap_s * sample_rate)))
