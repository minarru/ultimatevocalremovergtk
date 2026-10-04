"""Waveform peaks for the compare dialog: min/max envelopes at a fixed resolution.

Pure numpy over :mod:`core.audio_decode`; no GTK and no GStreamer. Values are raw
sample values clipped to full scale and never normalised, so every track of a
comparison shares one amplitude scale.

While a :class:`PeakSink` is installed, full decodes (:func:`load_audio`) and lossy
exports (:func:`core.audio_io.save_format`) seed it from audio already in hand, so the
dialog need not decode those files again.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol, cast

from .audio_decode import AudioDecodeError, load_audio
from .debug_log import log_event

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


class PeakSink(Protocol):
    """Where decoded or exported audio seeds its peaks; ``ui.playback.PeakCache`` fits."""

    def get(self, path: str) -> Peaks | None: ...
    def put(self, path: str, peaks: Peaks) -> None: ...


# Process-wide, because the run that seeds it works on its own thread. The UI installs
# one for the length of a run; the CLI never does, so it pays nothing.
_peak_sink: PeakSink | None = None


def set_peak_sink(sink: PeakSink | None) -> None:
    global _peak_sink
    _peak_sink = sink


def offer_peaks(path: str, compute: Callable[[], Peaks]) -> None:
    """Seed ``compute()`` under ``path`` when a sink wants it; never raises."""
    sink = _peak_sink
    if sink is None:
        return
    try:
        if sink.get(path) is not None:
            return
        sink.put(path, compute())
    except Exception as exc:
        log_event("playback", "waveform_seed_error", level="warning", path=path, error=str(exc))


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
        # Fold channels column by column: min(axis=1) over a two-wide C-order
        # block is several times slower than the whole WAV read.
        lows = block[:, 0].copy()
        highs = lows.copy()
        for channel in range(1, block.shape[1]):
            np.minimum(lows, block[:, channel], out=lows)
            np.maximum(highs, block[:, channel], out=highs)
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


def peaks_from_array(
    data: NDArray[np.float32],
    rate: int,
    *,
    buckets: int = DEFAULT_BUCKETS,
    cancel: threading.Event | None = None,
) -> Peaks:
    """Peaks of decoded audio shaped like :func:`load_audio` returns it, block by block."""
    by_channel = data.reshape(1, -1) if data.ndim == 1 else data
    frames = by_channel.shape[1]
    if frames == 0:
        raise AudioDecodeError("Cannot decode audio: Empty audio data")
    reducer = _Reducer(frames, buckets)
    by_frame = by_channel.T
    for start in range(0, frames, _BLOCK_FRAMES):
        _check(cancel)
        reducer.feed(by_frame[start : start + _BLOCK_FRAMES])
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
    return peaks_from_array(data, rate, buckets=buckets, cancel=cancel)


__all__ = [
    "DEFAULT_BUCKETS",
    "PeakSink",
    "Peaks",
    "WaveformCancelled",
    "compute_peaks",
    "offer_peaks",
    "peaks_from_array",
    "set_peak_sink",
]
