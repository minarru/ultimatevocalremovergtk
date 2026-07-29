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

from gi.repository import Adw, GLib, Gtk

from bundled.constants import AUDIO_INPUT_TOTAL_TEXT, VERIFY_INPUTS_TEXT

from .dialogs.utils import close_on_escape
from .errorlog import log_error, set_error_log
from .help_text import (
    ADD_INPUT_FILES_HINT,
    CLEAR_ALL_INPUTS_HINT,
    REMOVE_INPUT_HINT,
)
from .hints import set_icon_button_a11y
from .markup import set_row_subtitle, set_row_title
from .dispatch import idle_on_main
from .shared_settings import (
    format_input_sanitize_toasts,
    remove_unreadable_from_paths,
    sanitize_input_paths,
)
from .widgets.file_chooser import merge_input_paths
from .widgets.file_dialogs import audio_open_dialog, is_dialog_dismissed
from .widgets.rows import set_row_icon

_REMOVE_UNREADABLE_TEXT = "Remove unreadable"
_STATUS_OK = "success-small-symbolic"
_STATUS_BAD = "error-small-symbolic"


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
    if not os.path.isfile(path):
        return False, "file not found"

    try:
        import soundfile as sf

        info = sf.info(path)
        duration = info.frames / info.samplerate if info.samplerate else 0
        return True, f"{_fmt_duration(duration)} \u2022 {info.format} \u2022 {info.channels}ch \u2022 {info.samplerate} Hz"
    except Exception:
        pass

    try:
        import contextlib
        import wave

        with contextlib.closing(wave.open(path, "r")) as handle:
            rate = handle.getframerate()
            duration = handle.getnframes() / float(rate) if rate else 0
            return True, f"{_fmt_duration(duration)} \u2022 WAV \u2022 {handle.getnchannels()}ch \u2022 {rate} Hz"
    except Exception:
        pass

    try:
        import librosa

        librosa.load(path, duration=3, mono=False, sr=44100)
        return True, "readable"
    except Exception as exc:  # noqa: BLE001 - reported back to the user
        log_error("Verify Inputs", exc, context=f"path={path!r}")
        return False, "Could not read this file"


