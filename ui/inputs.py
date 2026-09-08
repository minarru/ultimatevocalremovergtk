"""Verify Inputs dialog (port of ``menu_view_inputs``).

Lists the currently-selected input files (the ``input_paths`` setting), shows the
total count, lets the user add / remove / clear inputs, and verifies each file —
reporting duration / format / validity. Failed paths are tracked ephemerally on
:class:`~ui.context.AppContext` so Start stays blocked until they are removed.

Verification mirrors UVR's ``verify_audio`` but runs on a worker thread and
marshals results back via ``GLib.idle_add``; the audio backend is imported lazily
so constructing the dialog stays ``torch``-free.

Entry point: :func:`open_view_inputs` (wire to ``win.view_inputs``).
"""

import os
import threading
import typing
from dataclasses import dataclass
from pathlib import Path

from gi.repository import Adw, Gdk, GLib, Gtk

from bundled.constants import VERIFY_INPUTS_TEXT
from core.audio_probe import probe_audio

from .dialogs.utils import present_modal_dialog
from .dispatch import idle_on_main
from .errorlog import log_error, set_error_log
from .gtk_narrow import root_window
from .help_text import (
    ADD_INPUT_FILES_HINT,
    CLEAR_ALL_INPUTS_HINT,
    REMOVE_INPUT_HINT,
)
from .hints import set_icon_button_a11y
from .lifetime import UiLifetime
from .markup import set_row_subtitle, set_row_title
from .shared_settings import (
    format_input_sanitize_toasts,
    remove_unreadable_from_paths,
    sanitize_input_paths,
)
from .template import load_builder, object_from_builder
from .widgets.file_chooser import merge_input_paths
from .widgets.file_dialogs import audio_open_dialog, is_dialog_dismissed

_STATUS_OK = "success-small-symbolic"
_STATUS_BAD = "warning-outline-symbolic"
_SEARCH_THRESHOLD = 8


@dataclass(frozen=True)
class _InputSnapshot:
    paths: tuple[str, ...]
    status: dict[str, tuple[bool, str]]
    unreadable: frozenset[str]


def _folder_label(path: str) -> str:
    folder = Path(path).parent
    if len(folder.parts) > (3 if folder.is_absolute() else 2):
        return str(Path("…", *folder.parts[-2:]))
    return str(folder)


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}:{secs:02d}"


def inspect_audio(path: str):
    """Return ``(is_valid, info)`` for ``path`` (duration / format / validity).

    Tries ``soundfile`` (rich metadata), then stdlib ``wave`` for WAV, then
    ``librosa`` (UVR's own verification path). All imports are lazy so the dialog
    can be constructed without the ML/audio stack present.
    """
    result = probe_audio(path)
    if not result.readable:
        if result.error and result.error != "file_not_found":
            log_error("Verify Inputs", RuntimeError(result.error), context=f"path={path!r}")
        return (
            False,
            "file not found" if result.error == "file_not_found" else "Could not read this file",
        )
    if result.format and result.duration_seconds is not None:
        return True, (
            f"{_fmt_duration(result.duration_seconds)} \u2022 {result.format} \u2022 "
            f"{result.channels}ch \u2022 {result.sample_rate} Hz"
        )
    return True, "readable"


