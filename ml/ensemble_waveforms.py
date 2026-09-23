"""Valid-sample waveform blending without padding missing members into votes."""

from collections.abc import Sequence

import numpy as np


def combine_waves(
    waves: Sequence[np.ndarray],
    algorithm: str,
    weights: Sequence[float],
    starts: Sequence[int],
) -> np.ndarray:
    length = max(w.shape[-1] for w in waves)
    dtype = np.result_type(*(w.dtype for w in waves), np.float32)
    output = np.zeros((waves[0].shape[0], length), dtype=dtype)
    if algorithm == "Average":
        total = np.zeros(length, dtype=np.float64)
        for wave, weight, start in zip(waves, weights, starts, strict=True):
            end = wave.shape[-1]
            output[:, start:end] += weight * wave[:, start:end]
            total[start:end] += weight
        np.divide(output, total[None, :], out=output, where=total[None, :] > 0)
        return output
    smallest = algorithm == "Min Spec"
    scores = np.full_like(output, np.inf if smallest else -np.inf)
    for wave, start in zip(waves, starts, strict=True):
        end = wave.shape[-1]
        magnitude = np.abs(wave[:, start:end])
        take = magnitude < scores[:, start:end] if smallest else magnitude > scores[:, start:end]
        np.copyto(output[:, start:end], wave[:, start:end], where=take)
        np.copyto(scores[:, start:end], magnitude, where=take)
    return output
