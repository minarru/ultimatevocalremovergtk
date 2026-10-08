"""Waveform strip for one track: shared time axis, playhead, click or drag to seek.

With a range set, bars outside it are dimmed and a frame with a trim handle at
each edge marks it. A drag slides the whole range; a click inside it seeks, and a
click outside moves the range to start there. A resizable range also changes
length when either handle is dragged.

The envelope is drawn as mirrored, round-capped bars separated by gaps. Heights
use one absolute scale (±1.0 fills the row), so rows compare honestly.
Colours come from the widget's CSS colour; the audible row carries libadwaita's
``accent`` class, which turns that colour into the accent colour.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Callable, Literal

from gi.repository import Gtk

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from core.waveform import Peaks

WAVEFORM_HEIGHT = 44
BAR_WIDTH = 2
BAR_GAP = 1
BAR_PITCH = BAR_WIDTH + BAR_GAP
PLAYHEAD_WIDTH = 2
_INACTIVE_ALPHA = 0.55
_UNPLAYED_ALPHA = 0.4
_PLACEHOLDER_ALPHA = 0.25
# Dimmer than an unplayed bar inside the window, so the trim reads without a wash.
_OUTSIDE_RANGE_ALPHA = 0.22
# Pointer travel below this many pixels is a click, not a range drag.
_CLICK_SLOP = 4.0
# Trim handles sit just outside the range edges; the frame joins them.
HANDLE_WIDTH = 8
_HANDLE_RADIUS = 3.0
_FRAME_WIDTH = 2
_GRIP_WIDTH = 2
_GRIP_HEIGHT = 12
# Pixels around a handle that still grab it rather than the whole range.
_HANDLE_REACH = 6.0

Edge = Literal["start", "end"]


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


def bar_levels(peaks: Peaks, width: int, timeline: float) -> NDArray[np.float32]:
    """Per-bar mirrored amplitude for bars at ``x = i * BAR_PITCH`` across ``width``.

    Each bar covers exactly its own pitch of the shared time axis, so a bar sits
    under the playhead at the moment it plays; the last bar needs no trailing gap.
    """
    import numpy as np

    bars = (width + BAR_GAP) // BAR_PITCH
    if bars <= 0 or timeline <= 0:
        return np.zeros(0, dtype=np.float32)
    lows, highs = column_extents(peaks, bars, timeline * bars * BAR_PITCH / width)
    return np.maximum(highs, -lows)


def _noop(_seconds: float) -> None:
    return None


def _noop_range(_start: float, _length: float) -> None:
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def _bars_centred_from(x: float, bars: int) -> int:
    """First bar whose centre is at or after ``x``."""
    if bars <= 0:
        return 0
    index = math.ceil((x - BAR_WIDTH / 2) / BAR_PITCH - 1e-9)
    return min(max(index, 0), bars)


def handle_spans(
    edges: tuple[float, float], width: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Left and right extents of the start and end handles, kept inside ``width``."""
    first, last = edges
    left = _clamp(first - HANDLE_WIDTH, 0.0, max(0.0, width - HANDLE_WIDTH))
    right = _clamp(last, 0.0, max(0.0, width - HANDLE_WIDTH))
    return (left, left + HANDLE_WIDTH), (right, right + HANDLE_WIDTH)


def _snap(value: float, low: float, high: float, step: float) -> float:
    """``value`` on a ``step`` grid, kept within ``low`` and ``high``."""
    if step > 0:
        value = round(value / step) * step
    return _clamp(value, min(low, high), high)


