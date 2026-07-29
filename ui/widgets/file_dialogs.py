"""Shared ``Gtk.FileDialog`` construction with filters and initial folders."""

from __future__ import annotations

import os
from typing import Optional

from gi.repository import Gio, GLib, Gtk

from core.audio_formats import AUDIO_EXTENSIONS

_AUDIO_FILTER_NAME = "Audio files"
_ALL_FILTER_NAME = "All files"


def audio_file_filters(*, accept_any: bool = False) -> tuple[Gio.ListStore, Gtk.FileFilter]:
    """Return ``(filters, default_filter)`` for an audio open dialog.

    When ``accept_any`` is False the audio filter is the default; when True the
    "All files" filter is.
    """
    audio = Gtk.FileFilter(name=_AUDIO_FILTER_NAME)
    for ext in AUDIO_EXTENSIONS:
        audio.add_suffix(ext.lstrip("."))
    all_files = Gtk.FileFilter(name=_ALL_FILTER_NAME)
    all_files.add_pattern("*")

    filters = Gio.ListStore.new(Gtk.FileFilter)
    if accept_any:
        filters.append(all_files)
        filters.append(audio)
        default = all_files
    else:
        filters.append(audio)
        filters.append(all_files)
        default = audio
    return filters, default


def resolve_existing_folder(path: Optional[str]) -> Optional[str]:
    """Return a readable directory near ``path``, walking parents if needed.

    Used to seed file dialogs. A missing remembered path must not leave the
    initial folder unset: the XDG portal then reopens its own last folder,
    which can be the same deleted path and surfaces a Nautilus error.
    """
    candidates: list[str] = []
    if path:
        current = os.path.expanduser(path)
        if current and (os.path.isfile(current) or not os.path.isdir(current)):
            current = os.path.dirname(current)
        while current:
            candidates.append(current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent

    home = os.path.expanduser("~")
    if home and home not in candidates:
        candidates.append(home)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            if os.path.isdir(candidate) and os.access(candidate, os.R_OK | os.X_OK):
                return candidate
        except OSError:
            continue
    return None


def _initial_folder(path: Optional[str]) -> Optional[Gio.File]:
    resolved = resolve_existing_folder(path)
    if not resolved:
        return None
    return Gio.File.new_for_path(resolved)


def audio_open_dialog(
    title: str,
    *,
    accept_any: bool = False,
    initial: Optional[str] = None,
) -> Gtk.FileDialog:
    """Build a multi-capable open dialog defaulting to audio filters."""
    dialog = Gtk.FileDialog(title=title)
    filters, default = audio_file_filters(accept_any=accept_any)
    dialog.set_filters(filters)
    dialog.set_default_filter(default)
    folder = _initial_folder(initial)
    if folder is not None:
        dialog.set_initial_folder(folder)
    return dialog


def folder_dialog(title: str, *, initial: Optional[str] = None) -> Gtk.FileDialog:
    """Build a folder-selection dialog seeded at ``initial`` when possible."""
    dialog = Gtk.FileDialog(title=title)
    folder = _initial_folder(initial)
    if folder is not None:
        dialog.set_initial_folder(folder)
    return dialog


def is_dialog_dismissed(error: GLib.Error) -> bool:
    """Return True when ``error`` is a user cancel / dismiss of a file dialog."""
    # Gtk.DialogError.DISMISSED / Gio.IOErrorEnum.CANCELLED depending on GTK.
    code = getattr(error, "code", None)
    domain = getattr(error, "domain", None) or ""
    message = (getattr(error, "message", None) or "").lower()
    if "dismiss" in message or "cancel" in message:
        return True
    # GTK4 FileDialog uses gtk-dialog-error-quark with code 2 for dismissed.
    if "dialog-error" in str(domain) and code in (1, 2):
        return True
    if code == getattr(getattr(Gio, "IOErrorEnum", object), "CANCELLED", None):
        return True
    return False
