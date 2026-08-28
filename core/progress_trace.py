"""Sampling policy for high-frequency progress diagnostics."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable

_UNSET = object()


@dataclass
class ProgressTraceSampler:
    """Keep progress traces useful without recording every producer tick."""

    step: float = 0.05
    heartbeat_seconds: float = 5.0
    clock: Callable[[], float] = time.monotonic
    _last_bucket: int = field(default=-1, init=False)
    _last_emitted_at: float = field(default=0.0, init=False)
    _last_fraction: float = field(default=-1.0, init=False)
    _last_context: object = field(default=_UNSET, init=False)

    def should_emit(self, fraction: float, *, context: object = None) -> bool:
        clamped = max(0.0, min(1.0, fraction))
        now = self.clock()
        bucket = math.floor((clamped + 1e-12) / self.step)
        first = self._last_fraction < 0.0
        terminal = clamped >= 1.0 and self._last_fraction < 1.0
        context_changed = self._last_context is not _UNSET and context != self._last_context
        crossed_step = bucket > self._last_bucket
        heartbeat = not first and now - self._last_emitted_at >= self.heartbeat_seconds
        emit = first or terminal or context_changed or crossed_step or heartbeat
        self._last_fraction = clamped
        if emit:
            self._last_bucket = bucket
            self._last_emitted_at = now
            self._last_context = context
        return emit
