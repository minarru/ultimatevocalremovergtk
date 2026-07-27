"""Open local paths and URIs via GTK launchers (portal-friendly)."""

from __future__ import annotations

import os
from typing import Callable, Optional

from gi.repository import Gio, GLib, Gtk

_OPEN_FOLDER_ERROR = "Couldn't open the folder: {message}"
_OPEN_URI_ERROR = "Couldn't open the link: {message}"

ErrorCallback = Callable[[str], None]


def open_folder_in_file_manager(
    window: Gtk.Window,
    folder_path: str,
    *,
    on_error: Optional[ErrorCallback] = None,
) -> None:
    """Reveal ``folder_path`` in the user's default file manager."""
    if not folder_path or not os.path.isdir(folder_path):
        return
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(folder_path))
    launcher.launch(
        window,
        None,
        _on_folder_launch_finished,
        {"window": window, "on_error": on_error},
    )


def open_uri_in_browser(
    window: Gtk.Window,
    uri: str,
    *,
    on_error: Optional[ErrorCallback] = None,
) -> None:
    """Open ``uri`` with the desktop's default handler (portal-aware)."""
    if not uri:
        return
    launcher = Gtk.UriLauncher.new(uri)
    launcher.launch(
        window,
        None,
        _on_uri_launch_finished,
        {"window": window, "on_error": on_error},
    )


def _report_error(
    window: Gtk.Window,
    on_error: Optional[ErrorCallback],
    message: str,
) -> None:
    if callable(on_error):
        on_error(message)
        return
    toast = getattr(window, "toast", None)
    if callable(toast):
        toast(message)


def _on_folder_launch_finished(launcher: Gtk.FileLauncher, result, data) -> None:
    window = data["window"]
    on_error = data.get("on_error")
    try:
        launcher.launch_finish(result)
    except GLib.Error as exc:
        _report_error(
            window,
            on_error,
            _OPEN_FOLDER_ERROR.format(message=exc.message),
        )


def _on_uri_launch_finished(launcher: Gtk.UriLauncher, result, data) -> None:
    window = data["window"]
    on_error = data.get("on_error")
    try:
        launcher.launch_finish(result)
    except GLib.Error as exc:
        _report_error(
            window,
            on_error,
            _OPEN_URI_ERROR.format(message=exc.message),
        )
