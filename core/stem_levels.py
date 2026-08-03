"""Post-separation stem level helpers (match mix / prevent PCM clipping)."""

from __future__ import annotations
import typing

from typing import Dict, List, Mapping, MutableMapping, Optional, Tuple

import numpy as np

_GAIN_EPS = 1e-12
_GAIN_REPORT_TOL = 1e-3


def _as_float_array(audio: typing.Any) -> np.ndarray:
    return np.asarray(audio, dtype=np.float64)


def match_gain_to_mix(summed: np.ndarray, mix: np.ndarray) -> float:
    """Least-squares gain ``g`` minimizing ``||g * summed - mix||``."""
    summed_a = _as_float_array(summed)
    mix_a = _as_float_array(mix)
    n = min(summed_a.shape[-1], mix_a.shape[-1])
    if n <= 0:
        return 1.0
    summed_a = summed_a[..., :n]
    mix_a = mix_a[..., :n]
    denom = float(np.dot(summed_a.ravel(), summed_a.ravel()))
    if denom <= _GAIN_EPS:
        return 1.0
    return float(np.dot(summed_a.ravel(), mix_a.ravel()) / denom)


def peak_limit_gain(audio_arrays: Mapping[str, np.ndarray], *, peak_limit: float = 1.0) -> float:
    """Shared scale so every array's peak is at most ``peak_limit``."""
    if peak_limit <= 0:
        return 1.0
    peak = 0.0
    for audio in audio_arrays.values():
        arr = _as_float_array(audio)
        if arr.size:
            peak = max(peak, float(np.max(np.abs(arr))))
    if peak <= peak_limit or peak <= _GAIN_EPS:
        return 1.0
    return float(peak_limit / peak)


def scale_audio(audio: np.ndarray, gain: float) -> np.ndarray:
    if abs(gain - 1.0) <= _GAIN_EPS:
        return audio
    return np.asarray(audio, dtype=np.float64) * gain


def apply_stem_level_options(
    stems: Mapping[str, np.ndarray],
    mix: Optional[np.ndarray],
    *,
    match_mix_level: bool = False,
    prevent_export_clipping: bool = False,
    peak_limit: float = 1.0,
) -> Tuple[Dict[str, np.ndarray], List[str]]:
    """Apply optional level fixes to a multi-stem dict.

    ``match_mix_level`` scales every stem by one gain so their sum best-matches
    ``mix``. ``prevent_export_clipping`` then applies one shared scale so no
    stem exceeds ``peak_limit`` (avoids hard PCM clipping on write).
    """
    if not stems:
        return {}, []

    adjusted: Dict[str, np.ndarray] = {key: np.asarray(value) for key, value in stems.items()}
    messages: List[str] = []

    if match_mix_level and mix is not None and len(adjusted) >= 2:
        lengths = [int(np.asarray(v).shape[-1]) for v in adjusted.values() if np.asarray(v).size]
        n = min(lengths) if lengths else 0
        n = min(n, int(np.asarray(mix).shape[-1])) if n else 0
        if n > 0:
            summed = None
            for value in adjusted.values():
                piece = np.asarray(value)[..., :n]
                summed = piece if summed is None else summed + piece
            assert summed is not None
            gain = match_gain_to_mix(summed, mix)
            if abs(gain - 1.0) > _GAIN_REPORT_TOL:
                adjusted = {key: scale_audio(value, gain) for key, value in adjusted.items()}
                messages.append(f"Matched stem levels to mix (gain ×{gain:.3f})")

    if prevent_export_clipping:
        gain = peak_limit_gain(adjusted, peak_limit=peak_limit)
        if abs(gain - 1.0) > _GAIN_REPORT_TOL:
            adjusted = {key: scale_audio(value, gain) for key, value in adjusted.items()}
            messages.append(f"Scaled stems to prevent export clipping (gain ×{gain:.3f})")

    return adjusted, messages


def scale_to_peak_limit(audio: np.ndarray, *, peak_limit: float = 1.0) -> Tuple[np.ndarray, float]:
    """Scale a single buffer so its peak is at most ``peak_limit``."""
    gain = peak_limit_gain({"_": audio}, peak_limit=peak_limit)
    return scale_audio(audio, gain), gain


def export_format_can_clip(
    save_format: str,
    wav_type_set: str,
) -> bool:
    """True when the configured export format cannot store peaks above 1.0."""
    fmt = (save_format or "").upper()
    if fmt in {"FLAC", "MP3"}:
        return True
    if fmt == "WAV":
        return wav_type_set not in {"32-bit Float", "64-bit Float"}
    return True


def update_stem_mapping(
    target: MutableMapping[str, np.ndarray],
    updated: Mapping[str, np.ndarray],
) -> None:
    for key, value in updated.items():
        target[key] = value
