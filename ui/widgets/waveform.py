"""Waveform strip for one track: shared time axis, playhead, click or drag to seek.

Heights use one absolute scale (±1.0 fills the row), so rows compare honestly.
Colours come from the widget's CSS colour; the audible row carries libadwaita's
``accent`` class, which turns that colour into the accent colour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from gi.repository import Gtk

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from core.waveform import Peaks

WAVEFORM_HEIGHT = 40
_INACTIVE_ALPHA = 0.55
_UNPLAYED_ALPHA = 0.45
_PLACEHOLDER_ALPHA = 0.25


def x_to_seconds(x: float, width: float, duration: float) -> float:
    if width <= 0 or duration <= 0:
        return 0.0
    return min(max(x / width, 0.0), 1.0) * duration


def seconds_to_x(seconds: float, width: float, duration: float) -> float:
    if width <= 0 or duration <= 0:
        return 0.0
    return min(max(seconds / duration, 0.0), 1.0) * width


def column_extents(
    peaks: Peaks, width: int, timeline: float
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Per-pixel-column min and max on an axis ``timeline`` seconds long.

    Columns past the track's own end are omitted, so a shorter track stops early.
    """
    import numpy as np

    buckets = len(peaks.mins)
    if width <= 0 or buckets == 0 or timeline <= 0 or peaks.duration <= 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, empty
    per_column = timeline / width * buckets / peaks.duration
    starts = np.floor(np.arange(width) * per_column).astype(np.intp)
    starts = starts[starts < buckets]
    return np.minimum.reduceat(peaks.mins, starts), np.maximum.reduceat(peaks.maxs, starts)


def _noop(_seconds: float) -> None:
    return None


class WaveformView(Gtk.DrawingArea):
    def __init__(self, track: str = "") -> None:
        # An image, not a slider: it is not focusable, and the dialog's Left/Right
        # keys are the keyboard route to seeking.
        super().__init__(accessible_role=Gtk.AccessibleRole.IMG)
        self.set_focusable(False)
        if track:
            self.update_property([Gtk.AccessibleProperty.LABEL], [f"{track} waveform"])
        self.on_seek: Callable[[float], None] = _noop
        self._peaks: Peaks | None = None
        self._timeline = 0.0
        self._position = 0.0
        self._active = False
        self.set_content_height(WAVEFORM_HEIGHT)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.add_controller(drag)

    # -- state -----------------------------------------------------------------

    @property
    def peaks(self) -> Peaks | None:
        return self._peaks

    @property
    def timeline(self) -> float:
        if self._timeline > 0:
            return self._timeline
        return self._peaks.duration if self._peaks is not None else 0.0

    @property
    def position(self) -> float:
        return self._position

    @property
    def active(self) -> bool:
        return self._active

    def set_peaks(self, peaks: Peaks | None) -> None:
        self._peaks = peaks
        self.queue_draw()

    def set_timeline(self, duration: float) -> None:
        self._timeline = max(0.0, duration)
        self.queue_draw()

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        self.queue_draw()

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self.add_css_class("accent")
        else:
            self.remove_css_class("accent")
        self.queue_draw()

    # -- seeking ---------------------------------------------------------------

    def seek_at(self, x: float, width: float) -> None:
        timeline = self.timeline
        if timeline > 0 and width > 0:
            self.on_seek(x_to_seconds(x, width, timeline))

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, x: float, _y: float) -> None:
        # Claiming keeps the press from also activating the row (switching tracks).
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.seek_at(x, self.get_width())

    def _on_drag_update(self, gesture: Gtk.GestureDrag, dx: float, _dy: float) -> None:
        ok, x, _y = gesture.get_start_point()
        if ok:
            self.seek_at(x + dx, self.get_width())

    # -- drawing ---------------------------------------------------------------

    def _draw(
        self, _area: Gtk.DrawingArea, cr: Any, width: int, height: int, *_data: object
    ) -> None:
        color = self.get_color()
        red, green, blue, alpha = color.red, color.green, color.blue, color.alpha
        middle = height / 2
        timeline = self.timeline
        peaks = self._peaks
        if peaks is None:
            cr.set_source_rgba(red, green, blue, alpha * _PLACEHOLDER_ALPHA)
            cr.rectangle(0, middle - 0.5, width, 1)
            cr.fill()
        elif timeline > 0:
            self._draw_envelope(cr, peaks, width, middle, timeline, (red, green, blue, alpha))
        if timeline <= 0:
            return
        # One playhead across every row, loaded or not.
        playhead = min(seconds_to_x(self._position, width, timeline), max(width - 1, 0))
        cr.set_source_rgba(red, green, blue, alpha)
        cr.rectangle(playhead, 0, 1, height)
        cr.fill()

    def _draw_envelope(
        self,
        cr: Any,
        peaks: Peaks,
        width: int,
        middle: float,
        timeline: float,
        rgba: tuple[float, float, float, float],
    ) -> None:
        red, green, blue, alpha = rgba
        lows, highs = column_extents(peaks, width, timeline)
        columns = len(highs)
        played = min(int(seconds_to_x(self._position, width, timeline)), columns)
        strength = alpha * (1.0 if self._active else _INACTIVE_ALPHA)
        for first, last, share in ((0, played, 1.0), (played, columns, _UNPLAYED_ALPHA)):
            if first >= last:
                continue
            for column in range(first, last):
                high = float(highs[column])
                low = float(lows[column])
                cr.rectangle(column, middle - high * middle, 1, max((high - low) * middle, 1.0))
            cr.set_source_rgba(red, green, blue, strength * share)
            cr.fill()


__all__ = [
    "WAVEFORM_HEIGHT",
    "WaveformView",
    "column_extents",
    "seconds_to_x",
    "x_to_seconds",
]
