"""Waveform peaks for the compare dialog: min/max envelopes at a fixed resolution.

Pure numpy over :mod:`core.audio_decode`; no GTK and no GStreamer. Values are raw
sample values clipped to full scale and never normalised, so every track of a
comparison shares one amplitude scale.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .audio_decode import AudioDecodeError, load_audio

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

DEFAULT_BUCKETS = 2048
_BLOCK_FRAMES = 65536


class WaveformCancelled(Exception):
    """The caller's cancel event was set while peaks were being computed."""


@dataclass(frozen=True, eq=False)
class Peaks:
    duration: float
    mins: NDArray[np.float32]
    maxs: NDArray[np.float32]


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise WaveformCancelled


class _Reducer:
    """Folds ``(frames, channels)`` blocks into ``buckets`` equal shares of ``frames``."""

    def __init__(self, frames: int, buckets: int) -> None:
        import numpy as np

        self.frames = frames
        self.buckets = max(1, min(buckets, frames))
        self.mins = np.full(self.buckets, np.inf, dtype=np.float32)
        self.maxs = np.full(self.buckets, -np.inf, dtype=np.float32)
        self.read = 0

    def feed(self, block: NDArray[np.float32]) -> None:
        import numpy as np

        count = block.shape[0]
        if count == 0:
            return
        lows = block.min(axis=1)
        highs = block.max(axis=1)
        index = (np.arange(self.read, self.read + count, dtype=np.int64) * self.buckets) // (
            self.frames
        )
        # A decoder that yields more frames than it declared folds them into the last bucket.
        np.minimum(index, self.buckets - 1, out=index)
        self.read += count
        starts = np.concatenate(([0], np.flatnonzero(np.diff(index)) + 1))
        ids = index[starts]
        # A bucket can straddle two blocks: merge with what the earlier block left.
        self.mins[ids] = np.minimum(self.mins[ids], np.minimum.reduceat(lows, starts))
        self.maxs[ids] = np.maximum(self.maxs[ids], np.maximum.reduceat(highs, starts))

    def result(self, rate: int) -> Peaks:
        import numpy as np

        # Buckets never reached (the file was shorter than declared) stay silent.
        mins = np.where(np.isfinite(self.mins), self.mins, 0.0)
        maxs = np.where(np.isfinite(self.maxs), self.maxs, 0.0)
        return Peaks(
            self.frames / rate,
            np.clip(mins, -1.0, 1.0).astype(np.float32),
            np.clip(maxs, -1.0, 1.0).astype(np.float32),
        )


def _stream_peaks(path: str, buckets: int, cancel: threading.Event | None) -> Peaks | None:
    """Block-wise SoundFile read; ``None`` when SoundFile cannot stream this file."""
    try:
        import soundfile as sf

        audio = sf.SoundFile(path)
    except Exception:
        return None
    with audio:
        frames = int(audio.frames)
        rate = int(audio.samplerate)
        if frames <= 0 or rate <= 0:
            return None
        reducer = _Reducer(frames, buckets)
        try:
            for block in audio.blocks(blocksize=_BLOCK_FRAMES, dtype="float32", always_2d=True):
                _check(cancel)
                # dtype="float32" is honoured; the stubs type blocks as any sample format.
                reducer.feed(cast("NDArray[np.float32]", block))
        except WaveformCancelled:
            raise
        except Exception:
            # A mid-file decode error: let the FFmpeg path try the whole file.
            return None
    if reducer.read == 0:
        return None
    return reducer.result(rate)


def compute_peaks(
    path: str, *, buckets: int = DEFAULT_BUCKETS, cancel: threading.Event | None = None
) -> Peaks:
    """Min/max envelope of ``path`` in at most ``buckets`` equal time slices."""
    if buckets <= 0:
        raise ValueError("buckets must be positive")
    _check(cancel)
    streamed = _stream_peaks(path, buckets, cancel)
    if streamed is not None:
        return streamed
    _check(cancel)
    data, rate = load_audio(path)
    _check(cancel)
    by_channel = data.reshape(1, -1) if data.ndim == 1 else data
    if by_channel.shape[1] == 0:
        raise AudioDecodeError("Cannot decode audio: Empty audio data")
    reducer = _Reducer(by_channel.shape[1], buckets)
    reducer.feed(by_channel.T)
    return reducer.result(rate)


__all__ = ["DEFAULT_BUCKETS", "Peaks", "WaveformCancelled", "compute_peaks"]
