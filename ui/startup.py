"""Lifecycle scheduling for work that may wait until the first GTK frame."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib  # noqa: E402


class _FrameClockWidget(Protocol):
    def get_frame_clock(self) -> Gdk.FrameClock | None: ...


class FirstFrameScheduler:
    """Run one callback after a mapped widget has completed its first paint.

    The frame-clock signal only marks the end of painting. The callback itself
    runs from a main-loop idle, outside the frame-clock handler. A scheduler is
    single-use: repeated activation of the same window cannot enqueue duplicate
    startup work.
    """

    def __init__(
        self,
        *,
        idle_add: Callable[[Callable[[], bool]], int] = GLib.idle_add,
        source_remove: Callable[[int], Any] = GLib.source_remove,
    ) -> None:
        self._idle_add = idle_add
        self._source_remove = source_remove
        self._frame_clock: Gdk.FrameClock | None = None
        self._after_paint_id: int | None = None
        self._idle_id: int | None = None
        self._callback: Callable[[], None] | None = None
        self._scheduled = False
        self._cancelled = False

    def schedule(self, widget: _FrameClockWidget, callback: Callable[[], None]) -> bool:
        """Attach to ``widget`` and queue ``callback`` after its first paint."""
        if self._scheduled or self._cancelled:
            return False
        frame_clock = widget.get_frame_clock()
        if frame_clock is None:
            return False

        self._scheduled = True
        self._callback = callback
        self._frame_clock = frame_clock
        self._after_paint_id = frame_clock.connect("after-paint", self._on_after_paint)
        return True

    def cancel(self) -> None:
        """Disconnect pending frame/idle work and discard its callback."""
        self._cancelled = True
        self._disconnect_after_paint()
        if self._idle_id is not None:
            self._source_remove(self._idle_id)
            self._idle_id = None
        self._callback = None

    def _disconnect_after_paint(self) -> None:
        frame_clock = self._frame_clock
        handler_id = self._after_paint_id
        self._frame_clock = None
        self._after_paint_id = None
        if frame_clock is not None and handler_id is not None:
            frame_clock.disconnect(handler_id)

    def _on_after_paint(self, *_args: Any) -> None:
        self._disconnect_after_paint()
        if self._cancelled:
            return

        def run() -> bool:
            self._idle_id = None
            callback = self._callback
            self._callback = None
            if self._cancelled or callback is None:
                return GLib.SOURCE_REMOVE
            callback()
            return GLib.SOURCE_REMOVE

        self._idle_id = self._idle_add(run)


__all__ = ["FirstFrameScheduler"]
