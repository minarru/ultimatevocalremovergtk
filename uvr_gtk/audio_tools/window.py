"""Audio Tools page controller (GTK4 / libadwaita port of UVR's Audio Tools mode).

Refactored from a standalone ``Adw.Window`` into an embeddable *page controller*
hosted by the main window's ``content_stack`` (see
:class:`uvr_gtk.window.MainWindow`). The page builds only its option groups in
the shared responsive two-column layout; the console, progress bar and
Start/Stop action bar are shared across all modes and supplied by the main
window via :meth:`AudioToolsPage.start`.

It offers the five UVR audio tools as selectable sub-modes:

* **Manual Ensemble** - combine N files via the spectrogram/wave ensembler
  (``choose_algorithm``) or a straight ``Combine Inputs``.
* **Time Stretch** - rubberband time stretch by ``time_stretch_rate``.
* **Change Pitch** - rubberband pitch shift by ``pitch_rate`` semitones, with an
  optional ``is_time_correction`` toggle.
* **Align Inputs** - phase-aligned subtraction of two inputs with the full align
  advanced options, driven by the dual/batch editor.
* **Matchering** - reference-based mastering of (target, reference) pairs.

Heavy work runs on :class:`uvr_core.AudioToolRunner`'s ``KThread`` worker; all
progress / console / completion callbacks are marshaled onto the GTK main loop
through the caller-supplied callbacks (built with
:func:`uvr_gtk.dispatch.gtk_job_callbacks`). Options bind to the exact
``DEFAULT_DATA`` keys via the shared ``SettingsModel``.
"""

import os
from typing import List, Optional, Tuple

from gi.repository import Adw, Gio, GLib, Gtk

from data.constants import (
    ALIGN_INPUTS,
    ALIGN_PHASE_OPTIONS,
    APOLLO_CHUNK_SIZE_HELP,
    APOLLO_MODEL_FAIL_TEXT,
    APOLLO_OVERLAP_HELP,
    APOLLO_RESTORE,
    AUDIO_TOOLS_HELP,
    CHANGE_PITCH,
    CHOOSE_APOLLO_MODEL_HELP,
    CHOOSE_MODEL,
    FLAC,
    INTRO_ANALYSIS_ALIGN_HELP,
    INTRO_MAPPER,
    IS_ALIGN_TRACK_HELP,
    IS_GPU_CONVERSION_HELP,
    IS_MATCH_SILENCE_HELP,
    IS_MATCH_SPEC_HELP,
    IS_NORMALIZATION_HELP,
    IS_PHASE_HELP,
    IS_TESTING_AUDIO_HELP,
    IS_TIME_CORRECTION_HELP,
    IS_WAV_ENSEMBLE_HELP,
    MANUAL_ENSEMBLE,
    MANUAL_ENSEMBLE_OPTIONS,
    MATCH_INPUTS,
    MP3,
    PHASE_SHIFTS_ALIGN_HELP,
    PHASE_SHIFTS_OPT,
    PITCH_SHIFT_HELP,
    TIME_STRETCH,
    TIME_WINDOW_ALIGN_HELP,
    TIME_WINDOW_MAPPER,
    VOLUME_ANALYSIS_ALIGN_HELP,
    VOLUME_MAPPER,
    WAV,
    WAV_TYPE,
)

from ..hints import HelpHintManager, OUTPUT_FORMAT_HINT
from ..shared_settings import apply_shared_file_options
from ..markup import set_row_subtitle
from ..widgets.columns import build_columns_box, wrap_options_scroller
from ..widgets.file_chooser import InputFilesRow, OutputFolderRow
from ..widgets.rows import (
    get_combo_value,
    make_combo_row,
    make_switch_row,
    set_combo_value,
    set_combo_values,
    use_wrapping_list,
)
from .dual_batch import DualBatchDialog

