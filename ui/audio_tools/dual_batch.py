"""Dual / batch input editor for the align and matchering tools.

GTK4 port of ``MainWindow.menu_batch_dual``: two side-by-side file lists whose
rows are paired by position (``zip``). Files can be added through a native file
dialog or dropped from the file manager, moved between sides, or cleared. On
confirm the editor reports the resulting list of ``(file_a, file_b)`` pairs back
to the caller, which persists them to ``DualBatch_inputPaths`` and the
``fileOneEntry`` / ``fileTwoEntry`` settings keys.
"""
import os
import typing
from typing import Callable, List, Sequence, Tuple

from gi.repository import Adw, Gdk, GLib, Gtk

from core.audio_formats import expand_audio_paths

from ..dialogs.utils import present_modal_dialog, set_form_dialog_content
from ..gtk_narrow import file_paths, root_window
from ..help_text import (
    DUAL_BATCH_CLEAR_HINT,
    DUAL_BATCH_MOVE_DOWN_HINT,
    DUAL_BATCH_MOVE_UP_HINT,
    DUAL_BATCH_REMOVE_HINT,
)
from ..hints import set_icon_button_a11y
from ..markup import set_row_subtitle, set_row_title
from ..spacing import set_inset
from ..widgets.file_dialogs import audio_open_dialog, is_dialog_dismissed


def pair_count_state(left_count: int, right_count: int) -> tuple[bool, str]:
    """Return whether paired inputs can be saved and their status copy."""
    if left_count == right_count:
        noun = "pair" if left_count == 1 else "pairs"
        return True, f"{left_count} {noun} ready"
    side = "left" if left_count > right_count else "right"
    difference = abs(left_count - right_count)
    noun = "file" if difference == 1 else "files"
    return False, f"Counts must match — {difference} unmatched {noun} on the {side}"


class _FileColumn(Gtk.Box):
    """One side of the dual editor: a titled, drop-enabled file list."""

    def __init__(self, title: str, on_changed: Callable[[], None]):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_hexpand(True)
        self._title = title
        self._on_changed = on_changed
        self.paths: List[str] = []

        self.header = Gtk.Label(label=title, xalign=0.0)
        self.header.add_css_class("heading")
        self.append(self.header)

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
        set_icon_button_a11y(self.up_button, DUAL_BATCH_MOVE_UP_HINT)
        self.up_button.connect("clicked", lambda *_a: self._move_selected(-1))
        self.down_button = Gtk.Button(icon_name="go-down-symbolic")
        set_icon_button_a11y(self.down_button, DUAL_BATCH_MOVE_DOWN_HINT)
        self.down_button.connect("clicked", lambda *_a: self._move_selected(1))
        self.remove_button = Gtk.Button(icon_name="list-remove-symbolic")
        set_icon_button_a11y(self.remove_button, DUAL_BATCH_REMOVE_HINT)
        self.remove_button.connect("clicked", self._on_remove_clicked)
        clear_button = Gtk.Button(icon_name="edit-clear-all-symbolic")
        set_icon_button_a11y(clear_button, DUAL_BATCH_CLEAR_HINT)
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
        count = len(self.paths)
        noun = "file" if count == 1 else "files"
        self.header.set_label(f"{self._title} — {count} {noun}")
        self._on_selection_changed(self.listbox)
        self._on_changed()

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
        self.down_button.set_sensitive(has_selection and index < len(self.paths) - 1)

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
        initial = os.path.dirname(self.paths[0]) if self.paths else None
        dialog = audio_open_dialog("Select Audio Files", initial=initial)
        dialog.open_multiple(root_window(self), None, self._on_open_finished)

    def _on_open_finished(self, dialog: Gtk.FileDialog, result: typing.Any) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error as exc:
            if not is_dialog_dismissed(exc):
                # DualBatchDialog may toast via parent if available later.
                pass
            return
        self.add_paths(file_paths(files))

    def _on_drop(self, _target: Gtk.DropTarget, value: typing.Any, _x: float, _y: float) -> bool:
        try:
            files = value.get_files()
        except AttributeError:
            return False
        raw = [f.get_path() for f in files if f.get_path()]
        paths = expand_audio_paths(raw)
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

        self._left = _FileColumn(labels[0], self._sync_pair_state)
        self._right = _FileColumn(labels[1], self._sync_pair_state)
        self._left.set_paths([p[0] for p in initial_pairs])
        self._right.set_paths([p[1] for p in initial_pairs])

        hint = Gtk.Label(
            label="Files are paired top-to-bottom. Add the same number of files to each side, then reorder rows so each pair lines up.",
            wrap=True,
            xalign=0.0,
        )
        hint.add_css_class("dim-label")
        set_inset(hint, start=12, end=12, bottom=6)

        self._pair_status = Gtk.Label(wrap=True, xalign=0.0)
        self._pair_status.add_css_class("dim-label")
        set_inset(self._pair_status, start=12, end=12)

        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        set_inset(columns, start=12, end=12, bottom=12)
        columns.append(self._left)
        columns.append(self._right)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, vexpand=True)
        set_inset(content, top=12)
        content.append(hint)
        content.append(self._pair_status)
        content.append(columns)

        self.dialog = Adw.Dialog()
        self.dialog.set_title("Dual / Batch Inputs")
        self.dialog.set_content_width(640)
        self.dialog.set_content_height(520)
        self._save_button = set_form_dialog_content(
            self.dialog, content, on_save=self._on_save
        )
        self._sync_pair_state()

    def _sync_pair_state(self) -> None:
        if not hasattr(self, "_pair_status") or not hasattr(self, "_save_button"):
            return
        valid, message = pair_count_state(
            len(self._left.paths), len(self._right.paths)
        )
        self._pair_status.set_label(message)
        self._pair_status.remove_css_class("error")
        if not valid:
            self._pair_status.add_css_class("error")
        self._save_button.set_sensitive(valid)

    def _on_save(self) -> None:
        valid, _message = pair_count_state(len(self._left.paths), len(self._right.paths))
        if not valid:
            self._sync_pair_state()
            return
        pairs = list(zip(self._left.paths, self._right.paths, strict=True))
        self._on_confirm(pairs)
        self.dialog.close()

    def present(self) -> None:
        present_modal_dialog(self.dialog, self.parent)
