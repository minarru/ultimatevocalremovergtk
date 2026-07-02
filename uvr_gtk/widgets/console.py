"""Read-only console log view.

Replaces the Tk ``ThreadSafeConsole``. Text is appended from the separation
worker via the callbacks marshaled onto the main loop (see
:mod:`uvr_gtk.dispatch`), so :meth:`ConsoleView.append` is only ever called on
the GTK main thread.
"""

from typing import Callable, Optional

from gi.repository import GLib, Gtk

from data.constants import DONE


class ConsoleView(Gtk.ScrolledWindow):
    def __init__(self, on_changed: Optional[Callable[[bool], None]] = None):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_vexpand(True)

        self._on_changed = on_changed
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

    def append(self, text: str) -> None:
        # ``DONE`` completes the current in-progress line (no trailing newline).
        # Skip it when there is no open line, which avoids a lone " Done!" at run
        # start before the first "Running inference..." message is written.
        if text == DONE and (self.is_empty() or self.get_text().endswith("\n")):
            return

        end = self._buffer.get_end_iter()
        self._buffer.insert(end, text)
        self._scroll_to_end()
        self._notify_changed()

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

    def _scroll_to_end(self) -> None:
        GLib.idle_add(self._do_scroll)

    def _do_scroll(self) -> bool:
        if not self.get_mapped():
            GLib.idle_add(self._do_scroll)
            return GLib.SOURCE_REMOVE

        mark = self._buffer.create_mark(None, self._buffer.get_end_iter(), False)
        self._view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        self._buffer.delete_mark(mark)
        self._reset_horizontal_scroll()
        return GLib.SOURCE_REMOVE
