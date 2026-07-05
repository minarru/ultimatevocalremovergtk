"""View / verify selected input audio files (port of ``menu_view_inputs``).

Lists the currently-selected input files (the ``input_paths`` setting), shows the
total count, lets the user add / remove / clear inputs, and verifies each file -
reporting duration / format / validity. Verification mirrors UVR's
``verify_audio`` (which loads each file to confirm it is readable) but runs on a
worker thread and marshals results back via ``GLib.idle_add``; the audio backend
is imported lazily so constructing the dialog stays ``torch``-free.

Entry point: :func:`open_view_inputs` (wire to a ``win.view_inputs`` action and/or
an input-row right-click / activation).
"""

import os
import threading

from gi.repository import Adw, GLib, Gtk

from bundled.constants import AUDIO_INPUT_TOTAL_TEXT, VERIFY_INPUTS_TEXT

from .errorlog import set_error_log
from .help_text import (
    ADD_INPUT_FILES_HINT,
    CLEAR_ALL_INPUTS_HINT,
    REMOVE_INPUT_HINT,
)
from .hints import set_tooltip
from .markup import set_row_subtitle, set_row_title

from .dispatch import idle_on_main
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
        return False, f"{type(exc).__name__}: {exc}"


class ViewInputs:
    def __init__(self, parent, app_context, on_inputs_changed=None):
        self.parent = parent
        self.context = app_context
        self.settings = app_context.settings
        self._on_inputs_changed = on_inputs_changed
        self.paths = list(self.settings.get("input_paths") or [])
        self._rows = {}
        self._verifying = False

        self.window = Adw.Window(title="Selected Inputs")
        self.window.set_default_size(620, 560)
        if parent is not None:
            self.window.set_transient_for(parent)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        add_button = Gtk.Button(icon_name="list-add-symbolic")
        set_tooltip(add_button, ADD_INPUT_FILES_HINT)
        add_button.connect("clicked", self._on_add)
        header.pack_start(add_button)

        clear_button = Gtk.Button(icon_name="edit-clear-all-symbolic")
        set_tooltip(clear_button, CLEAR_ALL_INPUTS_HINT)
        clear_button.connect("clicked", self._on_clear)
        header.pack_start(clear_button)

        self.verify_button = Gtk.Button(label=VERIFY_INPUTS_TEXT)
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

        self._rebuild_list()

    def present(self) -> None:
        self.window.present()

    # -- List management --------------------------------------------------------

    def _total_text(self) -> str:
        return f"{AUDIO_INPUT_TOTAL_TEXT}: {len(self.paths)}"

    def _rebuild_list(self) -> None:
        for row in self._rows.values():
            self._files_group.remove(row)
        self._rows = {}
        self._files_group.set_title(self._total_text())

        if not self.paths:
            placeholder = Adw.ActionRow(title="No files selected")
            self._rows["__placeholder__"] = placeholder
            self._files_group.add(placeholder)
            return

        for path in self.paths:
            row = Adw.ActionRow()
            set_row_title(row, os.path.basename(path))
            set_row_subtitle(row, path)
            remove_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            remove_button.add_css_class("flat")
            set_tooltip(remove_button, REMOVE_INPUT_HINT)
            remove_button.connect("clicked", lambda _b, p=path: self._remove_path(p))
            row.add_suffix(remove_button)
            self._files_group.add(row)
            self._rows[path] = row

    def _commit_paths(self) -> None:
        self.settings.set("input_paths", list(self.paths))
        self.context.save_settings()
        if self._on_inputs_changed is not None:
            self._on_inputs_changed(list(self.paths))

    def _remove_path(self, path: str) -> None:
        if path in self.paths:
            self.paths.remove(path)
            self._commit_paths()
            self._rebuild_list()

    def _on_clear(self, _button) -> None:
        if not self.paths:
            return
        self.paths = []
        self._commit_paths()
        self._rebuild_list()

    def _on_add(self, _button) -> None:
        dialog = Gtk.FileDialog(title="Select Audio Files")
        dialog.open_multiple(self.window, None, self._on_add_finished)

    def _on_add_finished(self, dialog, result) -> None:
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        added = [files.get_item(i).get_path() for i in range(files.get_n_items())]
        added = [p for p in added if p and p not in self.paths]
        if added:
            self.paths.extend(added)
            self._commit_paths()
            self._rebuild_list()

    # -- Verification -----------------------------------------------------------

    def _on_verify(self, _button) -> None:
        if self._verifying or not self.paths:
            if not self.paths:
                self._toast("No files to verify.")
            return
        self._verifying = True
        self.verify_button.set_sensitive(False)
        snapshot = list(self.paths)
        threading.Thread(target=self._verify_worker, args=(snapshot,), daemon=True).start()

    def _verify_worker(self, paths) -> None:
        broken = []
        for path in paths:
            is_valid, info = inspect_audio(path)
            idle_on_main(self._apply_result, path, is_valid, info)
            if not is_valid:
                broken.append((path, info))
        idle_on_main(self._verify_done, broken)

    def _apply_result(self, path, is_valid, info) -> None:
        row = self._rows.get(path)
        if row is None:
            return
        marker = "\u2713" if is_valid else "\u2717"
        set_row_subtitle(row, f"{marker} {info}\n{path}")

    def _verify_done(self, broken) -> None:
        self._verifying = False
        self.verify_button.set_sensitive(True)
        if broken:
            report_lines = "\n".join(f"{os.path.basename(p)}: {info}" for p, info in broken)
            set_error_log(
                "Audio Input Verification Report:\n\nBroken / unreadable files:\n\n" + report_lines
            )
            self._toast(f"{len(broken)} file(s) could not be read.")
        else:
            self._toast("No errors found!")

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))


def open_view_inputs(parent_window, app_context, on_inputs_changed=None):
    """Open the view-inputs verification dialog. Wire to ``win.view_inputs``."""
    view = ViewInputs(parent_window, app_context, on_inputs_changed=on_inputs_changed)
    view.present()
    return view
