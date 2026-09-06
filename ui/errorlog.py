"""Error log buffer + viewer (port of UVR's ``error_log_var`` / ``menu_error_log``).

UVR keeps the last error in an in-memory ``error_log_var`` (formatted by
:func:`data.error_handling.error_text`) and shows it in a read-only window
with *Copy All Text* and *Report Issue* buttons. This module reproduces that:

* a shared core error store with :func:`log_error` /
  :func:`set_error_log` / :func:`get_error_log` so any view (downloads,
  separation, verification, ...) records errors in the same place and format;
* :func:`open_error_log`, the entry point the main window can call (also usable
  with an explicit ``message`` for one-off error dialogs);
* :func:`present_error_dialog`, a modal summary shown when a run fails.
"""

from __future__ import annotations

import typing
import weakref
from typing import Callable, Optional

from gi.repository import Adw, Gdk, GLib, Gtk, Pango, PangoCairo

from bundled.error_handling import CONTACT_DEV, error_dialouge
from core.error_log import (
    append_error_log as append_error_log,
)
from core.error_log import (
    get_error_log as get_error_log,
)
from core.error_log import (
    log_error as log_error,
)
from core.error_log import (
    set_error_log as set_error_log,
)
from core.error_log import (
    subscribe_error_log,
)
from core.support_urls import fork_issue_url

from .dialogs.utils import (
    parent_window_width,
    present_modal_dialog,
)
from .protocols import WindowSizing
from .template import load_builder, object_from_builder

# Floating sheet width: wide enough to read, capped so it cannot grow with a
# long RuntimeError line. TextView (not Label) wraps to the allocated width.
_ERROR_DIALOG_WIDTH = 600
_ERROR_DIALOG_MARGIN = 64
_ERROR_SUMMARY_MIN_HEIGHT = 48
_ERROR_SUMMARY_MAX_HEIGHT = 280
_ERROR_SUMMARY_PAD_Y = 20  # TextView top+bottom margins
_ERROR_SUMMARY_LINE_FALLBACK = 18