class ViewInputs:
    def __init__(self, parent, app_context, on_inputs_changed=None):
        self.parent = parent
        self.context = app_context
        self.settings = app_context.settings
        self._on_inputs_changed = on_inputs_changed
        self.paths = list(self.settings.process.input_paths or [])
        self._rows = {}
        self._status = {}  # path -> (is_valid, info) after verify
        self._verifying = False
        self._verify_total = 0
        self._verify_stop = threading.Event()

        self.window = Adw.Window(title=VERIFY_INPUTS_TEXT)
        self.window.set_default_size(620, 560)
        if parent is not None:
            self.window.set_transient_for(parent)
        close_on_escape(self.window)
        self.window.connect("close-request", self._on_close_request)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        self.add_button = Gtk.Button(icon_name="list-add-symbolic")
        set_icon_button_a11y(self.add_button, ADD_INPUT_FILES_HINT)
        self.add_button.connect("clicked", self._on_add)
        header.pack_start(self.add_button)

        self.clear_button = Gtk.Button(icon_name="edit-clear-all-symbolic")
        set_icon_button_a11y(self.clear_button, CLEAR_ALL_INPUTS_HINT)
        self.clear_button.connect("clicked", self._on_clear)
        header.pack_start(self.clear_button)

        self.remove_unreadable_button = Gtk.Button(label=_REMOVE_UNREADABLE_TEXT)
        self.remove_unreadable_button.add_css_class("destructive-action")
        self.remove_unreadable_button.connect("clicked", self._on_remove_unreadable)
        header.pack_end(self.remove_unreadable_button)

        self.verify_button = Gtk.Button(label=f"_{VERIFY_INPUTS_TEXT}", use_underline=True)
        self.verify_button.add_css_class("suggested-action")
        self.verify_button.connect("clicked", self._on_verify)
        header.pack_end(self.verify_button)
        toolbar.add_top_bar(header)

        self.toast_overlay = Adw.ToastOverlay()
        self.page = Adw.PreferencesPage()
        self._files_group = Adw.PreferencesGroup(title=self._total_text())
        self.page.add(self._files_group)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.page)
        self.toast_overlay.set_child(scroller)
        toolbar.set_content(self.toast_overlay)
        self.window.set_content(toolbar)

        # Seed status from any prior verify still tracked on the context.
        for path in self.context.unreadable_input_paths:
            if path in self.paths:
                self._status[path] = (False, "unreadable")

        self._rebuild_list()
        self._sync_actions()

    def present(self) -> None:
        self.window.present()

    # -- List management --------------------------------------------------------

    def _failed_paths(self) -> list[str]:
        return [p for p, (ok, _info) in self._status.items() if not ok and p in self.paths]

    def _total_text(self) -> str:
        n = len(self.paths)
        base = f"{AUDIO_INPUT_TOTAL_TEXT}: {n}"
        failed = len(self._failed_paths())
        if failed:
            return f"{base} · {failed} unreadable"
        if self._status and n and failed == 0 and len(self._status) >= n:
            return f"{base} · all readable"
        return base

    def _rebuild_list(self) -> None:
        for row in self._rows.values():
            self._files_group.remove(row)
        self._rows = {}
        self._files_group.set_title(self._total_text())

        if not self.paths:
            placeholder = Adw.ActionRow(
                title="No files selected",
                subtitle="Add audio files to verify them before starting a run",
            )
            add_suffix = Gtk.Button(label="Add files", valign=Gtk.Align.CENTER)
            add_suffix.add_css_class("suggested-action")
            add_suffix.connect("clicked", self._on_add)
            placeholder.add_suffix(add_suffix)
            self._rows["__placeholder__"] = placeholder
            self._files_group.add(placeholder)
            return

        for path in self.paths:
            row = Adw.ActionRow()
            set_row_title(row, os.path.basename(path))
            status = self._status.get(path)
            if status is None:
                set_row_subtitle(row, path)
                set_row_icon(row, None)
            else:
                is_valid, info = status
                set_row_icon(row, _STATUS_OK if is_valid else _STATUS_BAD)
                set_row_subtitle(row, f"{path}\n{info}")
            remove_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            remove_button.add_css_class("flat")
            set_icon_button_a11y(remove_button, REMOVE_INPUT_HINT)
            remove_button.connect("clicked", lambda _b, p=path: self._remove_path(p))
            row.add_suffix(remove_button)
            self._files_group.add(row)
            self._rows[path] = row

    def _sync_actions(self) -> None:
        has_files = bool(self.paths)
        self.clear_button.set_sensitive(has_files and not self._verifying)
        self.add_button.set_sensitive(not self._verifying)
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
            self.verify_button.add_css_class("suggested-action")

    def _commit_paths(self) -> None:
        self.settings.process.input_paths = list(self.paths)
        error = self.context.try_save_settings(trigger="verify-inputs")
        if error:
            self._toast(error)
        self.context.prune_unreadable_input_paths(self.paths)
        if self._on_inputs_changed is not None:
            self._on_inputs_changed(list(self.paths))

    def _remove_path(self, path: str) -> None:
        if path in self.paths:
            self.paths.remove(path)
            self._status.pop(path, None)
            self._commit_paths()
            self._rebuild_list()
            self._sync_actions()

    def _on_clear(self, _button) -> None:
        if not self.paths:
            return
        self.paths = []
        self._status.clear()
        self.context.clear_unreadable_input_paths()
        self._commit_paths()
        self._rebuild_list()
        self._sync_actions()

    def _on_remove_unreadable(self, _button) -> None:
        failed = set(self._failed_paths()) | set(self.context.unreadable_input_paths)
        if not failed:
            return
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
            self._toast(f"Removed {removed} unreadable {noun}.")

    def _on_add(self, _button) -> None:
        initial = os.path.dirname(self.paths[0]) if self.paths else None
        dialog = audio_open_dialog(
            "Select Audio Files",
            accept_any=bool(self.settings.process.accept_any_input),
            initial=initial,
        )
        dialog.open_multiple(self.window, None, self._on_add_finished)

    def _on_add_finished(self, dialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error as exc:
            if not is_dialog_dismissed(exc):
                self._toast(f"Couldn't open files: {exc.message}")
            return
        added = [files.get_item(i).get_path() for i in range(files.get_n_items())]
        added = [p for p in added if p]
        if not added:
            return
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

    def _on_close_request(self, *_args) -> bool:
        if self._verifying:
            self._verify_stop.set()
        return False

    def _on_verify(self, _button) -> None:
        if self._verifying:
            self._verify_stop.set()
            self.verify_button.set_label("Cancelling…")
            self.verify_button.set_sensitive(False)
            return
        if not self.paths:
            self._toast("No files to verify.")
            return
        self._verifying = True
        self._verify_stop.clear()
        self._verify_total = len(self.paths)
        self._status.clear()
        self.verify_button.set_label(f"Verifying… 0/{self._verify_total}")
        self._sync_actions()
        snapshot = list(self.paths)
        threading.Thread(target=self._verify_worker, args=(snapshot,), daemon=True).start()

    def _verify_worker(self, paths) -> None:
        broken = []
        cancelled = False
        for index, path in enumerate(paths, start=1):
            if self._verify_stop.is_set():
                cancelled = True
                break
            is_valid, info = inspect_audio(path)
            idle_on_main(self._apply_result, path, is_valid, info, index)
            if not is_valid:
                broken.append((path, info))
        idle_on_main(self._verify_done, broken, cancelled)

    def _apply_result(self, path, is_valid, info, index: int) -> None:
        self._status[path] = (is_valid, info)
        self.verify_button.set_label(f"Verifying… {index}/{self._verify_total}")
        row = self._rows.get(path)
        if row is None:
            return
        set_row_icon(row, _STATUS_OK if is_valid else _STATUS_BAD)
        set_row_subtitle(row, f"{path}\n{info}")
        self._files_group.set_title(self._total_text())

    def _verify_done(self, broken, cancelled: bool = False) -> None:
        self._verifying = False
        self._verify_stop.clear()
        failed_paths = [p for p, _info in broken]
        self.context.set_unreadable_input_paths(failed_paths)
        self._rebuild_list()
        self._sync_actions()
        from core.debug_log import debug

        total = len(self.paths)
        debug("ui", f"verify_inputs count={total} ok={total - len(broken)} cancelled={cancelled}")
        if cancelled:
            self._toast("Verification cancelled")
            return
        if broken:
            report_lines = "\n".join(f"{os.path.basename(p)}: {info}" for p, info in broken)
            set_error_log(
                "Audio Input Verification Report:\n\nBroken / unreadable files:\n\n" + report_lines
            )
            self._toast(f"{len(broken)} file(s) could not be read.")
        else:
            self.context.clear_unreadable_input_paths()
            self._toast("No errors found!")
        if self._on_inputs_changed is not None:
            # Refresh Start readiness without changing the path list.
            self._on_inputs_changed(list(self.paths))

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))


def open_view_inputs(parent_window, app_context, on_inputs_changed=None):
    """Open the Verify Inputs dialog. Wire to ``win.view_inputs``."""
    view = ViewInputs(parent_window, app_context, on_inputs_changed=on_inputs_changed)
    view.present()
    return view
