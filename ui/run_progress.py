"""Progress text/fill policy, independent of GTK scheduling and widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.run_estimate import ProgressEtaTracker

_PROGRESS_EPSILON = 0.001
_PROGRESS_UI_MIN_INTERVAL = 0.1


@dataclass(frozen=True)
class ProgressPresentation:
    text: str
    fraction: float | None
    pulse: Literal["start", "stop"]


class RunProgressPresenter:
    def __init__(self) -> None:
        self.tracker = ProgressEtaTracker()
        self.reset(0.0)

    def reset(self, started_at: float) -> None:
        self.started_at = started_at
        self.tracker.reset()
        self._last_progress_ui_at = 0.0
        self._last_progress_phase: str | None = None
        self._last_progress_pass: int | None = None
        self._last_progress_combine: int | None = None

    def update(
        self,
        fraction: float,
        now: float,
        *,
        suspended: bool = False,
        local_step: float | None = None,
        pass_index: int | None = None,
        pass_total: int | None = None,
        detail: str | None = None,
        combine_index: int | None = None,
        combine_total: int | None = None,
    ) -> ProgressPresentation | None:
        if suspended:
            return None
        self.tracker.update(
            fraction,
            now,
            local_step=local_step,
            pass_index=pass_index,
            pass_total=pass_total,
            detail=detail,
            combine_index=combine_index,
            combine_total=combine_total,
        )
        phase = self.tracker.phase(fraction)
        force_ui = (
            fraction >= 1.0 - _PROGRESS_EPSILON
            or phase != self._last_progress_phase
            or pass_index != self._last_progress_pass
            or combine_index != self._last_progress_combine
        )
        if not force_ui and (now - self._last_progress_ui_at) < _PROGRESS_UI_MIN_INTERVAL:
            return
        self._last_progress_ui_at = now
        self._last_progress_phase = phase
        self._last_progress_pass = pass_index
        self._last_progress_combine = combine_index

        elapsed = max(0.0, now - self.started_at)
        text = self.tracker.format_text(fraction, elapsed, now=now)

        if fraction >= 1.0 - _PROGRESS_EPSILON:
            return ProgressPresentation(text, 1.0, "stop")
        if fraction <= _PROGRESS_EPSILON and self.tracker.held_display <= 0:
            return ProgressPresentation(text, None, "start")

        display = self.tracker.inference_display_fraction(fraction)
        if local_step is None:
            # Audio tools and other callers that only send a global fraction.
            display = fraction
        elif display is None:
            phase = self.tracker.phase(fraction)
            if phase == "loading" and self.tracker.held_display <= _PROGRESS_EPSILON:
                return ProgressPresentation(text, None, "start")
            # Ticked save / deverb / combine: paint the runner fraction.
            display = fraction
        return ProgressPresentation(text, display, "stop")