def _estimate_wrapped_text_height(text: str, width_px: int) -> int:
    """Measure wrapped monospace height for ``text`` at ``width_px``."""
    try:
        import cairo

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        context = cairo.Context(surface)
        layout = PangoCairo.create_layout(context)
        layout.set_font_description(Pango.FontDescription("Monospace 11"))
        layout.set_width(max(1, width_px) * Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_text(text, -1)
        _width, height = layout.get_pixel_size()
        return height + _ERROR_SUMMARY_PAD_Y
    except Exception:  # fall back without cairo/pango layout
        chars_per_line = max(20, width_px // 8)
        lines = max(1, summary_line_count(text, chars_per_line))
        return lines * _ERROR_SUMMARY_LINE_FALLBACK + _ERROR_SUMMARY_PAD_Y


def summary_line_count(text: str, chars_per_line: int) -> int:
    total = 0
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            total += 1
            continue
        total += max(1, (len(paragraph) + chars_per_line - 1) // chars_per_line)
    return total


def _summary_viewport_height(text: str, width_px: int) -> int:
    """Natural text height, clamped to the scrollable maximum."""
    natural = _estimate_wrapped_text_height(text, width_px) + 4
    return max(_ERROR_SUMMARY_MIN_HEIGHT, min(_ERROR_SUMMARY_MAX_HEIGHT, natural))


def _make_summary_text_view(summary: str) -> Gtk.TextView:
    builder = load_builder("error-summary-text")
    buffer = object_from_builder(builder, "buffer", Gtk.TextBuffer)
    buffer.set_text(summary)
    view = object_from_builder(builder, "view", Gtk.TextView)
    return view


def _build_error_summary_view(summary: str, *, width: int) -> Gtk.Widget:
    """Selectable technical summary: snug for short errors, scroll when long."""
    content_width = max(200, width - 48)
    text_width = content_width - 24
    natural = _estimate_wrapped_text_height(summary, text_width) + 4
    view = _make_summary_text_view(summary)

    # Short errors: skip ScrolledWindow so the card hugs the text (no empty viewport).
    if natural <= _ERROR_SUMMARY_MAX_HEIGHT:
        view.set_size_request(content_width, -1)
        return view

    height = _ERROR_SUMMARY_MAX_HEIGHT
    builder = load_builder("error-summary-scroll")
    scroller = object_from_builder(builder, "scroller", Gtk.ScrolledWindow)
    scroller.set_min_content_width(content_width)
    scroller.set_max_content_width(content_width)
    scroller.set_min_content_height(height)
    scroller.set_max_content_height(height)
    scroller.set_size_request(content_width, height)
    scroller.set_child(view)
    return scroller


_ACTIVE_ERROR_DIALOG: Optional[Adw.Dialog] = None
_ERROR_LOG_WINDOW: Optional[Adw.Window] = None
_ERROR_LOG_BUFFER: Optional[Gtk.TextBuffer] = None
_ERROR_LOG_SINK: ErrorLogViewSink | None = None


def _error_dialog_width(parent_window: WindowSizing) -> int:
    parent_width = parent_window_width(parent_window, fallback=_ERROR_DIALOG_WIDTH)
    return max(360, min(_ERROR_DIALOG_WIDTH, parent_width - _ERROR_DIALOG_MARGIN))


class ErrorLogViewSink:
    """Own a viewer subscription; queued main-loop work never owns widgets."""

    def __init__(self, buffer: Gtk.TextBuffer) -> None:
        self._buffer: Gtk.TextBuffer | None = buffer
        self._closed = False
        sink_ref = weakref.ref(self)

        def on_changed() -> None:
            GLib.idle_add(_refresh_error_log_sink, sink_ref)

        self._unsubscribe = subscribe_error_log(on_changed)
        self.refresh()

    def refresh(self) -> None:
        if not self._closed and self._buffer is not None:
            self._buffer.set_text(get_error_log() or "No errors have been logged.")

    def close(self) -> None:
        self._closed = True
        self._unsubscribe()
        self._buffer = None


def _refresh_error_log_sink(sink_ref: weakref.ReferenceType[ErrorLogViewSink]) -> bool:
    sink = sink_ref()
    if sink is not None:
        sink.refresh()
    return GLib.SOURCE_REMOVE


def _refresh_error_log_window() -> bool:
    if _ERROR_LOG_BUFFER is not None:
        _ERROR_LOG_BUFFER.set_text(get_error_log() or "No errors have been logged.")
    return GLib.SOURCE_REMOVE


def present_error_dialog(
    parent_window: Gtk.Window,
    *,
    heading: str,
    exception: BaseException,
    formatted_log: Optional[str] = None,
    on_copied: Optional[Callable[[], None]] = None,
) -> None:
    """Show a modal failure dialog with copy / error-log actions."""
    from core.debug_log import debug

    debug("ui", f"present_error_dialog heading={heading!r} error={type(exception).__name__}")
    global _ACTIVE_ERROR_DIALOG

    if _ACTIVE_ERROR_DIALOG is not None:
        debug("error", f"present_error_dialog suppressed heading={heading!r} (dialog already open)")
        if formatted_log:
            append_error_log(formatted_log)
        else:
            log_error(heading, exception)
        toast = getattr(parent_window, "toast", None)
        if callable(toast):
            toast("Another error occurred — see Error Log")
        return

    log_text = formatted_log if formatted_log is not None else get_error_log()
    summary = f"{type(exception).__name__}: {exception}"
    guidance = _friendly_error_message(exception)
    sheet_width = _error_dialog_width(parent_window)

    builder = load_builder("error-dialog")
    dialog = object_from_builder(builder, "dialog", Adw.Dialog)
    dialog.set_content_width(sheet_width)

    # Limit natural label widths so long messages cannot widen the sheet.
    label_chars = max(28, sheet_width // 9)
    title_label = object_from_builder(builder, "title_label", Gtk.Label)
    title_label.set_label(heading)
    title_label.set_max_width_chars(label_chars)
    guidance_label = object_from_builder(builder, "guidance_label", Gtk.Label)
    if guidance:
        guidance_label.set_label(guidance)
        guidance_label.set_max_width_chars(label_chars)
        guidance_label.set_visible(True)
    hint = object_from_builder(builder, "hint", Gtk.Label)
    hint.set_max_width_chars(label_chars)
    summary_box = object_from_builder(builder, "summary_box", Gtk.Box)
    summary_box.append(_build_error_summary_view(summary, width=sheet_width))
    copy_button = object_from_builder(builder, "copy_button", Gtk.Button)
    copy_button.connect(
        "clicked",
        lambda *_: _copy_report(parent_window, log_text, on_copied),
    )
    view_button = object_from_builder(builder, "view_button", Gtk.Button)
    view_button.connect("clicked", lambda *_: open_error_log(parent_window))
    clamp = object_from_builder(builder, "clamp", Adw.Clamp)
    clamp.set_maximum_size(sheet_width)
    clamp.set_tightening_threshold(sheet_width)
    dialog.connect("closed", lambda *_: _clear_active_error_dialog())

    _ACTIVE_ERROR_DIALOG = dialog
    present_modal_dialog(dialog, parent_window)


def _copy_report(
    parent_window: Gtk.Window,
    log_text: str,
    on_copied: Optional[Callable[[], None]],
) -> None:
    if log_text:
        copy_text(parent_window, log_text)
        if on_copied is not None:
            on_copied()


def _clear_active_error_dialog() -> None:
    global _ACTIVE_ERROR_DIALOG
    _ACTIVE_ERROR_DIALOG = None


def _friendly_error_message(exception: BaseException) -> Optional[str]:
    """Return extra guidance for known failures, or ``None`` for generic errors."""
    text = error_dialouge(exception).strip()
    error_name = type(exception).__name__
    prefix = f"An Error Occurred: {error_name}"
    if text.startswith(prefix):
        text = text[len(prefix) :].strip()
    if not text or text == CONTACT_DEV:
        return None
    if text.endswith(CONTACT_DEV):
        text = text[: -len(CONTACT_DEV)].strip()
    return text or None


def open_error_log(parent_window: typing.Any, message: typing.Any = None):
    """Open the Error Console window. Wire this to a ``win.error_log`` action.

    When ``message`` is given it is shown (and recorded) instead of the stored
    log, matching how UVR surfaces a specific error.
    """
    if message is not None:
        set_error_log(message)
    global _ERROR_LOG_WINDOW, _ERROR_LOG_BUFFER, _ERROR_LOG_SINK
    if _ERROR_LOG_WINDOW is not None:
        _refresh_error_log_window()
        _ERROR_LOG_WINDOW.present()
        return _ERROR_LOG_WINDOW
    text = get_error_log() or "No errors have been logged."

    builder = load_builder("error-console")
    window = object_from_builder(builder, "window", Adw.Window)
    if parent_window is not None:
        window.set_transient_for(parent_window)
    from .dialogs.utils import close_on_escape

    close_on_escape(window)
    copy_button = object_from_builder(builder, "copy_button", Gtk.Button)
    copy_button.connect("clicked", lambda *_: copy_text(window, get_error_log()))
    clear_button = object_from_builder(builder, "clear_button", Gtk.Button)
    clear_button.connect("clicked", lambda *_: set_error_log(""))
    report_button = object_from_builder(builder, "report_button", Gtk.Button)
    report_button.connect(
        "clicked",
        lambda *_: _open_link(window, fork_issue_url(log_text=get_error_log())),
    )
    buffer = object_from_builder(builder, "buffer", Gtk.TextBuffer)
    buffer.set_text(text)
    _ERROR_LOG_WINDOW = window
    _ERROR_LOG_BUFFER = buffer
    _ERROR_LOG_SINK = ErrorLogViewSink(buffer)
    window.connect("close-request", _on_error_log_window_closed)
    window.present()
    return window


def _on_error_log_window_closed(_window: typing.Any) -> bool:
    global _ERROR_LOG_WINDOW, _ERROR_LOG_BUFFER, _ERROR_LOG_SINK
    if _ERROR_LOG_SINK is not None:
        _ERROR_LOG_SINK.close()
        _ERROR_LOG_SINK = None
    _ERROR_LOG_WINDOW = None
    _ERROR_LOG_BUFFER = None
    return False


def copy_text(widget: Gtk.Widget, text: str) -> None:
    display = widget.get_display() if hasattr(widget, "get_display") else Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def _open_link(window: Gtk.Window, url: str) -> None:
    from .files import open_uri_in_browser

    def on_error(message: str) -> None:
        toast = getattr(window, "toast", None)
        if callable(toast):
            toast(message)

    open_uri_in_browser(window, url, on_error=on_error)
