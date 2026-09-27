"""Lazy, presentation-neutral audio readability probing."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .audio_decode import load_audio, read_audio_metadata


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
        info = read_audio_metadata(path)
        # SoundFile supplied a validated frame count. Other containers need a
        # short decode to establish readability; empty headers do not suffice.
        if not info.frames:
            load_audio(path, duration=3)
        return AudioProbeResult(
            True, info.duration_seconds, info.format, info.channels, info.sample_rate
        )
    except Exception as exc:
        return AudioProbeResult(False, error=f"{type(exc).__name__}: {exc}")


def audio_duration_seconds(path: str) -> float | None:
    """Return metadata duration without decoding PCM, or None if unknown."""
    if not os.path.isfile(path):
        return None
    try:
        return read_audio_metadata(path).duration_seconds
    except Exception:
        return None
