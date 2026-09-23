"""Memory-bounded numerical atoms for combining complex spectrograms.

All inputs use ``(channels, frequency, time)`` layout.  Members may end at
different frames and may also have an invalid aligned prefix; neither kind of
padding participates in a reduction.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence

import numpy as np

from bundled.constants import (
    AUDIO_AVERAGE,
    HYBRID_SPEC,
    MAX_MAG_AVG_PHASE,
    MAX_SPEC,
    MEDIAN_SPEC,
    MIN_SPEC,
    SOFT_SPEC,
)

_ALGORITHMS = frozenset(
    {
        AUDIO_AVERAGE,
        MAX_SPEC,
        MIN_SPEC,
        MEDIAN_SPEC,
        SOFT_SPEC,
        MAX_MAG_AVG_PHASE,
        HYBRID_SPEC,
    }
)
_MAX_SMOOTHING = 4.0
_MAX_SOFT_STRENGTH = 10.0
_TARGET_STACK_BYTES = 8 * 1024 * 1024


def _bounded_float(name: str, value: float, low: float, high: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if not low <= result <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return result


def _validate_inputs(
    algorithm: str,
    inputs: Sequence[np.ndarray],
    weights: Sequence[float] | None,
    valid_starts: Sequence[int] | None,
) -> tuple[list[np.ndarray], np.ndarray, np.ndarray, np.dtype[np.complexfloating]]:
    if algorithm not in _ALGORITHMS:
        raise ValueError(f"unknown algorithm: {algorithm!r}")
    if not inputs:
        raise ValueError("combine_spectra requires at least one input")

    members = [np.asarray(member) for member in inputs]
    first_shape: tuple[int, int] | None = None
    for member in members:
        if member.ndim != 3:
            raise ValueError("spectra must be three-dimensional (channels, frequency, time)")
        if not np.issubdtype(member.dtype, np.complexfloating):
            raise ValueError("spectra must use a complex dtype")
        if member.shape[0] < 1 or member.shape[1] < 1 or member.shape[2] < 1:
            raise ValueError("spectra dimensions must be non-empty")
        shape = (member.shape[0], member.shape[1])
        if first_shape is None:
            first_shape = shape
        elif shape != first_shape:
            raise ValueError("all spectra must have matching channel and frequency dimensions")
        if not np.isfinite(member).all():
            raise ValueError("spectra must contain only finite values")

    if weights is None:
        priors = np.ones(len(members), dtype=np.float64)
    else:
        if len(weights) != len(members):
            raise ValueError("weights must contain one value per input")
        try:
            priors = np.asarray(weights, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError("weights must be finite non-negative numbers") from exc
        if priors.ndim != 1 or not np.isfinite(priors).all():
            raise ValueError("weights must be finite non-negative numbers")
        if np.any(priors < 0):
            raise ValueError("weights must be non-negative")
    if not np.any(priors > 0):
        raise ValueError("weights must have a positive total")

    if valid_starts is None:
        starts = np.zeros(len(members), dtype=np.int64)
    else:
        if len(valid_starts) != len(members):
            raise ValueError("valid_starts must contain one value per input")
        checked: list[int] = []
        for start, member in zip(valid_starts, members, strict=True):
            if isinstance(start, bool) or not isinstance(start, numbers.Integral):
                raise ValueError("valid_starts must contain integer frame indices")
            index = int(start)
            if index < 0 or index > member.shape[-1]:
                raise ValueError("valid_starts entries must be within each input timeline")
            checked.append(index)
        starts = np.asarray(checked, dtype=np.int64)

    keep = priors > 0
    kept_members = [member for member, include in zip(members, keep, strict=True) if include]
    kept_priors = priors[keep]
    kept_priors = kept_priors / np.max(kept_priors)
    kept_starts = starts[keep]
    output_dtype = np.dtype(np.result_type(*(member.dtype for member in kept_members)))
    return kept_members, kept_priors, kept_starts, output_dtype


def _moving_sum(values: np.ndarray, radius: int, axis: int) -> np.ndarray:
    if radius == 0:
        return values
    padding = [(0, 0)] * values.ndim
    padding[axis] = (radius, radius)
    padded = np.pad(values, padding, mode="constant")
    cumulative = np.cumsum(padded, axis=axis)
    zero_shape = list(cumulative.shape)
    zero_shape[axis] = 1
    cumulative = np.concatenate(
        (np.zeros(zero_shape, dtype=cumulative.dtype), cumulative), axis=axis
    )
    window = radius * 2 + 1
    upper = [slice(None)] * cumulative.ndim
    lower = [slice(None)] * cumulative.ndim
    upper[axis] = slice(window, None)
    lower[axis] = slice(None, -window)
    return cumulative[tuple(upper)] - cumulative[tuple(lower)]


def _local_mean(values: np.ndarray, valid: np.ndarray, radius: int) -> np.ndarray:
    mask = np.broadcast_to(valid[:, None, :], values.shape)
    totals = _moving_sum(_moving_sum(np.where(mask, values, 0.0), radius, 1), radius, 2)
    counts = _moving_sum(_moving_sum(mask.astype(np.float64, copy=False), radius, 1), radius, 2)
    return np.divide(totals, counts, out=np.zeros_like(totals), where=counts > 0)


def _weighted_average(stack: np.ndarray, valid: np.ndarray, priors: np.ndarray) -> np.ndarray:
    factors = priors[:, None, None, None] * valid[:, None, None, :]
    denominator = np.sum(factors, axis=0)
    blend = np.divide(
        factors,
        denominator[None, ...],
        out=np.zeros_like(factors),
        where=denominator[None, ...] > 0,
    )
    return np.sum(stack * blend, axis=0)


def _hard_extreme(stack: np.ndarray, valid: np.ndarray, *, maximum: bool) -> np.ndarray:
    magnitudes = np.abs(stack)
    fill = -np.inf if maximum else np.inf
    scores = np.where(valid[:, None, None, :], magnitudes, fill)
    indices = np.argmax(scores, axis=0) if maximum else np.argmin(scores, axis=0)
    result = np.take_along_axis(stack, indices[None, ...], axis=0)[0]
    result[..., ~np.any(valid, axis=0)] = 0
    return result


def _smoothed_extreme(
    stack: np.ndarray,
    valid: np.ndarray,
    priors: np.ndarray,
    smoothing: float,
    *,
    maximum: bool,
) -> np.ndarray:
    if smoothing == 0:
        return _hard_extreme(stack, valid, maximum=maximum)

    linked_magnitude = np.mean(np.abs(stack), axis=1)
    active = valid[:, None, :]
    active_count = np.sum(active, axis=0)
    scale = np.divide(
        np.sum(np.where(active, linked_magnitude, 0.0), axis=0),
        active_count,
        out=np.ones(linked_magnitude.shape[1:], dtype=linked_magnitude.dtype),
        where=active_count > 0,
    )
    real_dtype = linked_magnitude.dtype
    eps = np.finfo(real_dtype).eps * 16
    normalized = linked_magnitude / np.maximum(scale[None, ...], eps)
    scores = normalized if maximum else -normalized
    radius = min(4, max(1, math.ceil(smoothing)))
    scores = _local_mean(scores, valid, radius)

    temperature = max(0.15, 0.35 * smoothing)
    logits = scores / temperature + np.log(priors)[:, None, None]
    logits = np.where(active, logits, -np.inf)
    peak = np.max(logits, axis=0, keepdims=True)
    covered = np.any(active, axis=0, keepdims=True)
    peak = np.where(covered, peak, 0.0)
    blend = np.where(active, np.exp(logits - peak), 0.0)
    blend_sum = np.sum(blend, axis=0, keepdims=True)
    blend = np.divide(blend, blend_sum, out=np.zeros_like(blend), where=blend_sum > 0)
    return np.sum(stack * blend[:, None, ...], axis=0)


def _unweighted_median(values: np.ndarray, valid: np.ndarray) -> np.ndarray:
    active = valid[:, None, None, :]
    ordered = np.sort(np.where(active, values, np.inf), axis=0)
    counts = np.sum(valid, axis=0)
    lower = np.maximum((counts - 1) // 2, 0)[None, None, None, :]
    upper = np.maximum(counts // 2, 0)[None, None, None, :]
    low_value = np.take_along_axis(ordered, lower, axis=0)[0]
    high_value = np.take_along_axis(ordered, upper, axis=0)[0]
    result = 0.5 * (low_value + high_value)
    result[..., counts == 0] = 0
    return result


def _soft_agreement(
    stack: np.ndarray,
    valid: np.ndarray,
    priors: np.ndarray,
    strength: float,
) -> np.ndarray:
    magnitudes = np.abs(stack)
    active = valid[:, None, None, :]
    count = np.sum(active, axis=0, keepdims=True)
    mean = np.divide(
        np.sum(magnitudes, axis=0, keepdims=True),
        count,
        out=np.zeros_like(magnitudes[:1]),
        where=count > 0,
    )
    variance = np.divide(
        np.sum(np.where(active, (magnitudes - mean) ** 2, 0.0), axis=0, keepdims=True),
        count,
        out=np.zeros_like(mean),
        where=count > 0,
    )
    # Preserve the original mean/variance agreement rule; priors are optional.
    logits = -strength * (magnitudes - mean) ** 2 / (variance + 1e-8)
    logits = np.where(active, logits + np.log(priors)[:, None, None, None], -np.inf)
    peak = np.max(logits, axis=0, keepdims=True)
    peak = np.where(count > 0, peak, 0.0)
    blend = np.where(active, np.exp(logits - peak), 0.0)
    total = np.sum(blend, axis=0, keepdims=True)
    blend = np.divide(blend, total, out=np.zeros_like(blend), where=total > 0)
    return np.sum(stack * blend, axis=0)


def _component_median(
    stack: np.ndarray,
    valid: np.ndarray,
    priors: np.ndarray,
) -> np.ndarray:
    """Coordinate-wise median, with weighted median intervals for unequal priors."""

    def median(values: np.ndarray) -> np.ndarray:
        if np.all(priors == priors[0]):
            return _unweighted_median(values, valid)
        active = valid[:, None, None, :]
        order = np.argsort(np.where(active, values, np.inf), axis=0)
        ordered = np.take_along_axis(values, order, axis=0)
        factors = np.broadcast_to(priors[:, None, None, None] * active, values.shape)
        cumulative = np.cumsum(np.take_along_axis(factors, order, axis=0), axis=0)
        half = cumulative[-1:] * 0.5
        lower = np.argmax(cumulative >= half, axis=0)
        upper = np.argmax(cumulative > half, axis=0)
        result = 0.5 * (
            np.take_along_axis(ordered, lower[None, ...], axis=0)[0]
            + np.take_along_axis(ordered, upper[None, ...], axis=0)[0]
        )
        result[..., ~np.any(valid, axis=0)] = 0
        return result

    return median(np.real(stack)) + 1j * median(np.imag(stack))


def _max_magnitude_average_phase(
    stack: np.ndarray,
    valid: np.ndarray,
    priors: np.ndarray,
) -> np.ndarray:
    magnitudes = np.abs(stack)
    active = valid[:, None, None, :]
    coefficients = priors[:, None, None, None] * active
    total = np.sum(coefficients, axis=0, keepdims=True)
    coefficients = np.divide(coefficients, total, out=np.zeros_like(coefficients), where=total > 0)
    # Circular mean of unit phasors: preserve the original equal-weight phase rule.
    unit = stack / (magnitudes + 1e-8)
    average_unit = np.sum(coefficients * unit, axis=0)
    maximum = np.max(np.where(active, magnitudes, 0.0), axis=0)
    return maximum * np.exp(1j * np.angle(average_unit))


def _combine_tile(
    algorithm: str,
    stack: np.ndarray,
    valid: np.ndarray,
    priors: np.ndarray,
    smoothing: float,
    soft_strength: float,
    hybrid_balance: float,
) -> np.ndarray:
    if algorithm == AUDIO_AVERAGE:
        return _weighted_average(stack, valid, priors)
    if algorithm == MAX_SPEC:
        return _smoothed_extreme(stack, valid, priors, smoothing, maximum=True)
    if algorithm == MIN_SPEC:
        return _smoothed_extreme(stack, valid, priors, smoothing, maximum=False)
    if algorithm == SOFT_SPEC:
        return _soft_agreement(stack, valid, priors, soft_strength)
    if algorithm == MEDIAN_SPEC:
        return _component_median(stack, valid, priors)
    if algorithm == MAX_MAG_AVG_PHASE:
        return _max_magnitude_average_phase(stack, valid, priors)
    if algorithm == HYBRID_SPEC:
        minimum = _smoothed_extreme(stack, valid, priors, smoothing, maximum=False)
        maximum = _smoothed_extreme(stack, valid, priors, smoothing, maximum=True)
        return minimum * (1.0 - hybrid_balance) + maximum * hybrid_balance
    raise AssertionError(f"validated ensemble algorithm was not dispatched: {algorithm!r}")


def _load_tile(
    members: Sequence[np.ndarray],
    starts: np.ndarray,
    begin: int,
    end: int,
    dtype: np.dtype[np.complexfloating],
) -> tuple[np.ndarray, np.ndarray]:
    channels, frequencies = members[0].shape[:2]
    width = end - begin
    stack = np.zeros((len(members), channels, frequencies, width), dtype=dtype)
    valid = np.zeros((len(members), width), dtype=bool)
    for index, (member, valid_start) in enumerate(zip(members, starts, strict=True)):
        overlap_start = max(begin, int(valid_start))
        overlap_end = min(end, member.shape[-1])
        if overlap_start >= overlap_end:
            continue
        target = slice(overlap_start - begin, overlap_end - begin)
        source = slice(overlap_start, overlap_end)
        stack[index, ..., target] = member[..., source]
        valid[index, target] = True
    return stack, valid


def combine_spectra(
    algorithm: str,
    inputs: Sequence[np.ndarray],
    *,
    weights: Sequence[float] | None = None,
    valid_starts: Sequence[int] | None = None,
    smoothing: float = 0.0,
    soft_strength: float = 1.0,
    hybrid_balance: float = 0.5,
) -> np.ndarray:
    """Combine channel-first complex spectra without materializing full padding.

    ``weights`` are non-negative priors; zero removes a member. ``valid_starts``
    marks leading frames introduced by alignment as absent. Max and Hybrid
    always use the evaluated smoothing strength of 1. ``smoothing`` controls
    only Min: zero selects exact minima; positive values soften selection over
    nearby frequency/time bins and link channels, trading rejection for detail.
    """

    smoothing_value = _bounded_float("smoothing", smoothing, 0.0, _MAX_SMOOTHING)
    if algorithm in {MAX_SPEC, HYBRID_SPEC}:
        smoothing_value = 1.0
    strength_value = _bounded_float("soft_strength", soft_strength, 0.0, _MAX_SOFT_STRENGTH)
    balance_value = _bounded_float("hybrid_balance", hybrid_balance, 0.0, 1.0)
    members, priors, starts, dtype = _validate_inputs(algorithm, inputs, weights, valid_starts)

    channels, frequencies = members[0].shape[:2]
    output_frames = max(member.shape[-1] for member in members)
    result = np.zeros((channels, frequencies, output_frames), dtype=dtype)
    bytes_per_frame = max(1, len(members) * channels * frequencies * dtype.itemsize)
    block_frames = max(1, min(output_frames, _TARGET_STACK_BYTES // bytes_per_frame))
    radius = (
        0
        if smoothing_value == 0 or algorithm not in {MAX_SPEC, MIN_SPEC, HYBRID_SPEC}
        else min(4, max(1, math.ceil(smoothing_value)))
    )

    for core_start in range(0, output_frames, block_frames):
        core_end = min(output_frames, core_start + block_frames)
        tile_start = max(0, core_start - radius)
        tile_end = min(output_frames, core_end + radius)
        stack, valid = _load_tile(members, starts, tile_start, tile_end, dtype)
        combined = _combine_tile(
            algorithm,
            stack,
            valid,
            priors,
            smoothing_value,
            strength_value,
            balance_value,
        )
        source = slice(core_start - tile_start, core_end - tile_start)
        result[..., core_start:core_end] = combined[..., source]
    return result


__all__ = ["combine_spectra"]
