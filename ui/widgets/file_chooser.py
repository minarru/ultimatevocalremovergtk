"""Input / output choosers with native GTK4 drag-and-drop.

Both rows accept files dragged from the
file manager via :class:`Gtk.DropTarget` (``Gdk.FileList``) and also open a
native :class:`Gtk.FileDialog`. Selections are reported through an ``on_changed``
callback so the window can persist them to the settings model.
"""

import os
from typing import AbstractSet, Callable, List, Optional, Sequence

from gi.repository import Adw, Gdk, GLib, Gtk

from core.audio_formats import expand_audio_paths

from ..help_text import (
    CLEAR_INPUT_FILES_HINT,
    REMOVE_FROM_LIST_HINT,
    SELECT_INPUT_FILES_HINT,
    SELECT_OUTPUT_FOLDER_HINT,
)
from ..hints import set_icon_button_a11y
from ..markup import set_row_subtitle, set_row_title
from ..shared_settings import (
    INPUT_FILES_WARN,
    export_path_blocked_reason,
    format_input_sanitize_toasts,
    input_paths_blocked_reason,
    sanitize_input_paths,
)
from .file_dialogs import (
    audio_open_dialog,
    folder_dialog,
    is_dialog_dismissed,
)

_AUDIO_HINT = "audio-x-generic-symbolic"


def merge_input_paths(existing: Sequence[str], added: Sequence[str]) -> List[str]:
    """Merge paths without duplicates while preserving first-seen order."""
    merged: List[str] = []
    seen = set()
    for path in (*existing, *added):
        if path and path not in seen:
            seen.add(path)
            merged.append(path)
    return merged


def expander_state(
    path_count: int, *, was_expanded: bool, preserve: bool
) -> tuple[bool, bool]:
    """Return ``(enable_expansion, expanded)`` for a ``path_count``-file selection.

    One file is fully summarized by the header, so expansion is disabled below
    two files. ``preserve`` keeps an already-open list open — set when the list
    is being edited in place (removing a file) rather than replaced wholesale.
    """
    if path_count <= 1:
        return False, False
    return True, (was_expanded if preserve else False)


def output_subtitle(path: str, reason: Optional[str]) -> tuple[str, bool]:
    """Return ``(subtitle, is_error)`` for the export-folder row."""
    if not path:
        return "No folder selected", False
    if not reason:
        return path, False
    if "writable" in reason.lower():
        return f"Folder not writable — {path}", True
    return f"Folder not found — {path}", True


# Re-export for call sites / tests that historically imported from here.
expand_dropped_paths = expand_audio_paths