# Full tool list (Time Stretch / Change Pitch are surfaced on all platforms here;
# UVR hides them on Linux purely because pyrubberband may be unavailable - the
# backend reports that as a graceful error if the dep is missing).
AUDIO_TOOL_ORDER = (MANUAL_ENSEMBLE, TIME_STRETCH, CHANGE_PITCH, ALIGN_INPUTS, MATCH_INPUTS, APOLLO_RESTORE)

_TOOL_LABELS = (("File 1", "File 2"), ("Target", "Reference"))

#: Blocking-reason strings surfaced as the shared Start button tooltip when the
#: active audio tool is missing a required field.
_REASON_OUTPUT = "Choose an output folder"
_REASON_INPUT = "Select an input file"
_REASON_DUAL_INPUTS = "Add input pairs in the dual/batch editor"
_REASON_TWO_FILES = "Select two or more files"
_REASON_NO_APOLLO = "No Apollo models found"
_REASON_APOLLO_MODEL = "Select an Apollo model"


class AudioToolsPage:
    """Embeddable Audio Tools page bound to the shared :class:`AppContext`.

    Exposes the uniform "run target" interface the main window's shared
    Start/Stop dispatch expects: :attr:`widget`, :attr:`columns_box`,
    :meth:`start`, :meth:`stop`, :meth:`on_activated`, :meth:`on_deactivated`
    and :meth:`load`. Every control writes its settings key live on change, so
    there is no separate flush step; the main window persists everything via
    ``AppContext.save_settings`` on close.
    """

    def __init__(self, window, context):
        # ``window`` is the MainWindow; the page borrows it for toasts, dialog
        # parenting and the shared run-control helpers.
        self.window = window
        self.context = context
        self.settings = context.settings
        self._loading = False
        self._dual_pairs: List[Tuple[str, str]] = [
            (str(p[0]), str(p[1]))
            for p in (self.settings.get("DualBatch_inputPaths") or [])
            if len(p) == 2
        ]
        # Align and matchering each build their own (input one / input two) rows;
        # both reflect the same dual pairs, so they are refreshed together.
        self._dual_row_sets: List[Tuple[Adw.ActionRow, Adw.ActionRow]] = []
        self._runner = None
        # Same per-view help-hint manager the separation method views use
        # (see ``uvr_gtk.views.base.MethodView``), so Audio Tools tooltips are
        # registered through the identical ``HelpHintManager`` path.
        self.hints = HelpHintManager(self.settings)

        select_group = self._build_select_group()
        self.tool_stack = self._build_tool_stack()
        shared_group = self._build_shared_group()

        # Tool selector + the active tool's options fill the left column; the
        # shared output options balance the right column.
        self.columns_box, self._col_start, self._col_end = build_columns_box(
            left_groups=(select_group, self.tool_stack),
            right_groups=(shared_group,),
        )
        self.widget = wrap_options_scroller(self.columns_box)

    @property
    def runner(self):
        if self._runner is None:
            from uvr_core.audio_tools import AudioToolRunner

            self._runner = AudioToolRunner(self.settings)
        return self._runner

    #: Label used when recording errors to the shared error log.
    @property
    def error_key(self) -> str:
        return self._current_tool()

    # -- Construction ----------------------------------------------------------

    def _build_select_group(self) -> Adw.PreferencesGroup:
        select_group = Adw.PreferencesGroup(title="Audio tool")
        self.tool_row = make_combo_row("Tool", AUDIO_TOOL_ORDER, icon_name="applications-utilities-symbolic")
        self.hints.register(self.tool_row, AUDIO_TOOLS_HELP)
        self.tool_row.connect("notify::selected", self._on_tool_changed)
        select_group.add(self.tool_row)
        return select_group

    def _build_tool_stack(self) -> Gtk.Stack:
        stack = Gtk.Stack()
        stack.set_vhomogeneous(False)
        stack.add_named(self._build_manual_ensemble_page(), MANUAL_ENSEMBLE)
        stack.add_named(self._build_time_stretch_page(), TIME_STRETCH)
        stack.add_named(self._build_pitch_page(), CHANGE_PITCH)
        stack.add_named(self._build_align_page(), ALIGN_INPUTS)
        stack.add_named(self._build_match_page(), MATCH_INPUTS)
        stack.add_named(self._build_apollo_page(), APOLLO_RESTORE)
        return stack

    # -- Per-tool pages --------------------------------------------------------

    def _build_manual_ensemble_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Manual Ensemble", description="Combine two or more audio files")

        self.me_inputs_row = InputFilesRow(self._on_inputs_changed)
        group.add(self.me_inputs_row)

        self.algorithm_row = make_combo_row("Algorithm", MANUAL_ENSEMBLE_OPTIONS)
        self.hints.register(self.algorithm_row, "Choose how the selected files are combined (e.g. Min/Max, Average, or Combine Inputs)")
        self.algorithm_row.connect("notify::selected", lambda *_a: self._set("choose_algorithm", get_combo_value(self.algorithm_row)))
        group.add(self.algorithm_row)

        self.wav_ensemble_row = make_switch_row("Ensemble waveforms", "Ensemble in the time domain instead of spectrograms")
        self.hints.register(self.wav_ensemble_row, IS_WAV_ENSEMBLE_HELP)
        self.wav_ensemble_row.connect("notify::active", lambda *_a: self._set("is_wav_ensemble", self.wav_ensemble_row.get_active()))
        group.add(self.wav_ensemble_row)

        box.append(group)
        return box

    def _build_time_stretch_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Time Stretch", description="Change playback rate (requires pyrubberband)")

        self.ts_inputs_row = InputFilesRow(self._on_inputs_changed)
        group.add(self.ts_inputs_row)

        self.time_rate_row = self._make_spin("Rate", 0.1, 10.0, 0.1, digits=2)
        self.hints.register(self.time_rate_row, "Playback rate multiplier: values below 1 slow the track down, values above 1 speed it up")
        self.time_rate_row.connect("notify::value", lambda *_a: self._set("time_stretch_rate", round(self.time_rate_row.get_value(), 2)))
        group.add(self.time_rate_row)

        box.append(group)
        return box

    def _build_pitch_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Change Pitch", description="Pitch shift in semitones (requires pyrubberband)")

        self.ps_inputs_row = InputFilesRow(self._on_inputs_changed)
        group.add(self.ps_inputs_row)

        self.pitch_rate_row = self._make_spin("Semitones", -10.0, 10.0, 0.5, digits=2)
        self.hints.register(self.pitch_rate_row, PITCH_SHIFT_HELP)
        self.pitch_rate_row.connect("notify::value", lambda *_a: self._set("pitch_rate", round(self.pitch_rate_row.get_value(), 2)))
        group.add(self.pitch_rate_row)

        self.time_correction_row = make_switch_row("Time correction", "Preserve length while shifting pitch")
        self.hints.register(self.time_correction_row, IS_TIME_CORRECTION_HELP)
        self.time_correction_row.connect("notify::active", lambda *_a: self._set("is_time_correction", self.time_correction_row.get_active()))
        group.add(self.time_correction_row)

        box.append(group)
        return box

    def _build_align_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Align Inputs", description="Phase-align and subtract two inputs")
        group.add(self._build_dual_rows())

        self.time_window_row = make_combo_row("Time window", list(TIME_WINDOW_MAPPER.keys()))
        self.hints.register(self.time_window_row, TIME_WINDOW_ALIGN_HELP)
        self.time_window_row.connect("notify::selected", lambda *_a: self._set("time_window", get_combo_value(self.time_window_row)))
        group.add(self.time_window_row)

        self.intro_row = make_combo_row("Intro analysis", list(INTRO_MAPPER.keys()))
        self.hints.register(self.intro_row, INTRO_ANALYSIS_ALIGN_HELP)
        self.intro_row.connect("notify::selected", lambda *_a: self._set("intro_analysis", get_combo_value(self.intro_row)))
        group.add(self.intro_row)

        self.db_row = make_combo_row("Volume adjustment", list(VOLUME_MAPPER.keys()))
        self.hints.register(self.db_row, VOLUME_ANALYSIS_ALIGN_HELP)
        self.db_row.connect("notify::selected", lambda *_a: self._set("db_analysis", get_combo_value(self.db_row)))
        group.add(self.db_row)

        advanced = Adw.ExpanderRow(title="Advanced align options")
        self.phase_option_row = make_combo_row("Secondary phase", ALIGN_PHASE_OPTIONS)
        self.hints.register(self.phase_option_row, IS_PHASE_HELP)
        self.phase_option_row.connect("notify::selected", lambda *_a: self._set("phase_option", get_combo_value(self.phase_option_row)))
        advanced.add_row(self.phase_option_row)

        self.phase_shifts_row = make_combo_row("Phase shifts", list(PHASE_SHIFTS_OPT.keys()))
        self.hints.register(self.phase_shifts_row, PHASE_SHIFTS_ALIGN_HELP)
        self.phase_shifts_row.connect("notify::selected", lambda *_a: self._set("phase_shifts", get_combo_value(self.phase_shifts_row)))
        advanced.add_row(self.phase_shifts_row)

        self.save_align_row = make_switch_row("Save aligned track")
        self.hints.register(self.save_align_row, IS_ALIGN_TRACK_HELP)
        self.save_align_row.connect("notify::active", lambda *_a: self._set("is_save_align", self.save_align_row.get_active()))
        advanced.add_row(self.save_align_row)

        self.match_silence_row = make_switch_row("Silence matching")
        self.hints.register(self.match_silence_row, IS_MATCH_SILENCE_HELP)
        self.match_silence_row.connect("notify::active", lambda *_a: self._set("is_match_silence", self.match_silence_row.get_active()))
        advanced.add_row(self.match_silence_row)

        self.spec_match_row = make_switch_row("Spectral matching")
        self.hints.register(self.spec_match_row, IS_MATCH_SPEC_HELP)
        self.spec_match_row.connect("notify::active", lambda *_a: self._set("is_spec_match", self.spec_match_row.get_active()))
        advanced.add_row(self.spec_match_row)

        adv_group = Adw.PreferencesGroup()
        adv_group.add(advanced)

        box.append(group)
        box.append(adv_group)
        return box

    def _build_match_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Matchering", description="Master target(s) to a reference (requires matchering)")
        group.add(self._build_dual_rows())
        box.append(group)
        return box

    def _build_apollo_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        self.apollo_banner = Adw.Banner(
            title=(
                "No Apollo models found. Place an Apollo checkpoint (.ckpt or .bin) "
                "in the Apollo models folder, then reload."
            ),
            button_label="Open Folder",
            revealed=False,
        )
        self.apollo_banner.add_css_class("app-banner")
        self.apollo_banner.connect("button-clicked", self._on_open_apollo_folder)
        box.append(self.apollo_banner)

        group = Adw.PreferencesGroup(
            title="Apollo Restore",
            description="Restore codec-distorted audio (e.g. low-bitrate MP3s)",
        )

        self.ap_inputs_row = InputFilesRow(self._on_inputs_changed)
        group.add(self.ap_inputs_row)

        self.apollo_model_row = make_combo_row("Apollo model", [CHOOSE_MODEL])
        use_wrapping_list(self.apollo_model_row)
        self.hints.register(self.apollo_model_row, CHOOSE_APOLLO_MODEL_HELP)
        self.apollo_model_row.connect("notify::selected", self._on_apollo_model_changed)
        group.add(self.apollo_model_row)

        self.apollo_overlap_row = self._make_spin("Overlap", 0, 50, 1, digits=0)
        self.hints.register(self.apollo_overlap_row, APOLLO_OVERLAP_HELP)
        self.apollo_overlap_row.connect(
            "notify::value",
            lambda *_a: self._set("apollo_overlap", str(int(self.apollo_overlap_row.get_value()))),
        )
        group.add(self.apollo_overlap_row)

        self.apollo_chunk_row = self._make_spin("Chunk size", 1, 50, 1, digits=0)
        self.hints.register(self.apollo_chunk_row, APOLLO_CHUNK_SIZE_HELP)
        self.apollo_chunk_row.connect(
            "notify::value",
            lambda *_a: self._set("apollo_chunk_size", str(int(self.apollo_chunk_row.get_value()))),
        )
        group.add(self.apollo_chunk_row)

        # Apollo is the only GPU-accelerated audio tool; the shared GPU toggle
        # lives on the separation tabs, so expose it here too (same setting key).
        self.apollo_gpu_row = make_switch_row("GPU conversion", "Use CUDA when available", icon_name="pci-card-symbolic")
        self.hints.register(self.apollo_gpu_row, IS_GPU_CONVERSION_HELP)
        self.apollo_gpu_row.connect(
            "notify::active",
            lambda *_a: self._set("is_gpu_conversion", self.apollo_gpu_row.get_active()),
        )
        group.add(self.apollo_gpu_row)

        box.append(group)
        return box

    def _on_apollo_model_changed(self, *_args) -> None:
        self._set("apollo_model", get_combo_value(self.apollo_model_row))

    def _refresh_apollo_models(self) -> None:
        """Repopulate the Apollo model picker from the models on disk."""
        from uvr_core.apollo import list_apollo_models

        found = list_apollo_models()
        models = [CHOOSE_MODEL, *found]
        stored = self.settings.get("apollo_model") or CHOOSE_MODEL
        was_loading = self._loading
        self._loading = True
        try:
            set_combo_values(self.apollo_model_row, models)
            if not set_combo_value(self.apollo_model_row, stored):
                self.apollo_model_row.set_selected(0)
        finally:
            self._loading = was_loading

        has_models = bool(found)
        self.apollo_model_row.set_visible(has_models)
        self.apollo_banner.set_revealed(not has_models)

    def _build_dual_rows(self) -> Gtk.Widget:
        """Two-file display + dual/batch editor button for align/match.

        Called once per dual tool; each call builds its own row pair (a widget
        can't be shared between two parents) and registers it so all dual pages
        stay in sync with :attr:`_dual_pairs`.
        """
        wrapper = Adw.PreferencesGroup()
        file_one_row = Adw.ActionRow(title="Input one", subtitle="Not set")
        file_two_row = Adw.ActionRow(title="Input two", subtitle="Not set")

        edit_button = Gtk.Button(label="Dual / Batch editor\u2026", valign=Gtk.Align.CENTER)
        edit_button.connect("clicked", self._on_open_dual_editor)
        file_one_row.add_suffix(edit_button)
        file_one_row.set_activatable_widget(edit_button)

        wrapper.add(file_one_row)
        wrapper.add(file_two_row)
        self._dual_row_sets.append((file_one_row, file_two_row))
        return wrapper

    def _build_shared_group(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup(title="Output and options")

        self.output_row = OutputFolderRow(self._on_output_changed)
        group.add(self.output_row)

        self.format_row = make_combo_row("Output format", [WAV, FLAC, MP3], icon_name="audio-x-generic-symbolic")
        self.hints.register(self.format_row, OUTPUT_FORMAT_HINT)
        self.format_row.connect("notify::selected", lambda *_a: self._set("save_format", get_combo_value(self.format_row)))
        group.add(self.format_row)

        self.wav_type_row = make_combo_row("WAV type", WAV_TYPE)
        self.hints.register(self.wav_type_row, "Bit depth / sample encoding used when saving WAV output")
        self.wav_type_row.connect("notify::selected", lambda *_a: self._set("wav_type_set", get_combo_value(self.wav_type_row)))
        group.add(self.wav_type_row)

        self.normalize_row = make_switch_row("Normalize output")
        self.hints.register(self.normalize_row, IS_NORMALIZATION_HELP)
        self.normalize_row.connect("notify::active", lambda *_a: self._set("is_normalization", self.normalize_row.get_active()))
        group.add(self.normalize_row)

        self.testing_row = make_switch_row("Settings test", "Append a timestamp to output names to avoid overwrites")
        self.hints.register(self.testing_row, IS_TESTING_AUDIO_HELP)
        self.testing_row.connect("notify::active", lambda *_a: self._set("is_testing_audio", self.testing_row.get_active()))
        group.add(self.testing_row)

        return group

    @staticmethod
    def _make_spin(title: str, lower: float, upper: float, step: float, digits: int = 2) -> Adw.SpinRow:
        adjustment = Gtk.Adjustment(lower=lower, upper=upper, step_increment=step)
        return Adw.SpinRow(title=title, adjustment=adjustment, digits=digits)

    # -- Settings load / persist -----------------------------------------------

    def _set(self, key: str, value) -> None:
        if self._loading:
            return
        self.settings.set(key, value)

    def _current_tool(self) -> str:
        return get_combo_value(self.tool_row) or MANUAL_ENSEMBLE

    def load(self) -> None:
        self._loading = True
        try:
            s = self.settings
            set_combo_value(self.tool_row, s.get("chosen_audio_tool", MANUAL_ENSEMBLE))

            inputs = s.get("input_paths") or []
            for row in (self.me_inputs_row, self.ts_inputs_row, self.ps_inputs_row, self.ap_inputs_row):
                row.set_paths(inputs, notify=False)
            self.output_row.set_path(s.get("export_path") or "", notify=False)

            set_combo_value(self.algorithm_row, s.get("choose_algorithm"))
            self.wav_ensemble_row.set_active(bool(s.get("is_wav_ensemble")))
            self.time_rate_row.set_value(float(s.get("time_stretch_rate") or 2.0))
            self.pitch_rate_row.set_value(float(s.get("pitch_rate") or 2.0))
            self.time_correction_row.set_active(bool(s.get("is_time_correction")))

            self.apollo_overlap_row.set_value(int(float(s.get("apollo_overlap") or 5)))
            self.apollo_chunk_row.set_value(int(float(s.get("apollo_chunk_size") or 10)))
            self.apollo_gpu_row.set_active(bool(s.get("is_gpu_conversion")))

            set_combo_value(self.time_window_row, s.get("time_window"))
            set_combo_value(self.intro_row, s.get("intro_analysis"))
            set_combo_value(self.db_row, s.get("db_analysis"))
            set_combo_value(self.phase_option_row, s.get("phase_option"))
            set_combo_value(self.phase_shifts_row, s.get("phase_shifts"))
            self.save_align_row.set_active(bool(s.get("is_save_align")))
            self.match_silence_row.set_active(bool(s.get("is_match_silence")))
            self.spec_match_row.set_active(bool(s.get("is_spec_match")))

            set_combo_value(self.format_row, s.get("save_format", WAV))
            set_combo_value(self.wav_type_row, s.get("wav_type_set"))
            self.normalize_row.set_active(bool(s.get("is_normalization")))
            self.testing_row.set_active(bool(s.get("is_testing_audio")))
        finally:
            self._loading = False

        self._refresh_apollo_models()
        self._sync_tool_visibility()
        self._refresh_dual_rows()

    def _sync_shared_from_settings(self) -> None:
        """Re-read the keys shared across tabs (inputs / output / format)."""
        self._loading = True
        try:
            apply_shared_file_options(
                self.settings,
                input_rows=(self.me_inputs_row, self.ts_inputs_row, self.ps_inputs_row, self.ap_inputs_row),
                output_row=self.output_row,
                format_row=self.format_row,
                gpu_row=self.apollo_gpu_row,
            )
        finally:
            self._loading = False

    def _sync_tool_visibility(self) -> None:
        self.tool_stack.set_visible_child_name(self._current_tool())

    def _refresh_dual_rows(self) -> None:
        labels = _TOOL_LABELS[1] if self._current_tool() == MATCH_INPUTS else _TOOL_LABELS[0]
        if self._dual_pairs:
            first = self._dual_pairs[0]
            extra = len(self._dual_pairs) - 1
            suffix = f"  (+{extra} pair(s))" if extra else ""
            sub_one = f"{os.path.basename(first[0])}{suffix}"
            sub_two = f"{os.path.basename(first[1])}{suffix}"
        else:
            sub_one = sub_two = "Not set"
        for file_one_row, file_two_row in self._dual_row_sets:
            file_one_row.set_title(labels[0])
            file_two_row.set_title(labels[1])
            set_row_subtitle(file_one_row, sub_one)
            set_row_subtitle(file_two_row, sub_two)

    # -- Signal handlers -------------------------------------------------------

    def _on_tool_changed(self, *_args) -> None:
        if self._loading:
            return
        tool = self._current_tool()
        self.settings.set("chosen_audio_tool", tool)
        self._sync_tool_visibility()
        self._refresh_dual_rows()

    def _on_inputs_changed(self) -> None:
        if self._loading:
            return
        page_rows = {
            MANUAL_ENSEMBLE: self.me_inputs_row,
            TIME_STRETCH: self.ts_inputs_row,
            CHANGE_PITCH: self.ps_inputs_row,
            APOLLO_RESTORE: self.ap_inputs_row,
        }
        row = page_rows.get(self._current_tool())
        if row is None:
            return
        paths = list(row.paths)
        self.settings.set("input_paths", paths)
        for other in page_rows.values():
            if other is not row:
                other.set_paths(paths, notify=False)

    def _on_output_changed(self) -> None:
        self._set("export_path", self.output_row.path)

    def _on_open_dual_editor(self, _button: Gtk.Button) -> None:
        labels = _TOOL_LABELS[1] if self._current_tool() == MATCH_INPUTS else _TOOL_LABELS[0]
        dialog = DualBatchDialog(self.window, labels, self._dual_pairs, self._on_dual_confirmed)
        dialog.present()

    def _on_dual_confirmed(self, pairs: List[Tuple[str, str]]) -> None:
        self._dual_pairs = [(str(a), str(b)) for a, b in pairs]
        self.settings.set("DualBatch_inputPaths", [list(p) for p in self._dual_pairs])
        if self._dual_pairs:
            first = self._dual_pairs[0]
            self.settings.set("fileOneEntry_Full", first[0])
            self.settings.set("fileTwoEntry_Full", first[1])
            self.settings.set("fileOneEntry", os.path.basename(first[0]))
            self.settings.set("fileTwoEntry", os.path.basename(first[1]))
        self._refresh_dual_rows()

    # -- Run target interface --------------------------------------------------

    def on_activated(self) -> None:
        # Audio Tools does not use ``chosen_process_method``; just keep the
        # shared input/output selection in step with the other tabs.
        self._sync_shared_from_settings()
        self._refresh_apollo_models()

    def on_deactivated(self) -> None:
        pass

    def start_blocked_reason(self) -> Optional[str]:
        """First reason the active tool can't start, or ``None`` when ready."""
        from uvr_core.audio_tools import DUAL_INPUT_TOOLS

        tool = self._current_tool()
        if tool in DUAL_INPUT_TOOLS:
            if not self._dual_pairs:
                return _REASON_DUAL_INPUTS
        else:
            page_rows = {
                MANUAL_ENSEMBLE: self.me_inputs_row,
                TIME_STRETCH: self.ts_inputs_row,
                CHANGE_PITCH: self.ps_inputs_row,
                APOLLO_RESTORE: self.ap_inputs_row,
            }
            row = page_rows.get(tool)
            single_inputs = list(row.paths) if row is not None else []
            if not single_inputs:
                return _REASON_INPUT
            if tool == MANUAL_ENSEMBLE and len(single_inputs) < 2:
                return _REASON_TWO_FILES
        if not os.path.isdir(self.output_row.path):
            return _REASON_OUTPUT
        if tool == APOLLO_RESTORE:
            return self._apollo_blocked_reason()
        return None

    def _apollo_blocked_reason(self) -> Optional[str]:
        """Side-effect-free Apollo readiness check (no toasts / dialogs)."""
        from uvr_core.apollo import list_apollo_models

        if not list_apollo_models():
            return _REASON_NO_APOLLO
        model_name = get_combo_value(self.apollo_model_row)
        if not model_name or model_name == CHOOSE_MODEL:
            return _REASON_APOLLO_MODEL
        return None

    def start(self, callbacks) -> None:
        # Input/output/tool readiness is validated by ``MainWindow._on_start``
        # before dispatch; the Apollo model resolution below still surfaces its
        # own dialog/toast for the deeper model-recognition cases.
        tool = self._current_tool()

        from uvr_core.audio_tools import DUAL_INPUT_TOOLS

        single_inputs: List[str] = []
        dual_pairs: List[Tuple[str, str]] = []
        apollo_params = None

        if tool in DUAL_INPUT_TOOLS:
            dual_pairs = list(self._dual_pairs)
        else:
            page_rows = {
                MANUAL_ENSEMBLE: self.me_inputs_row,
                TIME_STRETCH: self.ts_inputs_row,
                CHANGE_PITCH: self.ps_inputs_row,
                APOLLO_RESTORE: self.ap_inputs_row,
            }
            single_inputs = list(page_rows[tool].paths)
            if tool == APOLLO_RESTORE:
                apollo_params = self._resolve_apollo_model()
                if apollo_params is None:
                    return

        self.context.save_settings()
        self.window.begin_run(self)

        try:
            self.runner.start(tool, single_inputs, dual_pairs, callbacks, apollo_params=apollo_params)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.window.fail_to_start(f"Unable to start: {exc}", exc)

    def _resolve_apollo_model(self):
        """Resolve the selected Apollo model on the UI thread before the run.

        Returns ``{"extracted_params": ..., "config": ...}`` when the model is
        recognised (prompting for an unrecognized model's config yaml if needed),
        or ``None`` (after a toast) when no valid model is selected.
        """
        from uvr_core.apollo import ApolloModelData, list_apollo_models
        from ..dialogs.model_params import make_apollo_unrecognized_handler

        if not list_apollo_models():
            self._toast("No Apollo models found — add a checkpoint to the Apollo models folder first.")
            return None

        model_name = get_combo_value(self.apollo_model_row)
        if not model_name or model_name == CHOOSE_MODEL:
            self._toast("Select an Apollo model.")
            return None

        handler = make_apollo_unrecognized_handler(lambda: self.window)
        model_data = ApolloModelData(
            model_name,
            model_hash_table=self.context.repo.model_hash_table,
            on_unrecognized=handler,
        )
        if not model_data.is_model_status:
            self._toast(APOLLO_MODEL_FAIL_TEXT.strip())
            return None
        return {"extracted_params": model_data.extracted_params, "config": model_data.config}

    def stop(self) -> None:
        if self._runner is not None:
            self._runner.stop()

    def pause(self) -> None:
        if self._runner is not None:
            self._runner.pause()

    def unpause(self) -> None:
        if self._runner is not None:
            self._runner.unpause()

    # -- Misc ------------------------------------------------------------------

    def _on_open_apollo_folder(self, _banner: Adw.Banner) -> None:
        from uvr_core import paths

        os.makedirs(paths.APOLLO_MODELS_DIR, exist_ok=True)
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(paths.APOLLO_MODELS_DIR))
        launcher.launch(self.window, None, self._on_apollo_folder_launched)

    def _on_apollo_folder_launched(self, launcher: Gtk.FileLauncher, result) -> None:
        try:
            launcher.launch_finish(result)
        except GLib.Error as exc:
            self._toast(f"Couldn't open the Apollo models folder: {exc.message}")

    def _toast(self, message: str) -> None:
        self.window.toast(message)
