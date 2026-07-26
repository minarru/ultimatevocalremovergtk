"""Read-only console log view.

Replaces the Tk ``ThreadSafeConsole``. Text is appended from the separation
worker via the callbacks marshaled onto the main loop (see
:mod:`ui.dispatch`), so :meth:`ConsoleView.append` is only ever called on
the GTK main thread.
"""

from typing import Callable, Optional

from gi.repository import GLib, Gtk

from bundled.constants import DONE

#: Soft cap matching typical terminal scrollback; trim from the head when exceeded.
_CONSOLE_LINE_CAP = 5000


class ConsoleView(Gtk.ScrolledWindow):
    #: Matches revealer slide duration in :class:`ui.widgets.log_panel.LogPanel`.
    _LAYOUT_SETTLE_MS = 250

    def __init__(self, on_changed: Optional[Callable[[bool], None]] = None):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_vexpand(True)
        self.set_propagate_natural_height(False)
        self.set_overflow(Gtk.Overflow.HIDDEN)

        self._on_changed = on_changed
        self._scroll_idle_id: Optional[int] = None
        self._reconcile_scroll_id: Optional[int] = None
        self._viewport_idle_id: Optional[int] = None
        self._defer_scroll = False
        self._buffer = Gtk.TextBuffer()
        self._view = Gtk.TextView(buffer=self._buffer)
        self._view.set_editable(False)
        self._view.set_cursor_visible(False)
        self._view.set_monospace(True)
        self._view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._view.set_left_margin(8)
        self._view.set_right_margin(8)
        self._view.set_top_margin(8)
        self._view.set_bottom_margin(8)
        self.set_child(self._view)

        vadj = self.get_vadjustment()
        if vadj is not None:
            vadj.connect("notify::upper", self._on_viewport_changed)
            vadj.connect("notify::page-size", self._on_viewport_changed)

    def _on_viewport_changed(self, _adj: Gtk.Adjustment, _pspec) -> None:
        if not self.get_mapped():
            return
        if self._viewport_idle_id is not None:
            return
        self._viewport_idle_id = GLib.idle_add(self._on_viewport_idle)

    def _on_viewport_idle(self) -> bool:
        self._viewport_idle_id = None
        if not self.get_mapped():
            return GLib.SOURCE_REMOVE
        vadj = self.get_vadjustment()
        if vadj is None:
            return GLib.SOURCE_REMOVE
        upper = vadj.get_upper()
        page = vadj.get_page_size()
        if upper <= page + 0.5 or self._defer_scroll:
            if vadj.get_value() != vadj.get_lower():
                vadj.set_value(vadj.get_lower())
        return GLib.SOURCE_REMOVE

    def defer_scroll_until_settled(self) -> None:
        self._defer_scroll = True

    def resume_scroll(self) -> None:
        self._defer_scroll = False
        self._reset_scroll()

    def append(self, text: str) -> None:
        # ``DONE`` completes the current in-progress line (no trailing newline).
        # Skip it when there is no open line, which avoids a lone " Done!" at run
        # start before the first "Running inference..." message is written.
        if text == DONE and (self.is_empty() or self.get_text().endswith("\n")):
            return

        end = self._buffer.get_end_iter()
        self._buffer.insert(end, text)
        self._trim_to_line_cap()
        if self._defer_scroll:
            self._reset_scroll()
        else:
            self._scroll_to_end()
        self._notify_changed()

    def _trim_to_line_cap(self) -> None:
        line_count = self._buffer.get_line_count()
        if line_count <= _CONSOLE_LINE_CAP:
            return
        # Drop whole lines from the head; leave the newest cap lines.
        drop = line_count - _CONSOLE_LINE_CAP
        start = self._buffer.get_start_iter()
        end = self._buffer.get_iter_at_line(drop)
        self._buffer.delete(start, end)

    def clear(self) -> None:
        self._buffer.set_text("")
        self._reset_scroll()
        self._notify_changed()

    def is_empty(self) -> bool:
        return self._buffer.get_char_count() == 0

    def get_text(self) -> str:
        return self._buffer.get_text(
            self._buffer.get_start_iter(), self._buffer.get_end_iter(), False
        )

    def _notify_changed(self) -> None:
        if self._on_changed is not None:
            self._on_changed(self.is_empty())

    def _reset_scroll(self) -> None:
        hadj = self.get_hadjustment()
        vadj = self.get_vadjustment()
        if hadj is not None:
            hadj.set_value(hadj.get_lower())
        if vadj is not None:
            vadj.set_value(vadj.get_lower())

    def _reset_horizontal_scroll(self) -> None:
        hadj = self.get_hadjustment()
        if hadj is not None:
            hadj.set_value(hadj.get_lower())

    def scroll_to_end_stable(self) -> None:
        """Scroll to the latest line, then again after layout settles."""
        self._scroll_to_end()
        if self._reconcile_scroll_id is not None:
            GLib.source_remove(self._reconcile_scroll_id)
        self._reconcile_scroll_id = GLib.timeout_add(
            self._LAYOUT_SETTLE_MS, self._reconcile_scroll
        )

    def _scroll_to_end(self) -> None:
        if self._defer_scroll:
            return
        if self._scroll_idle_id is not None:
            return
        self._scroll_idle_id = GLib.idle_add(self._do_scroll)

    def _do_scroll(self) -> bool:
        self._scroll_idle_id = None
        if not self.get_mapped():
            self._scroll_idle_id = GLib.idle_add(self._do_scroll)
            return GLib.SOURCE_REMOVE

        self._scroll_view_to_end()
        return GLib.SOURCE_REMOVE

    def _reconcile_scroll(self) -> bool:
        self._reconcile_scroll_id = None
        if self.get_mapped():
            self._scroll_view_to_end()
        return GLib.SOURCE_REMOVE

    def _scroll_view_to_end(self) -> None:
        vadj = self.get_vadjustment()
        if vadj is None:
            return

        upper = vadj.get_upper()
        page = vadj.get_page_size()
        lower = vadj.get_lower()
        if upper <= page + 0.5:
            # Short content in a tall viewport: stay pinned to the top instead of
            # scrolling into blank space below the text.
            if vadj.get_value() != lower:
                vadj.set_value(lower)
        else:
            vadj.set_value(upper - page)
        self._reset_horizontal_scroll()