def _rounded_rect(cr: Any, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = min(radius, width / 2, height / 2)
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _bars_centred_after(x: float, bars: int) -> int:
    """First bar whose centre is after ``x``."""
    if bars <= 0:
        return 0
    index = math.floor((x - BAR_WIDTH / 2) / BAR_PITCH + 1e-9) + 1
    return min(max(index, 0), bars)


class WaveformView(Gtk.DrawingArea):
    def __init__(self, track: str = "") -> None:
        # An image, not a slider: it is not focusable, and the dialog's Left/Right
        # keys are the keyboard route to seeking.
        super().__init__(accessible_role=Gtk.AccessibleRole.IMG)
        self.set_focusable(False)
        if track:
            self.update_property([Gtk.AccessibleProperty.LABEL], [f"{track} waveform"])
        self.on_seek: Callable[[float], None] = _noop
        #: Fired once when a drag or click leaves the range at a new start or length.
        self.on_range_changed: Callable[[float, float], None] = _noop_range
        #: Fired as a drag moves or resizes the range, before it is committed.
        self.on_range_preview: Callable[[float, float], None] = _noop_range
        self._range_start = 0.0
        self._range_length = 0.0
        # Length bounds and grid while a handle is dragged; no maximum means fixed.
        self._min_length = 0.0
        self._max_length = 0.0
        self._length_step = 0.0
        # Range when the current drag began, what it changes, and the furthest the
        # pointer went.
        self._drag_anchor = 0.0
        self._drag_anchor_length = 0.0
        self._drag_edge: Edge | None = None
        self._drag_travel = 0.0
        self._dragging = False
        self._peaks: Peaks | None = None
        self._timeline = 0.0
        self._position = 0.0
        self._active = False
        # Pixel column of the last playhead a redraw was queued for.
        self._playhead_column: int | None = None
        # Bar levels depend only on the peaks, width and axis, not the playhead.
        self._levels_peaks: Peaks | None = None
        self._levels_key: tuple[int, float] = (0, 0.0)
        self._levels: NDArray[np.float32] | None = None
        self.set_content_height(WAVEFORM_HEIGHT)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", lambda _c: self._sync_cursor())
        self.add_controller(motion)

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
        self._sync_cursor()
        self.queue_draw()

    def set_timeline(self, duration: float) -> None:
        self._timeline = max(0.0, duration)
        self._sync_cursor()
        self.queue_draw()

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        # Position ticks arrive far faster than the playhead crosses a pixel.
        width = self.get_width()
        if width > 0 and self.timeline > 0:
            column = int(seconds_to_x(seconds, width, self.timeline))
            if column == self._playhead_column:
                return
            self._playhead_column = column
        self.queue_draw()

    @property
    def range_start(self) -> float:
        return self._range_start

    @property
    def range_length(self) -> float:
        return self._range_length

    def set_range(self, start: float, length: float) -> None:
        """Show a range; a ``length`` of 0 or less turns it off."""
        self._range_length = max(0.0, length)
        self._range_start = max(0.0, start) if self._range_length else 0.0
        self._sync_cursor()
        self.queue_draw()

    def set_range_resizable(self, minimum: float, maximum: float, step: float = 0.0) -> None:
        """Let the handles change the length within ``minimum`` and ``maximum`` seconds.

        Lengths snap to multiples of ``step``. A ``maximum`` of 0 keeps the length fixed.
        """
        self._min_length = max(0.0, minimum)
        self._max_length = max(0.0, maximum)
        self._length_step = max(0.0, step)

    @property
    def range_movable(self) -> bool:
        """Whether the range has room to move; a range as long as the track does not."""
        return bool(self._range_length) and self.timeline > self._range_length

    @property
    def range_resizable(self) -> bool:
        return bool(self._range_length) and self._max_length > 0 and self.timeline > 0

    def edge_at(self, x: float, width: float) -> Edge | None:
        """The handle under ``x``, if the range is resizable and one is in reach."""
        if not self.range_resizable:
            return None
        edges = self._range_edges(int(width), self.timeline)
        if edges is None:
            return None
        best: Edge | None = None
        best_distance = _HANDLE_REACH
        for edge, (left, right) in zip(("start", "end"), handle_spans(edges, width), strict=True):
            distance = max(left - x, x - right, 0.0)
            if distance < best_distance or (distance == best_distance == 0.0):
                best, best_distance = edge, distance
        return best

    def _sync_cursor(self, *, hover: Edge | None = None) -> None:
        edge = self._drag_edge if self._dragging else hover
        if edge is not None:
            self.set_cursor_from_name("ew-resize")
        elif not self.range_movable:
            self.set_cursor_from_name(None)
        else:
            self.set_cursor_from_name("grabbing" if self._dragging else "grab")

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

    def begin_range_drag(self, x: float | None = None, width: float = 0.0) -> None:
        """Start a drag at ``x``: on a handle it resizes, anywhere else it slides."""
        self._drag_anchor = self._range_start
        self._drag_anchor_length = self._range_length
        timeline = self.timeline
        if timeline > 0:
            # A range longer than the track is resized from the part that is shown.
            self._drag_anchor_length = min(self._range_length, timeline - self._range_start)
        self._drag_edge = self.edge_at(x, width) if x is not None else None
        self._drag_travel = 0.0
        self._dragging = True
        self._sync_cursor()

    def update_range_drag(self, dx: float, width: float) -> None:
        self._drag_travel = max(self._drag_travel, abs(dx))
        timeline = self.timeline
        if self._drag_travel < _CLICK_SLOP or width <= 0 or timeline <= 0:
            return
        shift = dx / width * timeline
        if self._drag_edge == "start":
            end = self._drag_anchor + self._drag_anchor_length
            high = min(self._max_length, end)
            length = _snap(
                end - (self._drag_anchor + shift), self._min_length, high, self._length_step
            )
            self._range_start, self._range_length = end - length, length
        elif self._drag_edge == "end":
            high = min(self._max_length, timeline - self._drag_anchor)
            raw = self._drag_anchor_length + shift
            self._range_length = _snap(raw, self._min_length, high, self._length_step)
        else:
            latest = max(0.0, timeline - self._range_length)
            self._range_start = _clamp(self._drag_anchor + shift, 0.0, latest)
        self.queue_draw()
        self.on_range_preview(self._range_start, self._range_length)

    def end_range_drag(self, x: float, width: float) -> None:
        self._dragging = False
        self._sync_cursor(hover=self.edge_at(x, width))
        if self._drag_travel >= _CLICK_SLOP:
            self.on_range_changed(self._range_start, self._range_length)
            return
        timeline = self.timeline
        if timeline <= 0 or width <= 0:
            return
        seconds = x_to_seconds(x, width, timeline)
        end = self._range_start + self._range_length
        if self._range_start <= seconds <= end or not self.range_movable:
            self.on_seek(_clamp(seconds, self._range_start, end))
            return
        # Outside the range: start it at the click, as far as the track allows.
        self._range_start = _clamp(seconds, 0.0, timeline - self._range_length)
        self.queue_draw()
        self.on_range_changed(self._range_start, self._range_length)

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, x: float, _y: float) -> None:
        # Claiming keeps the press from also activating the row (switching tracks).
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        if self._range_length:
            self.begin_range_drag(x, self.get_width())
        else:
            self.seek_at(x, self.get_width())

    def _on_drag_update(self, gesture: Gtk.GestureDrag, dx: float, _dy: float) -> None:
        if self._range_length:
            self.update_range_drag(dx, self.get_width())
            return
        ok, x, _y = gesture.get_start_point()
        if ok:
            self.seek_at(x + dx, self.get_width())

    def _on_drag_end(self, gesture: Gtk.GestureDrag, dx: float, _dy: float) -> None:
        if not self._range_length:
            return
        ok, x, _y = gesture.get_start_point()
        if ok:
            self.end_range_drag(x + dx, self.get_width())

    def _on_motion(self, _controller: Gtk.EventControllerMotion, x: float, _y: float) -> None:
        if not self._dragging:
            self._sync_cursor(hover=self.edge_at(x, self.get_width()))

    # -- drawing ---------------------------------------------------------------

    def _draw(
        self, _area: Gtk.DrawingArea, cr: Any, width: int, height: int, *_data: object
    ) -> None:
        import cairo

        color = self.get_color()
        red, green, blue, alpha = color.red, color.green, color.blue, color.alpha
        middle = height / 2
        timeline = self.timeline
        peaks = self._peaks
        edges = self._range_edges(width, timeline)
        if peaks is None:
            self._draw_placeholder(cr, width, middle, edges, (red, green, blue, alpha))
        elif timeline > 0:
            cr.set_line_width(BAR_WIDTH)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            self._draw_bars(cr, peaks, width, middle, timeline, (red, green, blue, alpha))
        if edges is not None:
            self._draw_handles(cr, width, height, edges, (red, green, blue, alpha))
        if timeline <= 0:
            return
        # One playhead across every row, loaded or not.
        half = PLAYHEAD_WIDTH / 2
        playhead = min(max(seconds_to_x(self._position, width, timeline), half), width - half)
        cr.set_source_rgba(red, green, blue, alpha)
        cr.rectangle(round(playhead - half), 0, PLAYHEAD_WIDTH, height)
        cr.fill()

    def _range_edges(self, width: int, timeline: float) -> tuple[float, float] | None:
        if not self._range_length or timeline <= 0 or width <= 0:
            return None
        return (
            seconds_to_x(self._range_start, width, timeline),
            seconds_to_x(self._range_start + self._range_length, width, timeline),
        )

    def _draw_placeholder(
        self,
        cr: Any,
        width: int,
        middle: float,
        edges: tuple[float, float] | None,
        rgba: tuple[float, float, float, float],
    ) -> None:
        red, green, blue, alpha = rgba
        if edges is None:
            cr.set_source_rgba(red, green, blue, alpha * _PLACEHOLDER_ALPHA)
            cr.rectangle(0, middle - 0.5, width, 1)
            cr.fill()
            return
        first, last = edges
        dim = alpha * _PLACEHOLDER_ALPHA * _OUTSIDE_RANGE_ALPHA / _UNPLAYED_ALPHA
        for start, end, share in (
            (0.0, first, dim),
            (first, last, alpha * _PLACEHOLDER_ALPHA),
            (last, float(width), dim),
        ):
            if end <= start:
                continue
            cr.set_source_rgba(red, green, blue, share)
            cr.rectangle(start, middle - 0.5, end - start, 1)
            cr.fill()

    def _draw_handles(
        self,
        cr: Any,
        width: int,
        height: int,
        edges: tuple[float, float],
        rgba: tuple[float, float, float, float],
    ) -> None:
        """A frame along the range with a gripped trim handle at each edge."""
        import cairo

        red, green, blue, alpha = rgba
        cr.set_source_rgba(red, green, blue, alpha)
        spans = handle_spans(edges, width)
        (_, first), (last, _) = spans
        if last > first:
            cr.rectangle(first, 0, last - first, _FRAME_WIDTH)
            cr.rectangle(first, height - _FRAME_WIDTH, last - first, _FRAME_WIDTH)
        for left, right in spans:
            _rounded_rect(cr, round(left), 0, right - left, height, _HANDLE_RADIUS)
        cr.fill()
        # The grip is cut out of each handle, so it reads on any theme colour.
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        grip = min(_GRIP_HEIGHT, max(height - 4 * _FRAME_WIDTH, 0))
        for left, right in spans:
            centre = round(left) + (right - left) / 2
            _rounded_rect(
                cr,
                centre - _GRIP_WIDTH / 2,
                (height - grip) / 2,
                _GRIP_WIDTH,
                grip,
                _GRIP_WIDTH / 2,
            )
        cr.fill()
        cr.restore()

    def _bar_levels(self, peaks: Peaks, width: int, timeline: float) -> NDArray[np.float32]:
        key = (width, timeline)
        if self._levels is None or peaks is not self._levels_peaks or key != self._levels_key:
            self._levels = bar_levels(peaks, width, timeline)
            self._levels_peaks = peaks
            self._levels_key = key
        return self._levels

    def _draw_bars(
        self,
        cr: Any,
        peaks: Peaks,
        width: int,
        middle: float,
        timeline: float,
        rgba: tuple[float, float, float, float],
    ) -> None:
        red, green, blue, alpha = rgba
        levels = self._bar_levels(peaks, width, timeline)
        bars = len(levels)
        # A bar counts as played once the playhead reaches its centre.
        playhead = seconds_to_x(self._position, width, timeline)
        played = min(max(int((playhead - BAR_WIDTH / 2) // BAR_PITCH) + 1, 0), bars)
        strength = alpha * (1.0 if self._active else _INACTIVE_ALPHA)
        # Round caps add half the line width at each end; silence stays a dot.
        cap = BAR_WIDTH / 2
        edges = self._range_edges(width, timeline)
        if edges is None:
            spans = ((0, played, 1.0), (played, bars, _UNPLAYED_ALPHA))
        else:
            first, last = edges
            inside = _bars_centred_from(first, bars)
            after = _bars_centred_after(last, bars)
            spans = (
                (0, inside, _OUTSIDE_RANGE_ALPHA),
                (inside, min(played, after), 1.0),
                (max(inside, played), after, _UNPLAYED_ALPHA),
                (after, bars, _OUTSIDE_RANGE_ALPHA),
            )
        for start, end, share in spans:
            if start >= end:
                continue
            for bar in range(start, end):
                x = bar * BAR_PITCH + cap
                reach = max(float(levels[bar]) * middle - cap, 0.0)
                cr.move_to(x, middle - reach)
                cr.line_to(x, middle + reach)
            cr.set_source_rgba(red, green, blue, strength * share)
            cr.stroke()


__all__ = [
    "BAR_GAP",
    "BAR_PITCH",
    "BAR_WIDTH",
    "WAVEFORM_HEIGHT",
    "HANDLE_WIDTH",
    "WaveformView",
    "bar_levels",
    "column_extents",
    "handle_spans",
    "seconds_to_x",
    "x_to_seconds",
]
