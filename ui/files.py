"""Open local paths in the desktop file manager."""

from __future__ import annotations

import os

from gi.repository import Gio, GLib, Gtk

_OPEN_FOLDER_ERROR = "Couldn't open the folder: {message}"


def open_folder_in_file_manager(window: Gtk.Window, folder_path: str) -> None:
    """Reveal ``folder_path`` in the user's default file manager."""
    if not folder_path or not os.path.isdir(folder_path):
        return
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(folder_path))
    launcher.launch(window, None, _on_folder_launch_finished, window)


def _on_folder_launch_finished(
    launcher: Gtk.FileLauncher, result, window: Gtk.Window
) -> None:
    try:
        launcher.launch_finish(result)
    except GLib.Error as exc:
        toast = getattr(window, "_toast", None)
        if callable(toast):
            toast(_OPEN_FOLDER_ERROR.format(message=exc.message))
