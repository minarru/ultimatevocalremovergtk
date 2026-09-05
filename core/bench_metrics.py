"""Stem pairing and null (difference) metrics for A/B benches."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

from .audio_formats import AUDIO_EXTENSIONS


@dataclass
class StemDiff:
    """Difference stats for one paired stem basename."""

    name: str
    peak_abs_diff: float
    rms_diff: float
    samples: int
    channels: int


@dataclass
class StemCompareReport:
    """Aggregate report across paired stem files."""

    pairs: list[StemDiff]
    only_a: list[str]
    only_b: list[str]

    @property
    def max_rms_diff(self) -> float:
        if not self.pairs:
            return 0.0
        return max(p.rms_diff for p in self.pairs)

    @property
    def max_peak_abs_diff(self) -> float:
        if not self.pairs:
            return 0.0
        return max(p.peak_abs_diff for p in self.pairs)

    def to_dict(self) -> dict:
        return {
            "pairs": [asdict(p) for p in self.pairs],
            "only_a": list(self.only_a),
            "only_b": list(self.only_b),
            "max_rms_diff": self.max_rms_diff,
            "max_peak_abs_diff": self.max_peak_abs_diff,
        }


def list_stem_basenames(directory: str) -> set[str]:
    """Return audio stem basenames (files only) under ``directory`` (non-recursive)."""
    if not os.path.isdir(directory):
        return set()
    return {
        name
        for name in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, name))
        and name.lower().endswith(AUDIO_EXTENSIONS)
    }


def list_wav_basenames(directory: str) -> set[str]:
    """Deprecated alias of :func:`list_stem_basenames` (kept for older tests)."""
    return list_stem_basenames(directory)


def array_diff_stats(a: np.ndarray, b: np.ndarray) -> tuple[float, float, int, int]:
    """Return ``(peak_abs_diff, rms_diff, samples, channels)`` for two arrays.

    Arrays are truncated to the shared min length on axis 0 (samples-first or
    channel-first both work after normalizing to ``(samples, channels)``).
    """
    aa = np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64)
    if aa.ndim == 1:
        aa = aa[:, None]
    if bb.ndim == 1:
        bb = bb[:, None]
    # soundfile returns (samples, channels); tolerate (channels, samples).
    if aa.shape[0] < aa.shape[-1] and aa.shape[0] <= 8 and aa.shape[-1] > 8:
        aa = aa.T
    if bb.shape[0] < bb.shape[-1] and bb.shape[0] <= 8 and bb.shape[-1] > 8:
        bb = bb.T
    n = min(aa.shape[0], bb.shape[0])
    ch = min(aa.shape[1], bb.shape[1])
    if n <= 0 or ch <= 0:
        return 0.0, 0.0, 0, 0
    delta = aa[:n, :ch] - bb[:n, :ch]
    peak = float(np.max(np.abs(delta))) if delta.size else 0.0
    rms = float(np.sqrt(np.mean(delta * delta))) if delta.size else 0.0
    return peak, rms, int(n), int(ch)


def compare_stem_dirs(dir_a: str, dir_b: str) -> StemCompareReport:
    """Pair stem audio files by basename in two directories and compute null metrics."""
    import soundfile as sf

    names_a = list_stem_basenames(dir_a)
    names_b = list_stem_basenames(dir_b)
    shared = sorted(names_a & names_b)
    pairs: list[StemDiff] = []
    for name in shared:
        path_a = os.path.join(dir_a, name)
        path_b = os.path.join(dir_b, name)
        audio_a, _sr_a = sf.read(path_a, always_2d=True)
        audio_b, _sr_b = sf.read(path_b, always_2d=True)
        peak, rms, samples, channels = array_diff_stats(audio_a, audio_b)
        pairs.append(
            StemDiff(
                name=name,
                peak_abs_diff=peak,
                rms_diff=rms,
                samples=samples,
                channels=channels,
            )
        )
    return StemCompareReport(
        pairs=pairs,
        only_a=sorted(names_a - names_b),
        only_b=sorted(names_b - names_a),
    )


def sanitize_env_label(env_assignments: Iterable[str]) -> str:
    """Turn ``KEY=val`` assignments into a filesystem-safe short label."""
    parts = []
    for item in env_assignments:
        text = str(item).strip().replace("=", "_").replace("/", "_").replace(" ", "")
        if text:
            parts.append(text)
    return "_".join(parts) or "env"


def parse_env_assignment(text: str) -> tuple[str, str]:
    """Parse ``KEY=value`` (value may be empty)."""
    if "=" not in text:
        raise ValueError(f"expected KEY=value, got {text!r}")
    key, value = text.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError(f"empty env key in {text!r}")
    return key, value