class InputFilesRow(Adw.ExpanderRow):
    """Expandable row listing the selected input audio file(s) with drop support.

    The header keeps the summary subtitle and the browse / clear-all affordances;
    expanding reveals one child row per file (basename + full path) with a remove
    button, so individual files can be dropped without re-picking everything.
    """

    def __init__(
        self,
        on_changed: Callable[[], None],
        on_toast: Optional[Callable[[str], None]] = None,
        *,
        accept_any_getter: Optional[Callable[[], bool]] = None,
        initial_folder_getter: Optional[Callable[[], Optional[str]]] = None,
    ):
        super().__init__(title="Input")
        if hasattr(self, "set_use_markup"):
            self.set_use_markup(False)
        self._on_changed = on_changed
        self._on_toast = on_toast
        self._accept_any_getter = accept_any_getter
        self._initial_folder_getter = initial_folder_getter
        self.paths: List[str] = []
        self._file_rows: List[Gtk.Widget] = []

        icon = Gtk.Image(icon_name=_AUDIO_HINT)
        self.add_prefix(icon)

        self._clear_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        set_icon_button_a11y(self._clear_button, CLEAR_INPUT_FILES_HINT)
        self._clear_button.add_css_class("flat")
        self._clear_button.connect("clicked", self._on_clear_clicked)
        self.add_suffix(self._clear_button)

        button = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER)
        set_icon_button_a11y(button, f"Add audio files. {SELECT_INPUT_FILES_HINT}")
        button.add_css_class("flat")
        button.connect("clicked", self._on_clicked)
        self.add_suffix(button)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", self._on_drop_enter)
        drop.connect("leave", self._on_drop_leave)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        self._refresh()

    def _accept_any(self) -> bool:
        if self._accept_any_getter is None:
            return False
        try:
            return bool(self._accept_any_getter())
        except Exception:  # noqa: BLE001
            return False

    def _initial_folder(self) -> Optional[str]:
        if self.paths:
            return os.path.dirname(self.paths[0]) or None
        if self._initial_folder_getter is not None:
            try:
                return self._initial_folder_getter()
            except Exception:  # noqa: BLE001
                return None
        return None

    def _on_drop_enter(self, _target: Gtk.DropTarget, _x: float, _y: float) -> Gdk.DragAction:
        self.add_css_class("drop-highlight")
        return Gdk.DragAction.COPY

    def _on_drop_leave(self, _target: Gtk.DropTarget) -> None:
        self.remove_css_class("drop-highlight")

    def set_paths(
        self,
        paths: Sequence[str],
        notify: bool = True,
        *,
        preserve_expansion: bool = False,
    ) -> None:
        cleaned, result = sanitize_input_paths(paths)
        self.paths = cleaned
        self._refresh(preserve_expansion=preserve_expansion)
        if notify:
            from core.debug_log import debug

            debug("ui", f"inputs count={len(self.paths)}")
            for message in format_input_sanitize_toasts(
                result,
                include_missing=result.removed_missing > 0,
            ):
                self._emit_toast(message)
            self._on_changed()

    def blocked_reason(
        self,
        *,
        unreadable_paths: Optional[AbstractSet[str]] = None,
    ) -> Optional[str]:
        return input_paths_blocked_reason(
            self.paths, unreadable_paths=unreadable_paths
        )

    def _emit_toast(self, message: str) -> None:
        if self._on_toast is not None:
            self._on_toast(message)

    def _refresh(self, *, preserve_expansion: bool = False) -> None:
        was_expanded = self.get_expanded()
        self._refresh_subtitle()
        self._rebuild_file_rows()
        self._clear_button.set_sensitive(bool(self.paths))
        enable, expanded = expander_state(
            len(self.paths), was_expanded=was_expanded, preserve=preserve_expansion
        )
        self.set_enable_expansion(enable)
        self.set_expanded(expanded)

    def _refresh_subtitle(self) -> None:
        if not self.paths:
            self.set_subtitle("No files selected")
            self.set_tooltip_text(None)
        elif len(self.paths) == 1:
            path = self.paths[0]
            set_row_subtitle(self, path)
            self.set_tooltip_text(path)
        else:
            extra = len(self.paths) - 1
            subtitle = f"{os.path.basename(self.paths[0])} (and {extra} more)"
            if len(self.paths) >= INPUT_FILES_WARN:
                subtitle = f"{subtitle} (large batch)"
            set_row_subtitle(self, subtitle)
            self.set_tooltip_text(None)

    def _rebuild_file_rows(self) -> None:
        for row in self._file_rows:
            self.remove(row)
        self._file_rows = []
        # A single selection already shows the path on the expander; skip the
        # duplicate child row that previously stacked the same path twice.
        if len(self.paths) <= 1:
            return
        for path in self.paths:
            row = Adw.ActionRow()
            set_row_title(row, os.path.basename(path))
            set_row_subtitle(row, path)
            row.set_tooltip_text(path)
            remove = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER)
            set_icon_button_a11y(remove, f"{REMOVE_FROM_LIST_HINT}: {os.path.basename(path)}")
            remove.add_css_class("flat")
            remove.connect("clicked", self._on_remove_clicked, path)
            row.add_suffix(remove)
            self.add_row(row)
            self._file_rows.append(row)

    def _on_remove_clicked(self, _button: Gtk.Button, path: str) -> None:
        self.set_paths(
            [p for p in self.paths if p != path], preserve_expansion=True
        )

    def _on_clear_clicked(self, _button: Gtk.Button) -> None:
        if self.paths:
            self.set_paths([])

    def _on_clicked(self, _button: Gtk.Button) -> None:
        dialog = audio_open_dialog(
            "Select Audio Files",
            accept_any=self._accept_any(),
            initial=self._initial_folder(),
        )
        dialog.open_multiple(self.get_root(), None, self._on_open_finished)

    def _on_open_finished(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error as exc:
            if not is_dialog_dismissed(exc):
                self._emit_toast(f"Couldn't open files: {exc.message}")
            return
        paths = [files.get_item(i).get_path() for i in range(files.get_n_items())]
        if paths:
            self.set_paths(merge_input_paths(self.paths, paths))

    def _on_drop(self, _target: Gtk.DropTarget, value, _x: float, _y: float) -> bool:
        self.remove_css_class("drop-highlight")
        try:
            files = value.get_files()
        except AttributeError:
            return False
        raw = [f.get_path() for f in files if f.get_path()]
        paths = expand_dropped_paths(raw, accept_any=self._accept_any())
        if not paths:
            self._emit_toast("No audio files found in the drop")
            return False
        self.set_paths(merge_input_paths(self.paths, paths))
        return True


class OutputFolderRow(Adw.ActionRow):
    """Row holding the export directory with drop support."""

    def __init__(self, on_changed: Callable[[], None], on_toast: Optional[Callable[[str], None]] = None):
        super().__init__(title="Output folder", icon_name="folder-symbolic")
        if hasattr(self, "set_use_markup"):
            self.set_use_markup(False)
        self._on_changed = on_changed
        self._on_toast = on_toast
        self.path: str = ""

        button = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER)
        set_icon_button_a11y(button, SELECT_OUTPUT_FOLDER_HINT)
        button.add_css_class("flat")
        button.connect("clicked", self._on_clicked)
        self.add_suffix(button)
        self.set_activatable_widget(button)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", self._on_drop_enter)
        drop.connect("leave", self._on_drop_leave)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        self._refresh_subtitle()

    def _emit_toast(self, message: str) -> None:
        if self._on_toast is not None:
            self._on_toast(message)

    def _on_drop_enter(self, _target: Gtk.DropTarget, _x: float, _y: float) -> Gdk.DragAction:
        self.add_css_class("drop-highlight")
        return Gdk.DragAction.COPY

    def _on_drop_leave(self, _target: Gtk.DropTarget) -> None:
        self.remove_css_class("drop-highlight")

    def set_path(self, path: str, notify: bool = True) -> None:
        self.path = path or ""
        self._refresh_subtitle()
        if notify:
            self._on_changed()

    def blocked_reason(self) -> Optional[str]:
        return export_path_blocked_reason(self.path)

    def is_valid(self) -> bool:
        return self.blocked_reason() is None

    def _refresh_subtitle(self) -> None:
        subtitle, is_error = output_subtitle(
            self.path, export_path_blocked_reason(self.path) if self.path else None
        )
        set_row_subtitle(self, subtitle)
        # libadwaita's .error class tints the row so a stale or read-only export
        # folder reads as a failure instead of an ordinary path.
        if is_error:
            self.add_css_class("error")
        else:
            self.remove_css_class("error")

    def _on_clicked(self, _button: Gtk.Button) -> None:
        dialog = folder_dialog("Select Output Folder", initial=self.path or None)
        dialog.select_folder(self.get_root(), None, self._on_select_finished)

    def _on_select_finished(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error as exc:
            if not is_dialog_dismissed(exc):
                self._emit_toast(f"Couldn't select folder: {exc.message}")
            return
        if folder and folder.get_path():
            self.set_path(folder.get_path())

    def _on_drop(self, _target: Gtk.DropTarget, value, _x: float, _y: float) -> bool:
        self.remove_css_class("drop-highlight")
        try:
            files = value.get_files()
        except AttributeError:
            return False
        for item in files:
            path = item.get_path()
            if not path:
                continue
            self.set_path(path if os.path.isdir(path) else os.path.dirname(path))
            return True
        return False
