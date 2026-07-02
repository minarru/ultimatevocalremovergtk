"""Input / output choosers with native GTK4 drag-and-drop.

Both rows accept files dragged from the
file manager via :class:`Gtk.DropTarget` (``Gdk.FileList``) and also open a
native :class:`Gtk.FileDialog`. Selections are reported through an ``on_changed``
callback so the window can persist them to the settings model.
"""

import os
from typing import Callable, List, Sequence

from gi.repository import Adw, Gdk, GLib, Gtk

from ..hints import set_tooltip
from ..markup import set_row_subtitle, set_row_title

_AUDIO_HINT = "audio-x-generic-symbolic"


class InputFilesRow(Adw.ExpanderRow):
    """Expandable row listing the selected input audio file(s) with drop support.

    The header keeps the summary subtitle and the browse / clear-all affordances;
    expanding reveals one child row per file (basename + full path) with a remove
    button, so individual files can be dropped without re-picking everything.
    """

    def __init__(self, on_changed: Callable[[], None]):
        super().__init__(title="Input")
        if hasattr(self, "set_use_markup"):
            self.set_use_markup(False)
        self._on_changed = on_changed
        self.paths: List[str] = []
        self._file_rows: List[Gtk.Widget] = []

        icon = Gtk.Image(icon_name=_AUDIO_HINT)
        self.add_prefix(icon)

        self._clear_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        set_tooltip(self._clear_button, "Clear all input files")
        self._clear_button.add_css_class("flat")
        self._clear_button.connect("clicked", self._on_clear_clicked)
        self.add_suffix(self._clear_button)

        button = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER)
        set_tooltip(button, "Select input audio files")
        button.add_css_class("flat")
        button.connect("clicked", self._on_clicked)
        self.add_suffix(button)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", self._on_drop_enter)
        drop.connect("leave", self._on_drop_leave)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        self._refresh()

    def _on_drop_enter(self, _target: Gtk.DropTarget, _x: float, _y: float) -> Gdk.DragAction:
        self.add_css_class("drop-highlight")
        return Gdk.DragAction.COPY

    def _on_drop_leave(self, _target: Gtk.DropTarget) -> None:
        self.remove_css_class("drop-highlight")

    def set_paths(self, paths: Sequence[str], notify: bool = True) -> None:
        self.paths = [p for p in paths if p]
        self._refresh()
        if notify:
            self._on_changed()

    def _refresh(self) -> None:
        self._refresh_subtitle()
        self._rebuild_file_rows()
        self._clear_button.set_sensitive(bool(self.paths))
        self.set_enable_expansion(bool(self.paths))

    def _refresh_subtitle(self) -> None:
        if not self.paths:
            self.set_subtitle("No files selected")
        elif len(self.paths) == 1:
            set_row_subtitle(self, self.paths[0])
        else:
            extra = len(self.paths) - 1
            set_row_subtitle(self, f"{os.path.basename(self.paths[0])} (and {extra} more)")

    def _rebuild_file_rows(self) -> None:
        for row in self._file_rows:
            self.remove(row)
        self._file_rows = []
        for path in self.paths:
            row = Adw.ActionRow()
            set_row_title(row, os.path.basename(path))
            set_row_subtitle(row, path)
            row.set_tooltip_text(path)
            remove = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.CENTER)
            set_tooltip(remove, "Remove from list")
            remove.add_css_class("flat")
            remove.connect("clicked", self._on_remove_clicked, path)
            row.add_suffix(remove)
            self.add_row(row)
            self._file_rows.append(row)

    def _on_remove_clicked(self, _button: Gtk.Button, path: str) -> None:
        self.set_paths([p for p in self.paths if p != path])

    def _on_clear_clicked(self, _button: Gtk.Button) -> None:
        if self.paths:
            self.set_paths([])

    def _on_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Select Audio Files")
        dialog.open_multiple(self.get_root(), None, self._on_open_finished)

    def _on_open_finished(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        paths = [files.get_item(i).get_path() for i in range(files.get_n_items())]
        if paths:
            self.set_paths(paths)

    def _on_drop(self, _target: Gtk.DropTarget, value, _x: float, _y: float) -> bool:
        self.remove_css_class("drop-highlight")
        try:
            files = value.get_files()
        except AttributeError:
            return False
        paths = [f.get_path() for f in files if f.get_path() and os.path.isfile(f.get_path())]
        if not paths:
            return False
        self.set_paths(paths)
        return True


class OutputFolderRow(Adw.ActionRow):
    """Row holding the export directory with drop support."""

    def __init__(self, on_changed: Callable[[], None]):
        super().__init__(title="Output folder", icon_name="folder-symbolic")
        if hasattr(self, "set_use_markup"):
            self.set_use_markup(False)
        self._on_changed = on_changed
        self.path: str = ""

        button = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER)
        set_tooltip(button, "Select output folder")
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

    def _refresh_subtitle(self) -> None:
        if self.path:
            set_row_subtitle(self, self.path)
        else:
            self.set_subtitle("No folder selected")

    def _on_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Select Output Folder")
        dialog.select_folder(self.get_root(), None, self._on_select_finished)

    def _on_select_finished(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
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
