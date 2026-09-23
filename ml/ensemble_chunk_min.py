"""Fixed-duration quietest-member selection for the Chunk Min ensemble atom."""

import numbers
from collections.abc import Sequence

import numpy as np

_WINDOW_SECONDS = 1.0
_CROSSFADE_SECONDS = 0.100
_MIN_SWITCH_REDUCTION = 0.10


def combine_chunk_min(
    waveforms: Sequence[np.ndarray],
    sample_rate: int,
    valid_starts: Sequence[int] | None = None,
) -> np.ndarray:
    """Combine channel-first waves using shared stereo decisions and linear fades.

    Score one-second windows by mean absolute amplitude across all channels.
    Keep the current member unless a challenger is at least 10% quieter, or
    the current member ends. Ties retain the current member, including silence.
    This measures quietness, not separation quality. A 100 ms crossfade surrounds each
    member switch; weights sum to one to preserve gain for correlated signals.
    Short final windows and member endpoints clip the fades. Missing samples
    never participate in scoring or blending as padded silence.
    """
    if not waveforms or sample_rate <= 0:
        raise ValueError("Chunk Min requires members and a positive sample rate")
    members = [np.asarray(wave) for wave in waveforms]
    channels = members[0].shape[0] if members[0].ndim == 2 else 0
    if not channels or any(w.ndim != 2 or w.shape[0] != channels for w in members):
        raise ValueError("Chunk Min requires channel-first waves with matching channels")

    lengths = [w.shape[1] for w in members]
    if valid_starts is None:
        starts = [0] * len(members)
    else:
        if len(valid_starts) != len(members):
            raise ValueError("Chunk Min requires one valid start per member")
        starts = []
        for start, size in zip(valid_starts, lengths, strict=True):
            if (
                isinstance(start, bool)
                or not isinstance(start, numbers.Integral)
                or not 0 <= int(start) <= size
            ):
                raise ValueError("Chunk Min valid starts must be within each member")
            starts.append(int(start))
    length = max(lengths)
    dtype = np.result_type(*(w.dtype for w in members), np.float32)
    output = np.zeros((channels, length), dtype=dtype)
    window = max(1, round(sample_rate * _WINDOW_SECONDS))
    half_fade = round(sample_rate * _CROSSFADE_SECONDS / 2)
    # Split at support edges too: absent prefixes/tails never enter a score.
    boundaries = sorted(set(range(0, length, window)) | set(starts) | set(lengths) | {0})
    winners: list[int | None] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        candidates = [i for i, size in enumerate(lengths) if starts[i] <= start and size >= end]
        if not candidates:
            winners.append(None)
            continue
        scores = {
            i: float(np.mean(np.abs(members[i][:, start:end]), dtype=np.float64))
            for i in candidates
        }
        winner = min(candidates, key=lambda i: scores[i])
        if winners and winners[-1] is not None and winners[-1] in scores:
            previous = winners[-1]
            improves = scores[winner] < scores[previous]
            clears_margin = scores[winner] <= scores[previous] * (1.0 - _MIN_SWITCH_REDUCTION)
            if not (improves and clears_margin):
                winner = previous
        winners.append(winner)
        output[:, start:end] = members[winner][:, start:end]

    for index in range(1, len(winners)):
        previous, current = winners[index - 1], winners[index]
        if previous is None or current is None or previous == current:
            continue
        boundary = boundaries[index]
        # Half-neighbor limits keep fades disjoint, including tiny final windows.
        start = max(
            boundary - min(half_fade, (boundary - boundaries[index - 1]) // 2),
            starts[previous],
            starts[current],
        )
        end = min(
            boundary + min(half_fade, (boundaries[index + 1] - boundary) // 2),
            lengths[previous],
            lengths[current],
        )
        if end - start < 2:
            continue
        weight = np.linspace(0.0, 1.0, end - start, dtype=dtype)
        output[:, start:end] = (
            members[previous][:, start:end] * (1.0 - weight)
            + members[current][:, start:end] * weight
        )
    return output
