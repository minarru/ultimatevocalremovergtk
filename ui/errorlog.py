"""Error log buffer + viewer (port of UVR's ``error_log_var`` / ``menu_error_log``).

UVR keeps the last error in an in-memory ``error_log_var`` (formatted by
:func:`data.error_handling.error_text`) and shows it in a read-only window
with *Copy All Text* and *Report Issue* buttons. This module reproduces that:

* a process-wide :data:`_ERROR_LOG` buffer with :func:`log_error` /
  :func:`set_error_log` / :func:`get_error_log` so any view (downloads,
  separation, verification, ...) records errors in the same place and format;
* :func:`open_error_log`, the entry point the main window can call (also usable
  with an explicit ``message`` for one-off error dialogs);
* :func:`present_error_dialog`, a modal summary shown when a run fails.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from gi.repository import Adw, Gdk, Gtk

from data.constants import ISSUE_LINK
from data.error_handling import CONTACT_DEV, error_dialouge, error_text

from .dialogs.utils import fill_dialog_width, present_modal_dialog, set_dialog_content

_ERROR_DIALOG_WIDTH = 360

_LOCK = threading.Lock()
_ERROR_LOG = ""
_ACTIVE_ERROR_DIALOG: Optional[Adw.Dialog] = None


def set_error_log(text: str) -> None:
    """Replace the current error log (mirrors ``error_log_var.set``)."""
    from uvr_core.debug_log import debug, preview_text

    global _ERROR_LOG
    with _LOCK:
        _ERROR_LOG = text or ""
    if text:
        debug("error", f"set_error_log {preview_text(text, max_len=120)!r}")


def log_error(process_method: str, exception: BaseException) -> str:
    """Format ``exception`` like UVR and store it as the current error log.

    Thread-safe so worker threads can record errors directly; returns the
    formatted text.
    """
    from uvr_core.debug_log import debug, preview_text

    formatted = error_text(process_method, exception)
    set_error_log(formatted)
    debug(
        "error",
        f"log_error method={process_method!r} error={type(exception).__name__}: {exception}",
    )
    return formatted


def get_error_log() -> str:
    with _LOCK:
        return _ERROR_LOG


def present_error_dialog(
    parent_window: Gtk.Window,
    *,
    heading: str,
    exception: BaseException,
    formatted_log: Optional[str] = None,
    on_copied: Optional[Callable[[], None]] = None,
) -> None:
    """Show a modal failure dialog with copy / error-log actions."""
    from uvr_core.debug_log import debug

    debug("ui", f"present_error_dialog heading={heading!r} error={type(exception).__name__}")
    global _ACTIVE_ERROR_DIALOG

    if _ACTIVE_ERROR_DIALOG is not None:
        debug("error", f"present_error_dialog suppressed heading={heading!r} (dialog already open)")
        return

    log_text = formatted_log if formatted_log is not None else get_error_log()
    summary = f"{type(exception).__name__}: {exception}"
    guidance = _friendly_error_message(exception)

    dialog = Adw.Dialog()
    dialog.set_content_width(_ERROR_DIALOG_WIDTH)
    dialog.set_follows_content_size(False)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    content.set_margin_bottom(20)
    content.set_margin_start(20)
    content.set_margin_end(20)
    fill_dialog_width(content)

    intro = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    intro.set_halign(Gtk.Align.FILL)
    icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
    icon.set_pixel_size(36)
    icon.set_valign(Gtk.Align.START)
    icon.add_css_class("error")
    intro.append(icon)

    intro_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    intro_text.set_hexpand(True)
    intro_text.set_valign(Gtk.Align.CENTER)

    title_label = Gtk.Label(label=heading)
    title_label.set_wrap(True)
    title_label.set_xalign(0.0)
    title_label.set_halign(Gtk.Align.FILL)
    title_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    title_label.add_css_class("title-4")
    intro_text.append(title_label)

    if guidance:
        guidance_label = Gtk.Label(label=guidance)
        guidance_label.set_wrap(True)
        guidance_label.set_xalign(0.0)
        guidance_label.set_halign(Gtk.Align.FILL)
        guidance_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        guidance_label.set_selectable(True)
        intro_text.append(guidance_label)

    intro.append(intro_text)
    content.append(intro)

    summary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    summary_box.add_css_class("card")
    fill_dialog_width(summary_box)

    summary_label = Gtk.Label(label=summary)
    summary_label.set_wrap(True)
    summary_label.set_xalign(0.0)
    summary_label.set_halign(Gtk.Align.FILL)
    summary_label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    summary_label.set_selectable(True)
    summary_label.add_css_class("monospace")
    summary_label.set_margin_top(12)
    summary_label.set_margin_bottom(12)
    summary_label.set_margin_start(12)
    summary_label.set_margin_end(12)
    summary_box.append(summary_label)
    content.append(summary_box)

    hint = Gtk.Label(
        label="View the log for the full traceback, or copy the report when asking for help"
    )
    hint.set_wrap(True)
    hint.set_xalign(0.0)
    hint.set_halign(Gtk.Align.FILL)
    hint.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    hint.add_css_class("dim-label")
    content.append(hint)

    button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    button_row.set_halign(Gtk.Align.END)
    button_row.set_margin_top(4)

    copy_button = Gtk.Button(label="Copy Report")
    copy_button.connect(
        "clicked",
        lambda *_: _copy_report(parent_window, log_text, on_copied),
    )

    view_button = Gtk.Button(label="View Log")
    view_button.add_css_class("suggested-action")
    view_button.connect("clicked", lambda *_: open_error_log(parent_window))

    button_row.append(copy_button)
    button_row.append(view_button)
    content.append(button_row)

    set_dialog_content(dialog, content)
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
    copy_button.connect("clicked", lambda *_: copy_text(window, text))
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


def copy_text(widget: Gtk.Widget, text: str) -> None:
    display = widget.get_display() if hasattr(widget, "get_display") else Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def _open_link(url: str) -> None:
    import webbrowser

    webbrowser.open_new_tab(url)
