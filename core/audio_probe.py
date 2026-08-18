"""Lazy, presentation-neutral audio readability probing."""

from __future__ import annotations

import contextlib
import os
import wave
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioProbeResult:
    readable: bool
    duration_seconds: float | None = None
    format: str | None = None
    channels: int | None = None
    sample_rate: int | None = None
    error: str | None = None


def probe_audio(path: str) -> AudioProbeResult:
    if not os.path.isfile(path):
        return AudioProbeResult(False, error="file_not_found")
    try:
        import soundfile as sf

        info = sf.info(path)
        duration = info.frames / info.samplerate if info.samplerate else 0.0
        return AudioProbeResult(
            True, duration, str(info.format), int(info.channels), int(info.samplerate)
        )
    except Exception:
        pass
    try:
        with contextlib.closing(wave.open(path, "r")) as handle:
            rate = handle.getframerate()
            duration = handle.getnframes() / float(rate) if rate else 0.0
            return AudioProbeResult(
                True, duration, "WAV", handle.getnchannels(), rate
            )
    except Exception:
        pass
    try:
        import librosa

        librosa.load(path, duration=3, mono=False, sr=44100)
        return AudioProbeResult(True)
    except Exception as exc:
        return AudioProbeResult(False, error=f"{type(exc).__name__}: {exc}")


def audio_duration_seconds(path: str) -> float | None:
    """Return wall-clock duration from metadata, or ``None`` if unknown.

    Does not decode PCM. Falls back through libsndfile, stdlib ``wave``, then
    ``librosa.get_duration(path=)``. A missing or unreadable path is ``None``.
    """
    if not os.path.isfile(path):
        return None
    try:
        import soundfile as sf

        info = sf.info(path)
        if info.samplerate:
            return float(info.frames) / float(info.samplerate)
    except Exception:
        pass
    try:
        with contextlib.closing(wave.open(path, "r")) as handle:
            rate = handle.getframerate()
            if rate:
                return handle.getnframes() / float(rate)
    except Exception:
        pass
    try:
        import librosa

        return float(librosa.get_duration(path=path))
    except Exception:
        return None

