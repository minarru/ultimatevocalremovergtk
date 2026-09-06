"""Audio Tools page controller (GTK4 / libadwaita port of UVR's Audio Tools mode).

Refactored from a standalone ``Adw.Window`` into an embeddable *page controller*
hosted by the main window's ``content_stack`` (see
:class:`ui.window.MainWindow`). The page builds only its option groups in
the shared responsive two-column layout; the console, progress bar and
Start/Stop action bar are shared across all modes and supplied by the main
window via :meth:`AudioToolsPage.start`.

Layout mirrors Separation / Ensemble: a shared left **Files** group (multi-file
or dual-pair inputs + output folder), an untitled tool selector, tool-specific
settings in a stack, and a right **Processing** group for format options.

It offers the UVR audio tools as selectable sub-modes:

* **Manual Ensemble** - combine N files via the spectrogram/wave ensembler
  (``choose_algorithm``) or a straight ``Combine Inputs``.
* **Time Stretch** - rubberband time stretch by ``time_stretch_rate``.
* **Change Pitch** - rubberband pitch shift by ``pitch_rate`` semitones, with an
  optional ``is_time_correction`` toggle.
* **Align Inputs** - phase-aligned subtraction of two inputs with the full align
  advanced options, driven by the dual/batch editor.
* **Matchering** - reference-based mastering of (target, reference) pairs.

Heavy work runs on :class:`core.AudioToolRunner`'s ``KThread`` worker; all
progress / console / completion callbacks are marshaled onto the GTK main loop
through the caller-supplied callbacks (built with
:func:`ui.dispatch.gtk_job_callbacks`). Options bind to the shared typed
settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ui.run_error_context import RunErrorContext

if TYPE_CHECKING:
    from core.audio_plan import AudioJobSpec, ResolvedAudioJob
    from core.job_callbacks import JobCallbacks
    from core.job_plan import ResolvedJob
    from core.settings import Settings
import os
import typing
from typing import List, Optional, Tuple

from gi.repository import Adw, GObject, Gtk

from bundled.constants import (
    ALIGN_INPUTS,
    ALIGN_PHASE_OPTIONS,
    AMPLIFICATION_THRESHOLD_HELP,
    APOLLO_CHUNK_SIZE_HELP,
    APOLLO_MODEL_FAIL_TEXT,
    APOLLO_OVERLAP_HELP,
    APOLLO_RESTORE,
    AUDIO_TOOLS_HELP,
    CHANGE_PITCH,
    CHOOSE_APOLLO_MODEL_HELP,
    CHOOSE_MODEL,
    INPUT_FOLDER_ENTRY_HELP,
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
    OUTPUT_FOLDER_ENTRY_HELP,
    PHASE_SHIFTS_ALIGN_HELP,
    PHASE_SHIFTS_OPT,
    PITCH_SHIFT_HELP,
    TIME_STRETCH,
    TIME_WINDOW_ALIGN_HELP,
    TIME_WINDOW_MAPPER,
    VOLUME_ANALYSIS_ALIGN_HELP,
    VOLUME_MAPPER,
)

from ..help_text import (
    MANUAL_ENSEMBLE_ALGORITHM_HINT,
    PLAYBACK_RATE_HINT,
    VIEW_INPUTS_BUTTON_HINT,
)
from ..hints import HelpHintManager, set_icon_button_a11y, set_tooltip
from ..protocols import FormatEdit
from ..settings_bind import set_flat
from ..shared_settings import (
    SharedSettingsSession,
    apply_shared_file_options,
    shared_settings_bindings,
)
from ..template import load_builder, object_from_builder
from ..widgets.columns import build_columns_box, wrap_options_scroller
from ..widgets.dual_inputs import DualInputsRow
from ..widgets.file_chooser import InputFilesRow, OutputFolderRow
from ..widgets.format_row import OutputFormatRow
from ..widgets.rows import (
    configure_combo_row,
    get_combo_value,
    set_combo_tag_values,
    set_combo_value,
    use_wrapping_list,
)
from .dual_batch import DualBatchDialog

_MATCH_FILES_DESCRIPTION = "Target is mastered to match the reference track"
_ALIGN_FILES_DESCRIPTION = "Primary is usually the full mix; secondary is usually the instrumental"
_DUAL_BANNER_TITLE = "No input pairs selected. Open the pair editor to choose files."
_APOLLO_BANNER_TITLE = (
    "No Apollo models found. Get one from the Download Center, or place a "
    "checkpoint (.ckpt or .bin) in the Apollo models folder."
)
_RUBBERBAND_BANNER_TITLE = (
    "Rubber Band CLI was not found. Install rubberband to use Time Stretch "
    "or Change Pitch, then restart the app."
)

# Full tool list (Time Stretch / Change Pitch are surfaced on all platforms here;
# UVR hides them on Linux purely because pyrubberband may be unavailable - the
# backend reports that as a graceful error if the dep is missing).
AUDIO_TOOL_ORDER = (
    MANUAL_ENSEMBLE,
    TIME_STRETCH,
    CHANGE_PITCH,
    ALIGN_INPUTS,
    MATCH_INPUTS,
    APOLLO_RESTORE,
)

_TOOL_LABELS = (("File 1", "File 2"), ("Target", "Reference"))
LayoutObjectT = typing.TypeVar("LayoutObjectT", bound=GObject.Object)

#: Blocking-reason strings surfaced as the shared Start button tooltip when the
#: active audio tool is missing a required field.
_REASON_INPUT = "Select an input file"
_REASON_DUAL_INPUTS = "Add input pairs in the dual/batch editor"
_REASON_TWO_FILES = "Select two or more files"
_REASON_NO_APOLLO = "No Apollo models found"
_REASON_APOLLO_MODEL = "Select an Apollo model"
_REASON_RUBBERBAND = "Rubber Band CLI not found"


class AudioToolsPage:
    """Embeddable Audio Tools page bound to the shared :class:`AppContext`.

    Exposes the uniform "run target" interface the main window's shared
    Start/Stop dispatch expects: :attr:`widget`, :attr:`columns_box`,
    :meth:`start`, :meth:`stop`, :meth:`on_activated`, :meth:`on_deactivated`
    and :meth:`load`. Shared controls commit their edited fields live and flush
    pending edits before preflight/start. The main window persists settings via
    ``AppContext.save_settings`` on close.
    """

    def __init__(self, window: typing.Any, context: typing.Any):
        # ``window`` is the MainWindow; the page borrows it for toasts, dialog
        # parenting and the shared run-control helpers.
        self.window = window
        self.context = context
        self.settings = context.settings
        self._shared_session: SharedSettingsSession | None = None
        self._loading = False
        self._dual_pairs: List[Tuple[str, str]] = [
            (str(p[0]), str(p[1]))
            for p in (self.settings.audio_tools.dual_batch_input_paths or [])
            if len(p) == 2
        ]
        self._runner = None
        # Same per-view help-hint manager the separation method views use
        # (see ``ui.views.base.MethodView``), so Audio Tools tooltips are
        # registered through the identical ``HelpHintManager`` path.
        self.hints = HelpHintManager()
        self._apollo_has_models = True
        self._apollo_model_ids: set[str] = set()
        self._apollo_stored_value: typing.Any = CHOOSE_MODEL
        self._apollo_write_gated = False
        self._apollo_gated_value: typing.Any = None
        self._banner_mode: Optional[str] = None
        self._layout_builder = load_builder("audio-tools-page")

        # Match Separation / Ensemble: shared Files (inputs + output) on the
        # left, Processing on the right. Tool-specific settings stay in the
        # stack below the tool selector. Page-level banner covers dual/Apollo
        # empty states (same pattern as Separation / Ensemble).
        self.files_group = self._build_files_group()
        select_group = self._build_select_group()
        self.tool_stack = self._build_tool_stack()
        self.shared_group = self._build_shared_group()
        self._install_shared_session()

        self.columns_box, _, _ = build_columns_box(
            left_groups=(self.files_group, select_group, self.tool_stack),
            right_groups=(self.shared_group,),
        )
        self.options_page = wrap_options_scroller(self.columns_box)

        self._audio_banner = self._layout_object("audio_banner", Adw.Banner)
        self._audio_banner.connect("button-clicked", self._on_audio_banner_clicked)

        page = self._layout_object("page", Gtk.Box)
        page.append(self.options_page)
        self.widget = page

        self._sync_tool_visibility()

    @property
    def runner(self):
        if self._runner is None:
            from core.audio_tools import AudioToolRunner

            self._runner = AudioToolRunner(self.settings)
        return self._runner

    #: Label used when recording errors to the shared error log.
    @property
    def error_key(self) -> str:
        return self._current_tool()

    # -- Construction ----------------------------------------------------------

    def _layout_object(self, name: str, kind: type[LayoutObjectT]) -> LayoutObjectT:
        return object_from_builder(self._layout_builder, name, kind)

    def _build_files_group(self) -> Adw.PreferencesGroup:
        """Shared inputs + output folder, matching Separation / Ensemble."""
        group = self._layout_object("files_group", Adw.PreferencesGroup)
        self._view_inputs_button = self._layout_object("view_inputs_button", Gtk.Button)
        set_icon_button_a11y(self._view_inputs_button, VIEW_INPUTS_BUTTON_HINT)
        self._view_inputs_button.connect("clicked", self._on_view_inputs_clicked)

        self.inputs_row = InputFilesRow(
            self._on_inputs_changed,
            on_toast=self.window.toast,
            accept_any_getter=lambda: bool(self.settings.process.accept_any_input),
        )
        self.hints.register(self.inputs_row, INPUT_FOLDER_ENTRY_HELP)
        # Back-compat aliases for callers that still look up per-tool rows.
        self.me_inputs_row = self.inputs_row
        self.ts_inputs_row = self.inputs_row
        self.ps_inputs_row = self.inputs_row
        self.ap_inputs_row = self.inputs_row

        self.dual_inputs_row = DualInputsRow(self._on_open_dual_editor)
        self._dual_inputs_rows: List[DualInputsRow] = [self.dual_inputs_row]

        self.output_row = OutputFolderRow(self._on_output_changed, on_toast=self.window.toast)
        set_tooltip(self.output_row, OUTPUT_FOLDER_ENTRY_HELP)

        group.add(self.inputs_row)
        group.add(self.dual_inputs_row)
        group.add(self.output_row)
        return group

    def _build_select_group(self) -> Adw.PreferencesGroup:
        # Untitled group + row title (same de-chrome pattern as Separation method).
        select_group = self._layout_object("select_group", Adw.PreferencesGroup)
        self.tool_row = configure_combo_row(
            self._layout_object("tool_row", Adw.ComboRow),
            AUDIO_TOOL_ORDER,
        )
        self.hints.register(self.tool_row, AUDIO_TOOLS_HELP)
        self.tool_row.connect("notify::selected", self._on_tool_changed)
        return select_group

    def _build_tool_stack(self) -> Gtk.Stack:
        stack = self._layout_object("tool_stack", Gtk.Stack)
        self._build_manual_ensemble_page()
        self._build_time_stretch_page()
        self._build_pitch_page()
        self._build_align_page()
        # Matchering has no tool settings; stack page is omitted (Files copy covers it).
        self._build_apollo_page()
        return stack

    # -- Per-tool pages (settings only; inputs live in Files) ------------------

    def _build_manual_ensemble_page(self) -> Gtk.Widget:
        box = self._layout_object("manual_ensemble_page", Gtk.Box)
        self.algorithm_row = configure_combo_row(
            self._layout_object("algorithm_row", Adw.ComboRow), MANUAL_ENSEMBLE_OPTIONS
        )
        self.hints.register(self.algorithm_row, MANUAL_ENSEMBLE_ALGORITHM_HINT)
        self.algorithm_row.connect(
            "notify::selected",
            lambda *_a: self._set("choose_algorithm", get_combo_value(self.algorithm_row)),
        )

        self.wav_ensemble_row = self._layout_object("wav_ensemble_row", Adw.SwitchRow)
        self.hints.register(self.wav_ensemble_row, IS_WAV_ENSEMBLE_HELP)
        self.wav_ensemble_row.connect(
            "notify::active",
            lambda *_a: self._set("is_wav_ensemble", self.wav_ensemble_row.get_active()),
        )
        return box

    def _build_time_stretch_page(self) -> Gtk.Widget:
        box = self._layout_object("time_stretch_page", Gtk.Box)
        self.time_rate_row = self._layout_object("time_rate_row", Adw.SpinRow)
        self.hints.register(self.time_rate_row, PLAYBACK_RATE_HINT)
        self.time_rate_row.connect(
            "notify::value",
            lambda *_a: self._set("time_stretch_rate", round(self.time_rate_row.get_value(), 2)),
        )
        return box

    def _build_pitch_page(self) -> Gtk.Widget:
        box = self._layout_object("pitch_page", Gtk.Box)
        self.pitch_rate_row = self._layout_object("pitch_rate_row", Adw.SpinRow)
        self.hints.register(self.pitch_rate_row, PITCH_SHIFT_HELP)
        self.pitch_rate_row.connect(
            "notify::value",
            lambda *_a: self._set("pitch_rate", round(self.pitch_rate_row.get_value(), 2)),
        )

        self.time_correction_row = self._layout_object("time_correction_row", Adw.SwitchRow)
        self.hints.register(self.time_correction_row, IS_TIME_CORRECTION_HELP)
        self.time_correction_row.connect(
            "notify::active",
            lambda *_a: self._set("is_time_correction", self.time_correction_row.get_active()),
        )
        return box

    def _build_align_page(self) -> Gtk.Widget:
        box = self._layout_object("align_page", Gtk.Box)
        self.time_window_row = configure_combo_row(
            self._layout_object("time_window_row", Adw.ComboRow),
            list(TIME_WINDOW_MAPPER.keys()),
        )
        self.hints.register(self.time_window_row, TIME_WINDOW_ALIGN_HELP)
        self.time_window_row.connect(
            "notify::selected",
            lambda *_a: self._set("time_window", get_combo_value(self.time_window_row)),
        )

        self.intro_row = configure_combo_row(
            self._layout_object("intro_row", Adw.ComboRow), list(INTRO_MAPPER.keys())
        )
        self.hints.register(self.intro_row, INTRO_ANALYSIS_ALIGN_HELP)
        self.intro_row.connect(
            "notify::selected",
            lambda *_a: self._set("intro_analysis", get_combo_value(self.intro_row)),
        )

        self.db_row = configure_combo_row(
            self._layout_object("db_row", Adw.ComboRow), list(VOLUME_MAPPER.keys())
        )
        self.hints.register(self.db_row, VOLUME_ANALYSIS_ALIGN_HELP)
        self.db_row.connect(
            "notify::selected", lambda *_a: self._set("db_analysis", get_combo_value(self.db_row))
        )

        self.phase_option_row = configure_combo_row(
            self._layout_object("phase_option_row", Adw.ComboRow), ALIGN_PHASE_OPTIONS
        )
        self.hints.register(self.phase_option_row, IS_PHASE_HELP)
        self.phase_option_row.connect(
            "notify::selected",
            lambda *_a: self._set("phase_option", get_combo_value(self.phase_option_row)),
        )

        self.phase_shifts_row = configure_combo_row(
            self._layout_object("phase_shifts_row", Adw.ComboRow),
            list(PHASE_SHIFTS_OPT.keys()),
        )
        self.hints.register(self.phase_shifts_row, PHASE_SHIFTS_ALIGN_HELP)
        self.phase_shifts_row.connect(
            "notify::selected",
            lambda *_a: self._set("phase_shifts", get_combo_value(self.phase_shifts_row)),
        )

        self.save_align_row = self._layout_object("save_align_row", Adw.SwitchRow)
        self.hints.register(self.save_align_row, IS_ALIGN_TRACK_HELP)
        self.save_align_row.connect(
            "notify::active",
            lambda *_a: self._set("is_save_align", self.save_align_row.get_active()),
        )

        self.match_silence_row = self._layout_object("match_silence_row", Adw.SwitchRow)
        self.hints.register(self.match_silence_row, IS_MATCH_SILENCE_HELP)
        self.match_silence_row.connect(
            "notify::active",
            lambda *_a: self._set("is_match_silence", self.match_silence_row.get_active()),
        )

        self.spec_match_row = self._layout_object("spec_match_row", Adw.SwitchRow)
        self.hints.register(self.spec_match_row, IS_MATCH_SPEC_HELP)
        self.spec_match_row.connect(
            "notify::active",
            lambda *_a: self._set("is_spec_match", self.spec_match_row.get_active()),
        )
        return box

    def _build_apollo_page(self) -> Gtk.Widget:
        box = self._layout_object("apollo_page", Gtk.Box)
        self.apollo_group = self._layout_object("apollo_group", Adw.PreferencesGroup)
        apollo_folder_button = self._layout_object("apollo_folder_button", Gtk.Button)
        set_icon_button_a11y(apollo_folder_button, "Open Apollo models folder")
        apollo_folder_button.connect("clicked", self._on_open_apollo_folder)

        self.apollo_model_row = configure_combo_row(
            self._layout_object("apollo_model_row", Adw.ComboRow), [CHOOSE_MODEL]
        )
        use_wrapping_list(self.apollo_model_row)
        self.hints.register(self.apollo_model_row, CHOOSE_APOLLO_MODEL_HELP)
        self.apollo_model_row.connect("notify::selected", self._on_apollo_model_changed)

        self.apollo_overlap_row = self._layout_object("apollo_overlap_row", Adw.SpinRow)
        self.hints.register(self.apollo_overlap_row, APOLLO_OVERLAP_HELP)
        self.apollo_overlap_row.connect(
            "notify::value",
            lambda *_a: self._set("apollo_overlap", int(self.apollo_overlap_row.get_value())),
        )
        self.apollo_chunk_row = self._layout_object("apollo_chunk_row", Adw.SpinRow)
        self.hints.register(self.apollo_chunk_row, APOLLO_CHUNK_SIZE_HELP)
        self.apollo_chunk_row.connect(
            "notify::value",
            lambda *_a: self._set("apollo_chunk_size", int(self.apollo_chunk_row.get_value())),
        )
        return box

    def _on_apollo_model_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        selected = get_combo_value(self.apollo_model_row)
        if selected not in self._apollo_model_ids:
            return
        self._apollo_stored_value = selected
        self._apollo_write_gated = False
        self._apollo_gated_value = None
        self._set("apollo_model", selected)
        self._update_audio_banner()
        self.window._refresh_start_readiness()

    def refresh_models(self) -> None:
        """Uniform hook for ``MainWindow._model_list_consumers``."""
        self._refresh_apollo_models()

    def refresh_apollo_models(self) -> None:
        """Public hook: re-read Apollo models after a Download Center batch."""
        self._refresh_apollo_models()

    def _refresh_apollo_models(self) -> None:
        """Repopulate the Apollo model picker from the models on disk."""
        from core.apollo import list_apollo_models
        from core.model_identity import ModelIdentityService

        found = list_apollo_models()
        identities = ModelIdentityService(self.context.repo)
        records = [
            record
            for record in identities.records()
            if record.family == "apollo" and record.installed
        ]
        models = [CHOOSE_MODEL, *((record.id, record.display) for record in records)]
        stored = self.settings.audio_tools.apollo_model or CHOOSE_MODEL
        ids = {record.id for record in records}
        self._apollo_model_ids = ids
        if not (self._apollo_write_gated and stored == self._apollo_gated_value):
            self._apollo_write_gated = False
            self._apollo_gated_value = None
        # Mirrors ``MethodView.populate_models``: a stored value that is not one
        # of this picker's installed IDs shows as no selection and is left on
        # disk exactly as written. Resolving it here and writing the result back
        # would let a refresh silently convert a legacy value -- which is what
        # the identity cutover forbids.
        if not self._apollo_write_gated:
            self._apollo_write_gated = stored not in (CHOOSE_MODEL, None, "") and (
                not isinstance(stored, str) or stored not in ids
            )
            if self._apollo_write_gated:
                self._apollo_gated_value = stored
        self._apollo_stored_value = stored
        selected = CHOOSE_MODEL if self._apollo_write_gated else stored
        was_loading = self._loading
        self._loading = True
        try:
            set_combo_tag_values(self.apollo_model_row, models)
            if not set_combo_value(self.apollo_model_row, selected):
                self.apollo_model_row.set_selected(0)
        finally:
            self._loading = was_loading

        self._apollo_has_models = bool(found)
        self.apollo_group.set_visible(self._apollo_has_models)
        self._update_audio_banner()

    def _build_shared_group(self) -> Gtk.Widget:
        group = self._layout_object("processing_group", Adw.PreferencesGroup)

        self.format_row = OutputFormatRow(self._on_format_changed)
        group.add(self.format_row)

        # Shown only for Apollo (GPU-accelerated audio tool).
        self.apollo_gpu_row = self._layout_object("apollo_gpu_row", Adw.SwitchRow)
        self.hints.register(self.apollo_gpu_row, IS_GPU_CONVERSION_HELP)
        self.apollo_gpu_row.connect(
            "notify::active",
            self._on_gpu_changed,
        )
        group.add(self.apollo_gpu_row)

        self.normalize_row = self._layout_object("normalize_row", Adw.SwitchRow)
        self.hints.register(self.normalize_row, IS_NORMALIZATION_HELP)
        self.normalize_row.connect(
            "notify::active",
            lambda *_a: self._set("is_normalization", self.normalize_row.get_active()),
        )
        group.add(self.normalize_row)

        self.amplification_row = self._layout_object("amplification_row", Adw.SpinRow)
        self.hints.register(self.amplification_row, AMPLIFICATION_THRESHOLD_HELP)
        self.amplification_row.connect(
            "notify::value",
            lambda *_a: self._set(
                "amplification_threshold", float(self.amplification_row.get_value())
            ),
        )
        group.add(self.amplification_row)

        self.testing_row = self._layout_object("testing_row", Adw.SwitchRow)
        self.hints.register(self.testing_row, IS_TESTING_AUDIO_HELP)
        self.testing_row.connect(
            "notify::active",
            lambda *_a: self._set("is_testing_audio", self.testing_row.get_active()),
        )
        group.add(self.testing_row)

        return group

    # -- Settings load / persist -----------------------------------------------

    def _set(self, key: str, value: typing.Any) -> None:
        if self._loading:
            return
        set_flat(self.settings, key, value)

    def _current_tool(self) -> str:
        return get_combo_value(self.tool_row) or MANUAL_ENSEMBLE

    def load(self) -> None:
        self._loading = True
        try:
            s = self.settings
            from ..settings_bind import setting_for_combo

            set_combo_value(
                self.tool_row,
                setting_for_combo("chosen_audio_tool", s.get("chosen_audio_tool", MANUAL_ENSEMBLE)),
            )

            self._sync_shared_from_settings()

            set_combo_value(
                self.algorithm_row,
                setting_for_combo("choose_algorithm", s.get("choose_algorithm")),
            )
            self.wav_ensemble_row.set_active(bool(s.get("is_wav_ensemble")))
            self.time_rate_row.set_value(float(s.get("time_stretch_rate") or 2.0))
            self.pitch_rate_row.set_value(float(s.get("pitch_rate", 2.0)))
            self.time_correction_row.set_active(bool(s.get("is_time_correction")))

            self.apollo_overlap_row.set_value(int(float(s.get("apollo_overlap", 5))))
            self.apollo_chunk_row.set_value(int(float(s.get("apollo_chunk_size") or 10)))

            set_combo_value(
                self.time_window_row,
                setting_for_combo("time_window", s.get("time_window")),
            )
            set_combo_value(
                self.intro_row,
                setting_for_combo("intro_analysis", s.get("intro_analysis")),
            )
            set_combo_value(self.db_row, setting_for_combo("db_analysis", s.get("db_analysis")))
            set_combo_value(
                self.phase_option_row,
                setting_for_combo("phase_option", s.get("phase_option")),
            )
            set_combo_value(
                self.phase_shifts_row,
                setting_for_combo("phase_shifts", s.get("phase_shifts")),
            )
            self.save_align_row.set_active(bool(s.get("is_save_align")))
            self.match_silence_row.set_active(bool(s.get("is_match_silence")))
            self.spec_match_row.set_active(bool(s.get("is_spec_match")))

            self.normalize_row.set_active(bool(s.get("is_normalization")))
            try:
                amp = float(s.get("amplification_threshold") or 0.0)
            except (TypeError, ValueError):
                amp = 0.0
            self.amplification_row.set_value(max(0.0, min(1.0, amp)))
            self.testing_row.set_active(bool(s.get("is_testing_audio")))
        finally:
            self._loading = False

        self._refresh_apollo_models()
        self._sync_tool_visibility()
        self._refresh_dual_rows()

    def _install_shared_session(self) -> None:
        self._shared_session = SharedSettingsSession(
            self.settings,
            shared_settings_bindings(
                input_row=self.inputs_row,
                output_row=self.output_row,
                format_row=self.format_row,
                gpu_row=self.apollo_gpu_row,
            ),
            can_commit=lambda: self.window.content_stack.get_visible_child_name() == "audio_tools",
        )

    def _apply_shared_widgets(self) -> None:
        apply_shared_file_options(
            self.settings,
            input_row=self.inputs_row,
            output_row=self.output_row,
            format_row=self.format_row,
            gpu_row=self.apollo_gpu_row,
        )

    def _sync_shared_from_settings(self) -> None:
        """Refresh displayed baselines without creating shared edits."""
        assert self._shared_session is not None
        self._shared_session.refresh(self._apply_shared_widgets)

    def sync_processing_from_settings(self) -> None:
        """Re-read the Processing-group rows Preferences can edit directly.

        ``_sync_shared_from_settings`` only covers the block shared with every
        tab (inputs/output/format/GPU/sample mode); normalization and the
        amplification threshold are Audio-Tools-only rows that Preferences can
        still edit (see ``ui/preferences.py``), so the light resync used after
        applying Preferences (``MainWindow._sync_after_preferences``) needs its
        own pass to keep them from going stale for the rest of the session.
        """
        self._loading = True
        try:
            s = self.settings
            self.normalize_row.set_active(bool(s.get("is_normalization")))
            try:
                amp = float(s.get("amplification_threshold") or 0.0)
            except (TypeError, ValueError):
                amp = 0.0
            self.amplification_row.set_value(max(0.0, min(1.0, amp)))
        finally:
            self._loading = False

    def _sync_tool_visibility(self) -> None:
        tool = self._current_tool()
        # Matchering has no tool settings page; hide the empty stack slot.
        has_settings = tool != MATCH_INPUTS
        self.tool_stack.set_visible(has_settings)
        if has_settings:
            self.tool_stack.set_visible_child_name(tool)
        self.apollo_gpu_row.set_visible(tool == APOLLO_RESTORE)
        self._sync_files_visibility(tool)
        self._update_audio_banner()

    def _sync_files_visibility(self, tool: Optional[str] = None) -> None:
        """Show multi-file or dual-pair inputs depending on the active tool."""
        from core.audio_tools import DUAL_INPUT_TOOLS

        tool = tool or self._current_tool()
        dual = tool in DUAL_INPUT_TOOLS
        self.inputs_row.set_visible(not dual)
        self.dual_inputs_row.set_visible(dual)
        if tool == MATCH_INPUTS:
            self.files_group.set_description(_MATCH_FILES_DESCRIPTION)
        elif tool == ALIGN_INPUTS:
            self.files_group.set_description(_ALIGN_FILES_DESCRIPTION)
        else:
            self.files_group.set_description(None)

    def _update_audio_banner(self) -> None:
        """Page-level empty-state banner for Apollo models / dual input pairs."""
        from core.audio_tools import DUAL_INPUT_TOOLS
        from core.external_tools import resolve_rubberband

        tool = self._current_tool()
        if tool == APOLLO_RESTORE and self._apollo_write_gated:
            self._banner_mode = "apollo-identity"
            self._audio_banner.set_title(
                f"Saved Apollo model {self._apollo_stored_value!r} cannot be "
                "selected; it was kept as written. Pick a model to replace it."
            )
            self._audio_banner.set_button_label("")
            self._audio_banner.set_revealed(True)
            self.window._refresh_start_readiness()
            return
        if tool in (TIME_STRETCH, CHANGE_PITCH) and not resolve_rubberband():
            self._banner_mode = "rubberband"
            self._audio_banner.set_title(_RUBBERBAND_BANNER_TITLE)
            self._audio_banner.set_button_label("")
            self._audio_banner.set_revealed(True)
            self.window._refresh_start_readiness()
            return
        if tool == APOLLO_RESTORE and not self._apollo_has_models:
            self._banner_mode = "apollo"
            self._audio_banner.set_title(_APOLLO_BANNER_TITLE)
            self._audio_banner.set_button_label("Download Center")
            self._audio_banner.set_revealed(True)
            self.window._refresh_start_readiness()
            return
        if tool in DUAL_INPUT_TOOLS and not self._dual_pairs:
            self._banner_mode = "dual"
            self._audio_banner.set_title(_DUAL_BANNER_TITLE)
            self._audio_banner.set_button_label("Pair Editor")
            self._audio_banner.set_revealed(True)
            self.window._refresh_start_readiness()
            return
        self._banner_mode = None
        self._audio_banner.set_revealed(False)
        self.window._refresh_start_readiness()

    def _on_audio_banner_clicked(self, *_args: typing.Any) -> None:
        if self._banner_mode == "apollo":
            # Apollo models are downloadable now, so the empty state sends users
            # to Restore with the Apollo network filter. Manual placement stays
            # available via the folder button in the Apollo group header (shown
            # once a model exists) and the Download Center's own
            # "Open models folder".
            from bundled.constants import APOLLO_ARCH_TYPE
            from core.model_scores import download_center_hint_for_method

            from ..download import open_download_center

            purpose, arch = download_center_hint_for_method(APOLLO_ARCH_TYPE)
            open_download_center(
                self.window,
                self.context,
                purpose=purpose,
                arch=arch,
            )
        elif self._banner_mode == "dual":
            self._on_open_dual_editor()

    def _on_view_inputs_clicked(self, *_args: typing.Any) -> None:
        """Open the pair editor for dual tools; otherwise the shared verifier."""
        from core.audio_tools import DUAL_INPUT_TOOLS

        if self._current_tool() in DUAL_INPUT_TOOLS:
            self._on_open_dual_editor()
            return
        self.window.activate_action("win.view_inputs", None)

    def _refresh_dual_rows(self) -> None:
        labels = _TOOL_LABELS[1] if self._current_tool() == MATCH_INPUTS else _TOOL_LABELS[0]
        for row in self._dual_inputs_rows:
            row.set_pairs(self._dual_pairs, labels)
        self._update_audio_banner()

    # -- Signal handlers -------------------------------------------------------

    def _on_tool_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        tool = self._current_tool()
        from core.settings.coerce import coerce_field

        self.settings.audio_tools.chosen_audio_tool = coerce_field(
            "audio_tools", "chosen_audio_tool", tool
        )
        self._sync_tool_visibility()
        self._refresh_dual_rows()

    def _on_gpu_changed(self, *_args: typing.Any) -> None:
        session = self._shared_session
        if session is None or not session.editable:
            return
        session.commit(edited=(session.bindings.use_gpu,))

    def _on_format_changed(self, event: FormatEdit) -> None:
        session = self._shared_session
        if session is None or not session.editable:
            return
        session.format_changed(event)

    def _on_inputs_changed(self) -> None:
        session = self._shared_session
        if session is None or not session.editable:
            return
        session.commit(edited=(session.bindings.input_paths,))
        self.context.prune_unreadable_input_paths(list(self.inputs_row.paths))
        self.window._refresh_start_readiness()

    def _on_output_changed(self) -> None:
        session = self._shared_session
        if session is None or not session.editable:
            return
        session.commit(edited=(session.bindings.export_path,))
        self.window._refresh_start_readiness()

    def _on_open_dual_editor(self, *_args: typing.Any) -> None:
        labels = _TOOL_LABELS[1] if self._current_tool() == MATCH_INPUTS else _TOOL_LABELS[0]
        dialog = DualBatchDialog(self.window, labels, self._dual_pairs, self._on_dual_confirmed)
        dialog.present()

    def _on_dual_confirmed(self, pairs: List[Tuple[str, str]]) -> None:
        self._dual_pairs = [(str(a), str(b)) for a, b in pairs]
        self.settings.audio_tools.dual_batch_input_paths = [list(p) for p in self._dual_pairs]
        if self._dual_pairs:
            first = self._dual_pairs[0]
            self.settings.audio_tools.file_one_entry_full = first[0]
            self.settings.audio_tools.file_two_entry_full = first[1]
            self.settings.audio_tools.file_one_entry = os.path.basename(first[0])
            self.settings.audio_tools.file_two_entry = os.path.basename(first[1])
        self._refresh_dual_rows()

    # -- Run target interface --------------------------------------------------

    def on_activated(self) -> None:
        # Audio Tools does not use ``chosen_process_method``; just keep the
        # shared input/output selection in step with the other tabs.
        self._sync_shared_from_settings()
        self.sync_processing_from_settings()
        self._refresh_apollo_models()
        self._sync_tool_visibility()
        self._refresh_dual_rows()

    def on_deactivated(self) -> None:
        pass

    def start_blocked_reason(self) -> Optional[str]:
        """First reason the active tool can't start, or ``None`` when ready."""
        from core.audio_tools import DUAL_INPUT_TOOLS

        tool = self._current_tool()
        if tool in (TIME_STRETCH, CHANGE_PITCH):
            from core.external_tools import resolve_rubberband

            if not resolve_rubberband():
                return _REASON_RUBBERBAND
        if tool in DUAL_INPUT_TOOLS:
            if not self._dual_pairs:
                return _REASON_DUAL_INPUTS
        else:
            input_reason = self.inputs_row.blocked_reason(
                unreadable_paths=self.context.unreadable_input_paths
            )
            if input_reason:
                return input_reason
            if tool == MANUAL_ENSEMBLE and len(self.inputs_row.paths) < 2:
                return _REASON_TWO_FILES
        output_reason = self.output_row.blocked_reason()
        if output_reason:
            return output_reason
        if tool == APOLLO_RESTORE:
            return self._apollo_blocked_reason()
        return None

    def build_job_spec(self) -> AudioJobSpec:
        """Snapshot the active Audio Tools page for shared runtime preflight."""
        import copy

        from core.audio_plan import AudioJobSpec
        from core.audio_tools import DUAL_INPUT_TOOLS

        assert self._shared_session is not None
        self._shared_session.commit()
        settings = copy.deepcopy(self.settings)
        settings.process.export_path = self.output_row.path
        tool = self._current_tool()
        if tool in DUAL_INPUT_TOOLS:
            inputs: tuple[str, ...] = ()
            pairs = tuple((str(left), str(right)) for left, right in self._dual_pairs)
        else:
            inputs = tuple(str(path) for path in self.inputs_row.paths)
            pairs = ()
        return AudioJobSpec(
            tool=tool,
            settings=settings,
            output=self.output_row.path,
            inputs=inputs,
            pairs=pairs,
            provenance={"profile": "gui"},
        )

    def _apollo_blocked_reason(self) -> Optional[str]:
        """Side-effect-free Apollo readiness check (no toasts / dialogs)."""
        from core.apollo import list_apollo_models

        if not list_apollo_models():
            return _REASON_NO_APOLLO
        model_name = get_combo_value(self.apollo_model_row)
        if not model_name or model_name == CHOOSE_MODEL:
            return _REASON_APOLLO_MODEL
        return None

    def start(
        self, callbacks: JobCallbacks, plan: ResolvedJob | ResolvedAudioJob | None = None
    ) -> None:
        assert self._shared_session is not None
        self._shared_session.commit()
        # Input/output/tool readiness is validated by ``MainWindow._on_start``
        # before dispatch; the Apollo model resolution below still surfaces its
        # own dialog/toast for the deeper model-recognition cases.
        tool = self._current_tool()

        from core.audio_tools import DUAL_INPUT_TOOLS

        single_inputs: List[str] = []
        dual_pairs: List[Tuple[str, str]] = []
        apollo_params = None

        if tool in DUAL_INPUT_TOOLS:
            dual_pairs = list(self._dual_pairs)
        else:
            single_inputs = list(self.inputs_row.paths)
            if tool == APOLLO_RESTORE:
                audio_plan = typing.cast("ResolvedAudioJob | None", plan)
                planned_model = audio_plan.model if audio_plan is not None else None
                backend_name = planned_model.backend_name if planned_model is not None else None
                apollo_params = self._resolve_apollo_model(backend_name)
                if apollo_params is None:
                    return
                self.runner.apollo_backend_name = backend_name

        self.window.begin_run(self)

        try:
            error = self.context.try_save_settings(trigger="audio-tools-start")
            if error:
                self._toast(error)
            from core.debug_log import debug

            debug(
                "ui",
                f"audio_tools start tool={tool!r} singles={len(single_inputs)} pairs={len(dual_pairs)}",
            )
            self.runner.start(
                tool, single_inputs, dual_pairs, callbacks, apollo_params=apollo_params
            )
        except Exception as exc:  # surfaced to the user
            self.window.fail_to_start(f"Unable to start: {exc}", exc)

    def _resolve_apollo_model(self, planned_backend_name: str | None = None):
        """Resolve the selected Apollo model on the UI thread before the run.

        Returns ``{"extracted_params": ..., "config": ...}`` when the model is
        recognised (prompting for an unrecognized model's config yaml if needed),
        or ``None`` (after a toast) when no valid model is selected.
        """
        from core.apollo import ApolloModelData, list_apollo_models

        from ..dialogs.model_params import make_apollo_unrecognized_handler

        if not list_apollo_models():
            self._toast(
                "No Apollo models found — add a checkpoint to the Apollo models folder first."
            )
            return None

        model_name = get_combo_value(self.apollo_model_row)
        if not model_name or model_name == CHOOSE_MODEL:
            self._toast("Select an Apollo model.")
            return None

        handler = make_apollo_unrecognized_handler(lambda: self.window)
        from core.model_identity import ModelIdentityService

        backend_name = planned_backend_name or ModelIdentityService(self.context.repo).engine_value(
            model_name, family="apollo"
        )
        model_data = ApolloModelData(
            backend_name,
            model_hash_table=self.context.repo.model_hash_table,
            on_unrecognized=handler,
        )
        if not model_data.is_model_status:
            self._toast(APOLLO_MODEL_FAIL_TEXT.strip())
            return None
        return {"extracted_params": model_data.extracted_params, "config": model_data.config}

    run_label = 'Audio tools'

    def worker_is_running(self) -> bool:
        return self.runner.is_running()

    def snapshot_error_context(self) -> RunErrorContext:
        from core.audio_tools import DUAL_INPUT_TOOLS
        from core.error_context import build_audio_tools_context

        tool = self._current_tool()
        paths = (
            [os.path.basename(left) for left, _right in self._dual_pairs]
            if tool in DUAL_INPUT_TOOLS
            else list(self.inputs_row.paths)
        )
        return RunErrorContext.from_fields(build_audio_tools_context(self.settings, tool, paths))

    def bind_run_settings(self, settings: Settings) -> None:
        import copy

        self.runner.settings = copy.deepcopy(settings)

    def restore_runner_settings(self) -> None:
        if self._runner is not None:
            self._runner.settings = self.settings

    def stop_started_worker(self, *, force: bool = False) -> None:
        if self._runner is not None:
            self._runner.stop(force=force)

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
        from core import paths

        try:
            os.makedirs(paths.APOLLO_MODELS_DIR, exist_ok=True)
        except OSError as exc:
            self._toast(f"Couldn't create Apollo models folder: {exc}")
            return
        from ..files import open_folder_in_file_manager

        open_folder_in_file_manager(self.window, paths.APOLLO_MODELS_DIR, on_error=self._toast)

    def _toast(self, message: str) -> None:
        self.window.toast(message)