class ViewInputs:
    def __init__(
        self,
        parent: Gtk.Window | None,
        app_context: typing.Any,
        on_inputs_changed: typing.Any = None,
        on_verification_changed: typing.Callable[[], None] | None = None,
    ):
        self.parent = parent
        self.context = app_context
        self.settings = app_context.settings
        self._on_inputs_changed = on_inputs_changed
        self._on_verification_changed = on_verification_changed
        self._verification_generation: int | None = None
        self.paths = list(self.settings.process.input_paths or [])
        self._rows = {}
        self._status_icons: dict[str, Gtk.Image] = {}
        self._remove_buttons: dict[str, Gtk.Button] = {}
        self._status = {}  # path -> (is_valid, info) after verify
        self._verifying = False
        self._verify_total = 0
        self._verify_stop = threading.Event()
        self._lifetime = UiLifetime()
        self._undo_snapshot: _InputSnapshot | None = None
        self._undo_toast: Adw.Toast | None = None

        builder = load_builder("verify-inputs")
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        self.dialog.connect("closed", self._on_closed)

        self.add_button = object_from_builder(builder, "add_button", Gtk.Button)
        set_icon_button_a11y(self.add_button, ADD_INPUT_FILES_HINT)
        self.add_button.connect("clicked", self._on_add)
        self.clear_button = object_from_builder(builder, "clear_button", Gtk.Button)
        set_icon_button_a11y(self.clear_button, CLEAR_ALL_INPUTS_HINT)
        self.clear_button.connect("clicked", self._on_clear)
        self.remove_unreadable_button = object_from_builder(
            builder, "remove_unreadable_button", Gtk.Button
        )
        self.remove_unreadable_button.connect("clicked", self._on_remove_unreadable)
        self.verify_button = object_from_builder(builder, "verify_button", Gtk.Button)
        self.verify_button.set_label(f"_{VERIFY_INPUTS_TEXT}")
        self.verify_button.connect("clicked", self._on_verify)
        self.toast_overlay = object_from_builder(builder, "toast_overlay", Adw.ToastOverlay)
        self._input_scroll = object_from_builder(builder, "input_scroll", Gtk.ScrolledWindow)
        self._empty_state = object_from_builder(builder, "empty_state", Adw.StatusPage)
        # StatusPage's internal clamp adjusts typography when first allocated.
        self._empty_state.connect("map", self._on_empty_state_mapped)
        self._search = object_from_builder(builder, "input_search", Gtk.SearchEntry)
        self._search.connect("search-changed", self._filter_rows)
        self._header_box = object_from_builder(builder, "header_box", Gtk.Box)
        self._summary = object_from_builder(builder, "files_summary", Gtk.Label)
        self._files_list = object_from_builder(builder, "files_list", Gtk.ListBox)
        self._summary.set_label(self._total_text())

        # Seed status from any prior verify still tracked on the context.
        for path in self.context.unreadable_input_paths:
            if path in self.paths:
                self._status[path] = (False, "unreadable")

        self._rebuild_list()
        self._sync_actions()

    def present(self) -> None:
        self._resize_to_content()
        present_modal_dialog(self.dialog, self.parent)

    def _resize_to_content(self) -> None:
        if self._lifetime.disposed:
            return
        parent_height = self.parent.get_height() if self.parent is not None else 0
        if parent_height <= 0 and self.parent is not None:
            parent_height = self.parent.get_default_size()[1]
        if parent_height <= 0:
            parent_height = 700
        self._input_scroll.set_max_content_height(min(460, max(120, parent_height - 240)))
        # Adw.Dialog resolves -1 once, so remeasure after content changes while
        # retaining the requested desktop width.
        self.dialog.set_content_height(-1)

    def _on_empty_state_mapped(self, widget: Gtk.Widget) -> None:
        # An idle on map can precede the first allocation and capture the old
        # natural height, before the status page's clamp updates its labels.
        def after_allocation(widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
            if self._lifetime.disposed:
                return GLib.SOURCE_REMOVE
            if widget.get_width() <= 0:
                return GLib.SOURCE_CONTINUE
            self._resize_to_content()
            return GLib.SOURCE_REMOVE

        widget.add_tick_callback(after_allocation)

    # -- List management --------------------------------------------------------

    def _failed_paths(self) -> list[str]:
        return [p for p, (ok, _info) in self._status.items() if not ok and p in self.paths]

    def _total_text(self) -> str:
        n = len(self.paths)
        base = f"{n} file" if n == 1 else f"{n} files"
        query = self._search.get_text().strip().casefold()
        if query:
            matches = sum(query in path.casefold() for path in self.paths)
            base = f"{matches} of {n} files"
        checked = sum(path in self._status for path in self.paths)
        if self._verifying:
            return f"{base} · Verifying {checked}/{n}"
        failed = len(self._failed_paths())
        if failed:
            remaining = f" · {n - checked} not verified" if checked < n else ""
            return f"{base} · {failed} unreadable{remaining}"
        if n and checked == n:
            return f"{base} · All readable"
        if checked:
            return f"{base} · {checked}/{n} verified"
        return f"{base} · Not verified" if n else base

    def _filter_rows(self, *_args: object) -> None:
        if self._lifetime.disposed:
            return
        if not self.paths:
            self._search.set_text("")
        query = self._search.get_text().strip().casefold()
        self._search.set_visible(len(self.paths) >= _SEARCH_THRESHOLD or bool(query))
        matches = 0
        for path, row in self._rows.items():
            visible = query in path.casefold()
            row.set_visible(visible)
            matches += visible
        self._header_box.set_visible(bool(self.paths))
        self._files_list.set_visible(bool(matches))
        self._summary.set_label(self._total_text())
        self._empty_state.set_visible(not matches)
        no_matches = bool(self.paths) and not matches
        self._empty_state.set_title("No matching files" if no_matches else "No input files")
        self._empty_state.set_description(
            "Try another filename or folder" if no_matches else "Add audio files to get started"
        )
        self._empty_state.set_icon_name(
            "system-search-symbolic" if no_matches else "audio-x-generic-symbolic"
        )
        self._resize_to_content()

    def _rebuild_list(self) -> None:
        for row in self._rows.values():
            self._files_list.remove(row)
        self._rows = {}
        self._status_icons.clear()
        self._remove_buttons.clear()

        for path in self.paths:
            builder = load_builder("verify-inputs-row")
            row = object_from_builder(builder, "row", Adw.ActionRow)
            set_row_title(row, os.path.basename(path))
            row.set_tooltip_text(path)
            remove_button = object_from_builder(builder, "remove_button", Gtk.Button)
            set_icon_button_a11y(remove_button, REMOVE_INPUT_HINT)
            remove_button.connect("clicked", lambda _b, p=path: self._remove_path(p))
            self._files_list.append(row)
            self._rows[path] = row
            self._status_icons[path] = object_from_builder(builder, "status_icon", Gtk.Image)
            self._remove_buttons[path] = remove_button
            remove_button.set_sensitive(not self._verifying)
            self._update_row_status(path)
        self._filter_rows()

    def _update_row_status(self, path: str) -> None:
        row = self._rows.get(path)
        icon = self._status_icons.get(path)
        if row is None or icon is None:
            return
        status = self._status.get(path)
        if status is None:
            icon_name, style, label = "audio-x-generic-symbolic", "dim-label", "Not verified"
            subtitle = _folder_label(path)
        else:
            valid, info = status
            icon_name = _STATUS_OK if valid else _STATUS_BAD
            style, label = ("success", "Readable") if valid else ("warning", "Unreadable")
            subtitle = f"{_folder_label(path)}\n{info}"
        icon.set_from_icon_name(icon_name)
        for old_style in ("dim-label", "success", "warning"):
            icon.remove_css_class(old_style)
        icon.add_css_class(style)
        icon.set_tooltip_text(label)
        icon.update_property([Gtk.AccessibleProperty.LABEL], [label])
        set_row_subtitle(row, subtitle)

    def _sync_actions(self) -> None:
        has_files = bool(self.paths)
        self.clear_button.set_sensitive(has_files and not self._verifying)
        self.add_button.set_sensitive(not self._verifying)
        if has_files:
            self.add_button.remove_css_class("suggested-action")
        else:
            self.add_button.add_css_class("suggested-action")
        for button in self._remove_buttons.values():
            button.set_sensitive(not self._verifying)
        failed = self._failed_paths()
        self.remove_unreadable_button.set_visible(bool(failed))
        self.remove_unreadable_button.set_sensitive(bool(failed) and not self._verifying)
        if self._verifying:
            self.verify_button.set_sensitive(True)
            self.verify_button.set_label("Cancel")
            self.verify_button.remove_css_class("suggested-action")
            self.verify_button.add_css_class("destructive-action")
        else:
            self.verify_button.set_sensitive(has_files)
            self.verify_button.set_label(f"_{VERIFY_INPUTS_TEXT}")
            self.verify_button.remove_css_class("destructive-action")
            self.verify_button.remove_css_class("suggested-action")
        self._summary.set_label(self._total_text())
        self._resize_to_content()

    def _snapshot_inputs(self) -> _InputSnapshot:
        return _InputSnapshot(
            tuple(self.paths), dict(self._status), frozenset(self.context.unreadable_input_paths)
        )

    def _discard_undo(self) -> None:
        toast = self._undo_toast
        self._undo_toast = None
        self._undo_snapshot = None
        if toast is not None:
            toast.dismiss()

    def _offer_undo(self, snapshot: _InputSnapshot, message: str) -> None:
        self._discard_undo()
        toast = Adw.Toast(title=message, button_label="_Undo", timeout=8)
        self._undo_snapshot = snapshot
        self._undo_toast = toast
        toast.connect("button-clicked", self._undo_removal)
        toast.connect("dismissed", self._undo_dismissed)
        self.toast_overlay.add_toast(toast)

    def _undo_dismissed(self, toast: Adw.Toast) -> None:
        if toast is self._undo_toast:
            self._undo_toast = None
            self._undo_snapshot = None

    def _undo_removal(self, toast: Adw.Toast) -> None:
        if self._lifetime.disposed or self._verifying or toast is not self._undo_toast:
            return
        snapshot = self._undo_snapshot
        if snapshot is None:
            return
        self._discard_undo()
        self.paths = list(snapshot.paths)
        self._status = dict(snapshot.status)
        self.context.set_unreadable_input_paths(sorted(snapshot.unreadable))
        self._commit_paths()
        self._rebuild_list()
        self._sync_actions()

    def _commit_paths(self) -> None:
        self.settings.process.input_paths = list(self.paths)
        error = self.context.try_save_settings(trigger="verify-inputs")
        if error:
            self._toast(error)
        self.context.prune_unreadable_input_paths(self.paths)
        if self._on_inputs_changed is not None:
            self._on_inputs_changed(list(self.paths))

    def _remove_path(self, path: str) -> None:
        if not self._verifying and path in self.paths:
            snapshot = self._snapshot_inputs()
            self.paths.remove(path)
            self._status.pop(path, None)
            self._commit_paths()
            self._rebuild_list()
            self._sync_actions()
            self._offer_undo(snapshot, "File removed")

    def _on_clear(self, _button: typing.Any) -> None:
        if not self.paths or self._verifying:
            return
        snapshot = self._snapshot_inputs()
        self.paths = []
        self._status.clear()
        self.context.clear_unreadable_input_paths()
        self._commit_paths()
        self._rebuild_list()
        self._sync_actions()
        self._offer_undo(snapshot, "Input files cleared")

    def _on_remove_unreadable(self, _button: typing.Any) -> None:
        if self._verifying:
            return
        failed = set(self._failed_paths()) | set(self.context.unreadable_input_paths)
        if not failed:
            return
        snapshot = self._snapshot_inputs()
        before = len(self.paths)
        self.paths = remove_unreadable_from_paths(self.paths, failed)
        for path in failed:
            self._status.pop(path, None)
        self.context.clear_unreadable_input_paths()
        removed = before - len(self.paths)
        self._commit_paths()
        self._rebuild_list()
        self._sync_actions()
        if removed:
            noun = "file" if removed == 1 else "files"
            self._offer_undo(snapshot, f"Removed {removed} unreadable {noun}")

    def _on_add(self, _button: typing.Any) -> None:
        initial = os.path.dirname(self.paths[0]) if self.paths else None
        dialog = audio_open_dialog(
            "Select Audio Files",
            accept_any=bool(self.settings.process.accept_any_input),
            initial=initial,
        )
        dialog.open_multiple(root_window(self.dialog), None, self._on_add_finished)

    def _on_add_finished(self, dialog: typing.Any, result: typing.Any) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error as exc:
            if not self._lifetime.disposed and not is_dialog_dismissed(exc):
                self._toast(f"Couldn't open files: {exc.message}")
            return
        if self._lifetime.disposed:
            return
        added = [files.get_item(i).get_path() for i in range(files.get_n_items())]
        added = [p for p in added if p]
        if not added:
            return
        self._discard_undo()
        merged = merge_input_paths(self.paths, added)
        cleaned, sanitize_result = sanitize_input_paths(merged)
        self.paths = cleaned
        # New additions invalidate prior verify for paths no longer present.
        self._status = {p: s for p, s in self._status.items() if p in self.paths}
        self._commit_paths()
        self._rebuild_list()
        self._sync_actions()
        for message in format_input_sanitize_toasts(
            sanitize_result,
            include_missing=sanitize_result.removed_missing > 0,
        ):
            self._toast(message)

    # -- Verification -----------------------------------------------------------

    def _on_closed(self, *_args: typing.Any) -> None:
        self._lifetime.dispose()
        self._discard_undo()
        if self._verifying:
            self._verify_stop.set()

    def _on_verify(self, _button: typing.Any) -> None:
        if self._verifying:
            self._verify_stop.set()
            self.verify_button.set_label("Cancelling…")
            self.verify_button.set_sensitive(False)
            return
        if not self.paths:
            self._toast("No files to verify.")
            return
        self._discard_undo()
        self._verifying = True
        self._verification_generation = self.context.begin_input_verification()
        self._verify_stop.clear()
        self._verify_total = len(self.paths)
        self._status.clear()
        for path in self._rows:
            self._update_row_status(path)
        self._sync_actions()
        snapshot = list(self.paths)
        threading.Thread(
            target=self._verify_worker,
            args=(snapshot,),
            daemon=True,
        ).start()

    def _verify_worker(self, paths: typing.Any) -> None:
        broken = []
        verified_paths = []
        cancelled = False
        for index, path in enumerate(paths, start=1):
            if self._verify_stop.is_set():
                cancelled = True
                break
            is_valid, info = inspect_audio(path)
            verified_paths.append(path)
            idle_on_main(self._apply_result, path, is_valid, info, index)
            if not is_valid:
                broken.append((path, info))
        idle_on_main(
            self._verify_done,
            broken,
            cancelled,
            verified_paths,
        )

    def _apply_result(
        self, path: typing.Any, is_valid: typing.Any, info: typing.Any, index: int
    ) -> None:
        if self._lifetime.disposed:
            return
        self._status[path] = (is_valid, info)
        row = self._rows.get(path)
        if row is None:
            return
        self._update_row_status(path)
        self._summary.set_label(self._total_text())
        self._resize_to_content()

    def _verify_done(
        self,
        broken: typing.Any,
        cancelled: bool = False,
        verified_paths: typing.Any = (),
    ) -> None:
        failed_paths = [p for p, _info in broken]
        if self._verification_generation is not None:
            changed = self.context.apply_input_verification(
                self._verification_generation, verified_paths, failed_paths
            )
            if changed and self._on_verification_changed is not None:
                self._on_verification_changed()
        if self._lifetime.disposed:
            return
        self._verifying = False
        self._verify_stop.clear()
        self._rebuild_list()
        self._sync_actions()
        from core.debug_log import debug

        total = len(self.paths)
        debug("ui", f"verify_inputs count={total} ok={total - len(broken)} cancelled={cancelled}")
        if cancelled:
            self._toast("Verification cancelled")
        elif broken:
            report_lines = "\n".join(f"{os.path.basename(p)}: {info}" for p, info in broken)
            set_error_log(
                "Audio Input Verification Report:\n\nBroken / unreadable files:\n\n" + report_lines
            )
            self._toast(f"{len(broken)} file(s) could not be read.")
        else:
            self._toast("No errors found!")

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))


def open_view_inputs(
    parent_window: typing.Any,
    app_context: typing.Any,
    on_inputs_changed: typing.Any = None,
    on_verification_changed: typing.Callable[[], None] | None = None,
):
    """Open the Verify Inputs dialog. Wire to ``win.view_inputs``."""
    view = ViewInputs(
        parent_window,
        app_context,
        on_inputs_changed=on_inputs_changed,
        on_verification_changed=on_verification_changed,
    )
    view.present()
    return view
