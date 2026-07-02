"""Error log buffer + viewer (port of UVR's ``error_log_var`` / ``menu_error_log``).

UVR keeps the last error in an in-memory ``error_log_var`` (formatted by
:func:`data.error_handling.error_text`) and shows it in a read-only window
with *Copy All Text* and *Report Issue* buttons. This module reproduces that:

* a process-wide :data:`_ERROR_LOG` buffer with :func:`log_error` /
  :func:`set_error_log` / :func:`get_error_log` so any view (downloads,
  separation, verification, ...) records errors in the same place and format;
* :func:`open_error_log`, the entry point the main window can call (also usable
  with an explicit ``message`` for one-off error dialogs).
"""

import threading

from gi.repository import Adw, Gdk, Gtk

from data.constants import ISSUE_LINK
from data.error_handling import error_text

_LOCK = threading.Lock()
_ERROR_LOG = ""


def set_error_log(text: str) -> None:
    """Replace the current error log (mirrors ``error_log_var.set``)."""
    global _ERROR_LOG
    with _LOCK:
        _ERROR_LOG = text or ""


def log_error(process_method: str, exception: BaseException) -> str:
    """Format ``exception`` like UVR and store it as the current error log.

    Thread-safe so worker threads can record errors directly; returns the
    formatted text.
    """
    formatted = error_text(process_method, exception)
    set_error_log(formatted)
    return formatted


def get_error_log() -> str:
    with _LOCK:
        return _ERROR_LOG


def open_error_log(parent_window, message=None):
    """Open the Error Console window. Wire this to a ``win.error_log`` action.

    When ``message`` is given it is shown (and recorded) instead of the stored
    log, matching how UVR surfaces a specific error.
    """
    if message is not None:
        set_error_log(message)
    text = get_error_log() or "No errors have been logged."

    window = Adw.Window(title="Error Console")
    window.set_default_size(700, 520)
    if parent_window is not None:
        window.set_transient_for(parent_window)

    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()

    copy_button = Gtk.Button(label="Copy All Text")
    copy_button.connect("clicked", lambda *_: _copy_to_clipboard(window, text))
    header.pack_start(copy_button)

    report_button = Gtk.Button(label="Report Issue")
    report_button.connect("clicked", lambda *_: _open_link(ISSUE_LINK))
    header.pack_start(report_button)

    toolbar.add_top_bar(header)

    buffer = Gtk.TextBuffer()
    buffer.set_text(text)
    text_view = Gtk.TextView(buffer=buffer)
    text_view.set_editable(False)
    text_view.set_cursor_visible(False)
    text_view.set_monospace(True)
    text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    text_view.set_left_margin(10)
    text_view.set_right_margin(10)
    text_view.set_top_margin(10)
    text_view.set_bottom_margin(10)
    text_view.add_css_class("card")

    scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
    scroller.set_child(text_view)
    toolbar.set_content(scroller)
    window.set_content(toolbar)
    window.present()
    return window


def _copy_to_clipboard(widget, text: str) -> None:
    display = widget.get_display() if hasattr(widget, "get_display") else Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def _open_link(url: str) -> None:
    import webbrowser

    webbrowser.open_new_tab(url)
