"""Dual / batch input editor for the align and matchering tools.

GTK4 port of ``MainWindow.menu_batch_dual``: two side-by-side file lists whose
rows are paired by position (``zip``). Files can be added through a native file
dialog or dropped from the file manager, moved between sides, or cleared. On
confirm the editor reports the resulting list of ``(file_a, file_b)`` pairs back
to the caller, which persists them to ``DualBatch_inputPaths`` and the
``fileOneEntry`` / ``fileTwoEntry`` settings keys.
"""

import os
from typing import Callable, List, Sequence, Tuple

from gi.repository import Adw, Gdk, GLib, Gtk

from ..dialogs.utils import present_modal_dialog, set_form_dialog_content
from ..hints import set_tooltip
from ..markup import set_row_subtitle, set_row_title


class _FileColumn(Gtk.Box):
    """One side of the dual editor: a titled, drop-enabled file list."""

    def __init__(self, title: str):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_hexpand(True)
        self.paths: List[str] = []

        header = Gtk.Label(label=title, xalign=0.0)
        header.add_css_class("heading")
        self.append(header)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.connect("selected-rows-changed", self._on_selection_changed)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(300)
        scroller.set_min_content_width(240)
        scroller.set_child(self.listbox)
        self.append(scroller)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_button = Gtk.Button(label="Add files", hexpand=True)
        add_button.connect("clicked", self._on_add_clicked)
        self.up_button = Gtk.Button(icon_name="go-up-symbolic")
        set_tooltip(self.up_button, "Move selected up")
        self.up_button.connect("clicked", lambda *_a: self._move_selected(-1))
        self.down_button = Gtk.Button(icon_name="go-down-symbolic")
        set_tooltip(self.down_button, "Move selected down")
        self.down_button.connect("clicked", lambda *_a: self._move_selected(1))
        self.remove_button = Gtk.Button(icon_name="list-remove-symbolic")
        set_tooltip(self.remove_button, "Remove selected")
        self.remove_button.connect("clicked", self._on_remove_clicked)
        clear_button = Gtk.Button(icon_name="edit-clear-all-symbolic")
        set_tooltip(clear_button, "Clear all")
        clear_button.connect("clicked", lambda *_a: self.clear())
        button_box.append(add_button)
        button_box.append(self.up_button)
        button_box.append(self.down_button)
        button_box.append(self.remove_button)
        button_box.append(clear_button)
        self.append(button_box)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self._on_drop)
        self.listbox.add_controller(drop)

        self._on_selection_changed(self.listbox)

    # -- Model -----------------------------------------------------------------

    def set_paths(self, paths: Sequence[str]) -> None:
        self.paths = [p for p in paths if p]
        self._refresh()

    def add_paths(self, paths: Sequence[str]) -> None:
        for path in paths:
            if path and path not in self.paths and os.path.isfile(path):
                self.paths.append(path)
        self._refresh()

    def clear(self) -> None:
        self.paths = []
        self._refresh()

    def _refresh(self, *, select_index: int | None = None) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.listbox.remove(child)
            child = nxt
        for index, path in enumerate(self.paths, start=1):
            row = Adw.ActionRow()
            row.set_activatable(False)
            set_row_title(row, f"{index}: {os.path.basename(path)}")
            set_row_subtitle(row, path)
            self.listbox.append(row)
        if select_index is not None and 0 <= select_index < len(self.paths):
            row = self.listbox.get_row_at_index(select_index)
            if row is not None:
                self.listbox.select_row(row)
        self._on_selection_changed(self.listbox)

    def _selected_index(self) -> int | None:
        row = self.listbox.get_selected_row()
        if row is None:
            return None
        index = row.get_index()
        return index if 0 <= index < len(self.paths) else None

    def _on_selection_changed(self, _listbox: Gtk.ListBox) -> None:
        index = self._selected_index()
        has_selection = index is not None
        self.remove_button.set_sensitive(has_selection)
        self.up_button.set_sensitive(has_selection and index > 0)
        self.down_button.set_sensitive(has_selection and index is not None and index < len(self.paths) - 1)

    def _move_selected(self, delta: int) -> None:
        index = self._selected_index()
        if index is None:
            return
        new_index = index + delta
        if not 0 <= new_index < len(self.paths):
            return
        path = self.paths.pop(index)
        self.paths.insert(new_index, path)
        self._refresh(select_index=new_index)

    def _on_remove_clicked(self, _button: Gtk.Button) -> None:
        index = self._selected_index()
        if index is None:
            return
        del self.paths[index]
        self._refresh()

    # -- Input -----------------------------------------------------------------

    def _on_add_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Select Audio Files")
        dialog.open_multiple(self.get_root(), None, self._on_open_finished)

    def _on_open_finished(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        paths = [files.get_item(i).get_path() for i in range(files.get_n_items())]
        self.add_paths([p for p in paths if p])

    def _on_drop(self, _target: Gtk.DropTarget, value, _x: float, _y: float) -> bool:
        try:
            files = value.get_files()
        except AttributeError:
            return False
        paths = [f.get_path() for f in files if f.get_path() and os.path.isfile(f.get_path())]
        if not paths:
            return False
        self.add_paths(paths)
        return True


class DualBatchDialog:
    """Modal editor producing ``(file_a, file_b)`` pairs for align/matchering."""

    def __init__(
        self,
        parent: Gtk.Window,
        labels: Tuple[str, str],
        initial_pairs: Sequence[Tuple[str, str]],
        on_confirm: Callable[[List[Tuple[str, str]]], None],
    ):
        self.parent = parent
        self._on_confirm = on_confirm

        self._left = _FileColumn(labels[0])
        self._right = _FileColumn(labels[1])
        self._left.set_paths([p[0] for p in initial_pairs])
        self._right.set_paths([p[1] for p in initial_pairs])

        hint = Gtk.Label(
            label="Files are paired top-to-bottom. Add the same number of files to each side, then reorder rows so each pair lines up.",
            wrap=True,
            xalign=0.0,
        )
        hint.add_css_class("dim-label")
        hint.set_margin_start(12)
        hint.set_margin_end(12)
        hint.set_margin_bottom(6)

        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        columns.set_margin_start(12)
        columns.set_margin_end(12)
        columns.set_margin_bottom(12)
        columns.append(self._left)
        columns.append(self._right)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, vexpand=True)
        content.set_margin_top(12)
        content.append(hint)
        content.append(columns)

        self.dialog = Adw.Dialog()
        self.dialog.set_title("Dual / Batch Inputs")
        self.dialog.set_content_width(640)
        self.dialog.set_content_height(520)
        set_form_dialog_content(self.dialog, content, on_save=self._on_save)

    def _on_save(self) -> None:
        pairs = list(zip(self._left.paths, self._right.paths))
        self._on_confirm(pairs)
        self.dialog.close()

    def present(self) -> None:
        present_modal_dialog(self.dialog, self.parent)
