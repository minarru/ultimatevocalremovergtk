"""Monotone local-step mapping for one inference pass.

Hops fill 0.10–0.80. Extra work in the same pass (match-mix, Denoise Model)
continues through 0.80–0.89 so the bar never rewinds and never crosses the
0.90 save cutoff.
"""

from __future__ import annotations


INFER_START = 0.10
HOP_END = 0.80
EXTRA_END = 0.89


class InferenceProgress:
    """Per-pass hop + extra unit counter."""

    def __init__(self) -> None:
        self.value = 0
        self.total = 0
        self.extra_done = 0
        self.extra_total = 0

    def reset(self) -> None:
        self.value = 0
        self.total = 0
        self.extra_done = 0
        self.extra_total = 0

    def hop(self, total: int) -> float:
        units = max(1, int(total))
        if self.total <= 0:
            self.total = units
        elif units > self.total:
            self.total = units
        self.value += 1
        denom = max(1, self.total)
        return min(HOP_END, INFER_START + (HOP_END - INFER_START) * self.value / denom)

    def extra(self, phase_total: int) -> float:
        phase = max(1, int(phase_total))
        if self.extra_done >= self.extra_total:
            self.extra_total += phase
        self.extra_done += 1
        denom = max(1, self.extra_total)
        return min(
            EXTRA_END,
            HOP_END + (EXTRA_END - HOP_END) * self.extra_done / denom,
        )
