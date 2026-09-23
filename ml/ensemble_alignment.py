"""Conservative integer-delay diagnostics for ensemble waveforms."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.signal import correlate

_MAX_DELAY_SECONDS = 0.020
_EXCERPT_SECONDS = 0.250
_MAX_EXCERPT_SAMPLES = 8_192
_EXCERPT_COUNT = 3
_MIN_CORRELATION = 0.90
_MIN_PEAK_MARGIN = 0.05
_MIN_ZERO_LAG_IMPROVEMENT = 0.05
_MIN_RMS = 1e-7


@dataclass(frozen=True)
class AlignmentDiagnostic:
    """Alignment result and valid support for one ensemble member.

    A positive delay means that the member arrived later than the reference.
    ``valid_start_samples`` and ``valid_end_samples`` describe the half-open
    interval containing original samples in the returned member.
    """

    member_index: int
    delay_samples: int
    confidence: float
    applied: bool
    reason: str
    valid_start_samples: int
    valid_end_samples: int


@dataclass(frozen=True)
class _ExcerptEstimate:
    delay_samples: int
    peak: float
    margin: float
    zero_lag: float


def _sample_count(wave: np.ndarray) -> int:
    return int(wave.shape[-1])


def _mono_proxy(wave: np.ndarray) -> np.ndarray:
    values = np.asarray(wave, dtype=np.float64)
    if values.ndim == 1:
        return values
    return np.asarray(np.mean(values, axis=0, dtype=np.float64))


def _energetic_excerpt_starts(
    reference: np.ndarray,
    available_samples: int,
    max_delay: int,
    sample_rate: int,
) -> tuple[list[int], int]:
    usable_samples = available_samples - 2 * max_delay
    minimum_window = max(256, 4 * max_delay + 1)
    window_size = min(
        _MAX_EXCERPT_SAMPLES,
        max(1, round(sample_rate * _EXCERPT_SECONDS)),
        usable_samples // _EXCERPT_COUNT,
    )
    if window_size < minimum_window:
        return [], window_size

    starts: list[int] = []
    usable_start = max_delay
    for band_index in range(_EXCERPT_COUNT):
        band_start = usable_start + band_index * usable_samples // _EXCERPT_COUNT
        band_end = usable_start + (band_index + 1) * usable_samples // _EXCERPT_COUNT
        latest_start = band_end - window_size
        if latest_start < band_start:
            return [], window_size

        candidate_count = min(24, max(1, latest_start - band_start + 1))
        candidates = np.linspace(
            band_start,
            latest_start,
            num=candidate_count,
            dtype=np.int64,
        )
        best_start = max(
            (int(start) for start in candidates),
            key=lambda start: float(np.mean(np.square(reference[start : start + window_size]))),
        )
        starts.append(best_start)
    return starts, window_size


def _estimate_excerpt(
    reference: np.ndarray,
    member: np.ndarray,
    start: int,
    window_size: int,
    max_delay: int,
    ambiguity_radius: int,
) -> _ExcerptEstimate | None:
    reference_window = reference[start : start + window_size]
    member_region = member[start - max_delay : start + window_size + max_delay]
    if member_region.size != window_size + 2 * max_delay:
        return None

    reference_zero_mean = reference_window - np.mean(reference_window)
    reference_energy = float(np.dot(reference_zero_mean, reference_zero_mean))
    if reference_energy < window_size * _MIN_RMS**2:
        return None

    cumulative = np.concatenate(([0.0], np.cumsum(member_region)))
    cumulative_sq = np.concatenate(([0.0], np.cumsum(np.square(member_region))))
    window_sums = cumulative[window_size:] - cumulative[:-window_size]
    window_sums_sq = cumulative_sq[window_size:] - cumulative_sq[:-window_size]
    member_energy = np.maximum(
        window_sums_sq - np.square(window_sums) / window_size,
        0.0,
    )
    if float(np.max(member_energy)) < window_size * _MIN_RMS**2:
        return None
    numerator = correlate(
        member_region,
        reference_zero_mean,
        mode="valid",
        method="fft",
    )
    denominator = np.sqrt(reference_energy * member_energy)
    correlations = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator),
        where=denominator > window_size * _MIN_RMS**2,
    )
    correlations = np.nan_to_num(correlations, nan=0.0, posinf=0.0, neginf=0.0)

    peak_index = int(np.argmax(correlations))
    peak = float(correlations[peak_index])
    competing = correlations.copy()
    competing[
        max(0, peak_index - ambiguity_radius) : min(
            competing.size, peak_index + ambiguity_radius + 1
        )
    ] = -1.0
    second_peak = float(np.max(competing)) if competing.size else -1.0
    return _ExcerptEstimate(
        delay_samples=peak_index - max_delay,
        peak=peak,
        margin=peak - second_peak,
        zero_lag=float(correlations[max_delay]),
    )


def _diagnose_member(
    reference: np.ndarray,
    member: np.ndarray,
    sample_rate: int,
    member_index: int,
) -> AlignmentDiagnostic:
    reference_mono = _mono_proxy(reference)
    member_mono = _mono_proxy(member)
    available_samples = min(reference_mono.size, member_mono.size)
    max_delay = max(1, round(sample_rate * _MAX_DELAY_SECONDS))
    starts, window_size = _energetic_excerpt_starts(
        reference_mono,
        available_samples,
        max_delay,
        sample_rate,
    )
    if len(starts) != _EXCERPT_COUNT:
        return AlignmentDiagnostic(
            member_index,
            0,
            0.0,
            False,
            "insufficient samples",
            0,
            _sample_count(member),
        )

    ambiguity_radius = max(2, round(sample_rate * 0.0005))
    estimates = [
        _estimate_excerpt(
            reference_mono,
            member_mono,
            start,
            window_size,
            max_delay,
            ambiguity_radius,
        )
        for start in starts
    ]
    complete = [estimate for estimate in estimates if estimate is not None]
    if len(complete) != _EXCERPT_COUNT:
        return AlignmentDiagnostic(
            member_index,
            0,
            0.0,
            False,
            "insufficient signal energy",
            0,
            _sample_count(member),
        )

    delay = int(round(float(np.median([item.delay_samples for item in complete]))))
    confidence = float(min(item.peak for item in complete))
    if confidence < _MIN_CORRELATION:
        reason = "low correlation"
    elif min(item.margin for item in complete) < _MIN_PEAK_MARGIN:
        reason = "ambiguous correlation"
    elif max(abs(item.delay_samples - delay) for item in complete) > max(
        1, round(sample_rate * 0.00025)
    ):
        reason = "inconsistent delay"
    elif (
        delay != 0
        and min(item.peak - item.zero_lag for item in complete) < _MIN_ZERO_LAG_IMPROVEMENT
    ):
        reason = "insufficient improvement over zero lag"
    elif abs(delay) >= max_delay:
        reason = "delay reached search boundary"
    elif delay == 0:
        reason = "already aligned"
    else:
        reason = "alignment available"

    return AlignmentDiagnostic(
        member_index,
        delay,
        max(0.0, min(1.0, confidence)),
        False,
        reason,
        0,
        _sample_count(member),
    )


def _shift_member(wave: np.ndarray, delay: int) -> tuple[np.ndarray, int, int]:
    if delay > 0:
        shifted = wave[..., delay:]
        return shifted, 0, _sample_count(shifted)
    if delay < 0:
        prefix = -delay
        padding = [(0, 0)] * wave.ndim
        padding[-1] = (prefix, 0)
        shifted = np.pad(wave, padding)
        return shifted, prefix, _sample_count(shifted)
    return wave, 0, _sample_count(wave)


def align_ensemble_members(
    waves: Sequence[np.ndarray],
    sample_rate: int,
    *,
    correct: bool = False,
) -> tuple[list[np.ndarray], list[AlignmentDiagnostic]]:
    """Diagnose and optionally correct bounded integer delays.

    Member zero is the reference. Callers that use weighted members should pass
    only positive-weight members, with the first such member at index zero.
    Corrections move every channel together and expose original-sample support in
    each diagnostic so downstream algorithms can ignore an early member's padded
    prefix. No gain, polarity, or time-scale changes are made.
    """

    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    aligned = list(waves)
    if not waves:
        return aligned, []

    for index, wave in enumerate(waves):
        if wave.ndim not in (1, 2):
            raise ValueError(f"member {index} must be a channel-first ndarray")
        if wave.ndim == 2 and wave.shape[0] == 0:
            raise ValueError(f"member {index} must contain at least one channel")

    reference = waves[0]
    reference_length = _sample_count(reference)
    diagnostics = [
        AlignmentDiagnostic(
            0,
            0,
            1.0 if reference_length else 0.0,
            False,
            "reference",
            0,
            reference_length,
        )
    ]

    for member_index, member in enumerate(waves[1:], start=1):
        diagnostic = _diagnose_member(reference, member, sample_rate, member_index)
        if diagnostic.reason == "alignment available":
            if correct:
                shifted, valid_start, valid_end = _shift_member(member, diagnostic.delay_samples)
                aligned[member_index] = shifted
                diagnostic = AlignmentDiagnostic(
                    member_index,
                    diagnostic.delay_samples,
                    diagnostic.confidence,
                    True,
                    "aligned",
                    valid_start,
                    valid_end,
                )
            else:
                diagnostic = AlignmentDiagnostic(
                    member_index,
                    diagnostic.delay_samples,
                    diagnostic.confidence,
                    False,
                    "correction disabled",
                    0,
                    _sample_count(member),
                )
        diagnostics.append(diagnostic)

    return aligned, diagnostics
