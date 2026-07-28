"""Ensemble Mode page controller (GTK4 / libadwaita).

Port of UVR's ensemble surface, refactored from a standalone ``Adw.Window`` into
an embeddable *page controller* that lives inside the main window's
``content_stack`` (see :class:`ui.window.MainWindow`). The page owns only
its option groups (laid out in the shared responsive two-column layout); the
console, progress bar and Start/Stop action bar are shared with every other mode
and supplied by the main window via :meth:`EnsemblePage.start`.

Pick the ensemble main-stem pair and combination algorithm, multi-select the
member models, manage saved ensembles, and run all members through
:class:`core.JobRunner` so their outputs are combined by the
:class:`core.Ensembler`. Worker-thread callbacks are marshaled onto the GTK
main loop by the caller-supplied callbacks (built with
:func:`ui.dispatch.gtk_job_callbacks`), so GTK is never touched off the main
thread.

Every control binds to the same settings keys the Tk app uses
(``ensemble_main_stem`` / ``ensemble_type`` / ``selected_models`` /
``chosen_ensemble`` / ``is_save_all_outputs_ensemble`` / ...), so saved
ensembles are interchangeable with ``UVR.py``.
"""

import os
from typing import Dict, List, Optional

from gi.repository import Adw, Gtk

from core.run_estimate import (
    compose_stem_group_tooltip,
    ensemble_export_summary,
    estimate_workload,
    format_workload_line,
)
from core.model_stem_semantics import recommended_export_note, stem_display_overrides
from bundled.constants import (
    CHUNK_MIN,
    CHOOSE_ENSEMBLE_OPTION,
    CHOOSE_STEM_PAIR,
    ENSEMBLE_ALGORITHMS,
    ENSEMBLE_LISTBOX_HELP,
    ENSEMBLE_MAIN_STEM,
    ENSEMBLE_MAIN_STEM_HELP,
    ENSEMBLE_MODE,
    ENSEMBLE_PARTITION,
    ENSEMBLE_TYPE_HELP,
    FOUR_STEM_ENSEMBLE,
    IS_APPEND_ENSEMBLE_NAME_HELP,
    IS_AUTOCAST_HELP,
    IS_GPU_CONVERSION_HELP,
    INPUT_FOLDER_ENTRY_HELP,
    IS_SAVE_ALL_OUTPUTS_ENSEMBLE_HELP,
    IS_WAV_ENSEMBLE_HELP,
    MAX_MIN,
    MODEL_SAMPLE_MODE_HELP,
    OUTPUT_FOLDER_ENTRY_HELP,
    MULTI_STEM_ENSEMBLE,
    SAVE_STEM_ONLY_HELP,
)
from core.ensemble_algorithms import (
    ENSEMBLE_PRESET_OPTIONS,
    algorithm_blurb,
    algorithm_row_titles,
    ensemble_options_summary,
    format_ensemble_type,
    model_row_matches_query,
    models_selection_status,
    pair_for_preset,
    parse_ensemble_type,
    preset_for_pair,
    wav_ensemble_subtitle,
)

from ..dialogs.utils import present_modal_dialog, set_dialog_content
from ..spacing import inset_md
from ..help_text import (
    ENSEMBLE_DELETE_BUTTON_HINT,
    ENSEMBLE_MEMBER_MODEL_OPTIONS_HINT,
    ENSEMBLE_SAVE_BUTTON_HINT,
    ENSEMBLE_SAVED_PRESET_HINT,
    RUN_WORKLOAD_HINT,
    VIEW_INPUTS_BUTTON_HINT,
)
from ..hints import set_icon_button_a11y, set_tooltip
from ..markup import set_row_subtitle, set_row_title
from core.model_display import format_tag_subtitle, format_tag_title
from core import (
    delete_ensemble,
    list_saved_ensembles,
    load_ensemble,
    save_ensemble,
)
from core.ensemble_presets import (
    classify_preset_members,
    curated_combo_label,
    curated_id_from_combo_label,
    download_entries_for_missing,
    is_curated_combo_label,
    list_curated_ensembles,
    load_curated_ensemble,
    resolve_member_tags,
)

from ..widgets.columns import build_columns_box, wrap_options_scroller
from ..widgets.file_chooser import InputFilesRow, OutputFolderRow
from ..widgets.format_row import OutputFormatRow
from ..widgets.vocal_split_row import VocalSplitRow
from ..shared_settings import (
    SAMPLE_MODE_TITLE,
    apply_sample_mode_label,
    apply_shared_file_options,
    gpu_dependent_enabled,
    sample_mode_subtitle,
)
from ..widgets.rows import (
    get_combo_value,
    make_combo_row,
    make_switch_row,
    set_combo_value,
    set_combo_values,
)
from ..widgets.stem_only import SaveStemsSection

_PRIMARY_STEM_ONLY_KEY = "is_primary_stem_only"
_SECONDARY_STEM_ONLY_KEY = "is_secondary_stem_only"

#: Blocking-reason strings surfaced as the shared Start button tooltip (and
#: reused as the safety-net toasts in :meth:`EnsemblePage.start`).
_REASON_STEM_PAIR = "Choose an ensemble stem pair"
_REASON_TWO_MODELS = "Select two or more models"


class _RowTooltipHints:
    """Adapts :class:`VocalSplitRow`'s ``hints.register(widget, text)`` calls
    to this page's plain :func:`set_tooltip` hinting.

    ``EnsemblePage`` has no :class:`~ui.hints.HelpHintManager` -- every other
    row here is hinted with a direct ``set_tooltip`` call -- so this is a
    stateless one-off adapter rather than pulling in the manager.
    """

    def register(self, widget, text):
        set_tooltip(widget, text)
        return widget


class EnsemblePage:
    """Embeddable Ensemble Mode page bound to the shared :class:`AppContext`.

    The page exposes the uniform "run target" interface the main window's shared
    Start/Stop dispatch expects: :attr:`widget` (the page surface), :attr:`columns_box`
    (registered with the responsive breakpoint), :meth:`start`, :meth:`stop`,
    :meth:`on_activated`, :meth:`on_deactivated` and :meth:`load`. Every control
    writes its settings key live on change, so there is no separate flush step;
    the main window persists everything via ``AppContext.save_settings`` on close.
    """

    #: Label used when recording errors to the shared error log.
    error_key = ENSEMBLE_MODE

    def __init__(self, window, context):
        # ``window`` is the MainWindow; the page borrows it for toasts, dialog
        # parenting and the shared run-control helpers.
        self.window = window
        self.context = context
        self.settings = context.settings
        self._loading = False
        self._syncing_preset = False
        self._model_checks: Dict[str, Gtk.CheckButton] = {}
        self._model_row_text: Dict[str, tuple[str, str]] = {}

        # Distribute the groups across the shared two-column layout. The member
        # model checklist now lives in a modal dialog opened from a compact
        # trigger row inside "Ensemble options", so the left column carries the
        # Files and Ensemble panels while the shorter stem/output/advanced
        # groups balance the right column.
        files_group = self._build_files_group()
        ensemble_group = self._build_ensemble_group()
        stems_group = self._build_stems_group()
        output_group = self._build_output_group()

        self.columns_box, self._col_start, self._col_end = build_columns_box(
            left_groups=(files_group, ensemble_group),
            right_groups=(stems_group, output_group),
        )

        # Proactive empty-state hint mirroring the Separation page: a full-width
        # banner above the columns that surfaces the ensemble-configuration
        # blocker (stem pair / member models) and auto-hides once the run is
        # ready. Refreshed from ``_update_ensemble_banner`` on stem/model change.
        self._ensemble_banner = Adw.Banner(revealed=False)
        self.options_page = wrap_options_scroller(self.columns_box)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.set_vexpand(True)
        page.append(self._ensemble_banner)
        page.append(self.options_page)
        self.widget = page

    # -- Construction -----------------------------------------------------------

    def _build_files_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Files")
        view_inputs_button = Gtk.Button(icon_name="view-list-symbolic", valign=Gtk.Align.CENTER)
        view_inputs_button.add_css_class("flat")
        set_icon_button_a11y(view_inputs_button, VIEW_INPUTS_BUTTON_HINT)
        view_inputs_button.set_action_name("win.view_inputs")
        group.set_header_suffix(view_inputs_button)
        self.input_row = InputFilesRow(
            self._on_inputs_changed,
            on_toast=self.window.toast,
            accept_any_getter=lambda: bool(self.settings.get("is_accept_any_input")),
        )
        set_tooltip(self.input_row, INPUT_FOLDER_ENTRY_HELP)
        self.output_row = OutputFolderRow(self._on_output_changed, on_toast=self.window.toast)
        set_tooltip(self.output_row, OUTPUT_FOLDER_ENTRY_HELP)
        group.add(self.input_row)
        group.add(self.output_row)
        return group

    def _build_ensemble_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Ensemble options")
        self.ensemble_group = group

        self.saved_row = make_combo_row("Saved ensemble", [CHOOSE_ENSEMBLE_OPTION])
        set_tooltip(self.saved_row, ENSEMBLE_SAVED_PRESET_HINT)
        self.saved_row.connect("notify::selected", self._on_saved_selected)
        save_button = Gtk.Button(icon_name="document-save-symbolic", valign=Gtk.Align.CENTER)
        set_icon_button_a11y(save_button, ENSEMBLE_SAVE_BUTTON_HINT)
        save_button.add_css_class("flat")
        save_button.connect("clicked", self._on_save_clicked)
        delete_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        set_icon_button_a11y(delete_button, ENSEMBLE_DELETE_BUTTON_HINT)
        delete_button.add_css_class("flat")
        delete_button.connect("clicked", self._on_delete_clicked)
        self.saved_row.add_suffix(save_button)
        self.saved_row.add_suffix(delete_button)
        group.add(self.saved_row)

        self.main_stem_row = make_combo_row("Main stem pair", list(ENSEMBLE_MAIN_STEM), icon_name="view-list-symbolic")
        set_tooltip(self.main_stem_row, ENSEMBLE_MAIN_STEM_HELP)
        self.main_stem_row.connect("notify::selected", self._on_main_stem_changed)
        group.add(self.main_stem_row)

        # Checklist: models before algorithms.
        self._build_models_dialog()
        self.models_trigger_row = Adw.ActionRow(
            title="Member models",
            subtitle=self._models_summary(),
            activatable=True,
        )
        set_tooltip(self.models_trigger_row, ENSEMBLE_LISTBOX_HELP)
        self.models_trigger_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.models_trigger_row.connect("activated", self._open_models_dialog)
        group.add(self.models_trigger_row)

        self.member_options_row = Adw.ActionRow(
            title="Member model options",
            subtitle="Batch size, secondary models, and more",
            activatable=True,
        )
        set_tooltip(self.member_options_row, ENSEMBLE_MEMBER_MODEL_OPTIONS_HINT)
        self.member_options_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self.member_options_row.connect("activated", self._open_member_model_options)
        group.add(self.member_options_row)

        self.preset_row = make_combo_row(
            "Algorithm preset",
            list(ENSEMBLE_PRESET_OPTIONS),
            icon_name="emblem-favorite-symbolic",
        )
        set_tooltip(
            self.preset_row,
            "Quick dual-stem algorithm pairs. Choose Custom to set Primary and Secondary independently.",
        )
        self.preset_row.connect("notify::selected", self._on_preset_changed)
        group.add(self.preset_row)

        self.primary_algo_row = make_combo_row(
            "Primary algorithm",
            list(ENSEMBLE_ALGORITHMS),
            icon_name="media-playlist-shuffle-symbolic",
        )
        set_tooltip(self.primary_algo_row, ENSEMBLE_TYPE_HELP)
        self.primary_algo_row.connect("notify::selected", self._on_ensemble_type_changed)
        group.add(self.primary_algo_row)

        self.secondary_algo_row = make_combo_row(
            "Secondary algorithm",
            list(ENSEMBLE_ALGORITHMS),
            icon_name="media-playlist-shuffle-symbolic",
        )
        set_tooltip(self.secondary_algo_row, ENSEMBLE_TYPE_HELP)
        self.secondary_algo_row.connect("notify::selected", self._on_ensemble_type_changed)
        group.add(self.secondary_algo_row)

        return group

    def _build_models_dialog(self) -> None:
        """Build the modal member-model checklist (the inline boxed list lives
        here now, opened from the compact trigger row in "Ensemble options")."""
        self.models_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.models_listbox.add_css_class("boxed-list")
        set_tooltip(self.models_listbox, ENSEMBLE_LISTBOX_HELP)
        self.models_listbox.set_filter_func(self._models_row_visible)
        self.models_listbox.append(
            Adw.ActionRow(title="Choose a stem pair to list models")
        )

        self.models_listbox.set_valign(Gtk.Align.START)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(320)
        scroller.set_vexpand(True)
        scroller.set_child(self.models_listbox)
        set_tooltip(scroller, ENSEMBLE_LISTBOX_HELP)

        description = Gtk.Label(
            label="Select two or more models compatible with the chosen stem pair.",
            wrap=True,
            xalign=0.0,
        )
        description.add_css_class("dim-label")

        self.models_status_label = Gtk.Label(
            label=models_selection_status(0),
            wrap=True,
            xalign=0.0,
        )
        self.models_status_label.add_css_class("dim-label")

        self.models_search = Gtk.SearchEntry()
        self.models_search.set_placeholder_text("Search models")
        self.models_search.set_hexpand(True)
        self.models_search.connect("search-changed", self._on_models_search_changed)

        select_all_btn = Gtk.Button(label="Select all")
        select_all_btn.add_css_class("flat")
        select_all_btn.connect("clicked", self._on_models_select_all)
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.add_css_class("flat")
        clear_btn.connect("clicked", self._on_models_clear)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.append(select_all_btn)
        actions.append(clear_btn)
        actions.set_halign(Gtk.Align.END)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        toolbar.append(self.models_search)
        toolbar.append(actions)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inset_md(content)
        content.append(description)
        content.append(self.models_status_label)
        content.append(toolbar)
        content.append(scroller)

        self.models_dialog = Adw.Dialog()
        self.models_dialog.set_title("Member models")
        self.models_dialog.set_content_width(440)
        self.models_dialog.set_content_height(560)
        self.models_dialog.set_follows_content_size(True)
        set_dialog_content(self.models_dialog, content)
        self.models_dialog.connect("closed", self._on_models_dialog_closed)

    def _build_stems_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Save stems")
        self.save_stems = SaveStemsSection(
            settings=self.settings,
            on_changed=self._on_save_stems_changed,
        )
        self.save_stems.attach_to(group)
        set_tooltip(group, SAVE_STEM_ONLY_HELP)
        # Revealed in _rebuild_stem_only_toggles once a stem pair is chosen.
        group.set_visible(False)
        self.stems_group = group
        return group

    def _build_output_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Processing")

        self.format_row = OutputFormatRow(self._on_format_changed)
        group.add(self.format_row)

        self.gpu_row = make_switch_row("GPU conversion", icon_name="pci-card-symbolic")
        set_tooltip(self.gpu_row, IS_GPU_CONVERSION_HELP)
        self.gpu_row.connect("notify::active", self._on_gpu_changed)
        group.add(self.gpu_row)

        self.autocast_row = make_switch_row(
            "FP16 autocast",
            subtitle="Faster VR/MDX/Roformer on modern NVIDIA GPUs",
            icon_name="emblem-system-symbolic",
        )
        set_tooltip(self.autocast_row, IS_AUTOCAST_HELP)
        self.autocast_row.connect("notify::active", self._on_autocast_changed)
        group.add(self.autocast_row)

        duration = self.settings.get("model_sample_mode_duration", 30)
        self.sample_row = make_switch_row(
            SAMPLE_MODE_TITLE,
            sample_mode_subtitle(duration),
            icon_name="preferences-system-time-symbolic",
        )
        set_tooltip(self.sample_row,MODEL_SAMPLE_MODE_HELP)
        self.sample_row.connect("notify::active", self._on_sample_changed)
        group.add(self.sample_row)

        # Advanced toggles live in Processing (titled group) instead of a
        # title-less PreferencesGroup wrapping a lone expander.
        expander = Adw.ExpanderRow(title="Advanced ensemble options")

        self.save_all_row = make_switch_row("Save all outputs")
        set_tooltip(self.save_all_row, IS_SAVE_ALL_OUTPUTS_ENSEMBLE_HELP)
        self.save_all_row.connect(
            "notify::active",
            lambda *_a: self._set_bool(
                "is_save_all_outputs_ensemble",
                self.save_all_row.get_active(),
                refresh_stems=True,
            ),
        )
        expander.add_row(self.save_all_row)

        self.append_name_row = make_switch_row("Append ensemble name to output")
        set_tooltip(self.append_name_row, IS_APPEND_ENSEMBLE_NAME_HELP)
        self.append_name_row.connect(
            "notify::active",
            lambda *_a: self._set_bool("is_append_ensemble_name", self.append_name_row.get_active()),
        )
        expander.add_row(self.append_name_row)

        self.wav_ensemble_row = make_switch_row(
            "Ensemble waveforms",
            wav_ensemble_subtitle(uses_chunk_min=False),
        )
        set_tooltip(self.wav_ensemble_row, IS_WAV_ENSEMBLE_HELP)
        self.wav_ensemble_row.connect(
            "notify::active",
            lambda *_a: self._set_bool("is_wav_ensemble", self.wav_ensemble_row.get_active()),
        )
        expander.add_row(self.wav_ensemble_row)

        group.add(expander)

        self.vocal_split_row = VocalSplitRow(
            self.context.repo, self._on_vocal_split_changed, hints=_RowTooltipHints()
        )
        group.add(self.vocal_split_row)

        return group

    # -- Settings load / persist ------------------------------------------------

    def load(self) -> None:
        """Populate every control from settings (driven by the main window).

        Does *not* set ``chosen_process_method``; that flips to ``ENSEMBLE_MODE``
        only while this tab is active (see :meth:`on_activated`), so the saved
        separation method is preserved at startup.
        """
        self._loading = True
        try:
            self.input_row.set_paths(self.settings.get("input_paths") or [], notify=False)
            self.output_row.set_path(self.settings.get("export_path") or "", notify=False)
            self.format_row.apply_from_settings(self.settings)
            self.vocal_split_row.apply_from_settings(self.settings)
            self.gpu_row.set_active(bool(self.settings.get("is_gpu_conversion")))
            self.autocast_row.set_active(bool(self.settings.get("is_autocast")))
            apply_sample_mode_label(self.sample_row, self.settings.get("model_sample_mode_duration", 30))
            self.sample_row.set_active(bool(self.settings.get("model_sample_mode")))

            self._refresh_saved_list()
            set_combo_value(self.main_stem_row, self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR))
            self._refresh_ensemble_type_values()

            self._rebuild_stem_only_toggles()
            self.save_all_row.set_active(bool(self.settings.get("is_save_all_outputs_ensemble")))
            self.append_name_row.set_active(bool(self.settings.get("is_append_ensemble_name")))
            self.wav_ensemble_row.set_active(bool(self.settings.get("is_wav_ensemble")))
        finally:
            self._loading = False
        self._sync_gpu_dependent_rows()

        self._rebuild_model_list(self.settings.get("selected_models") or [])

    def _sync_shared_from_settings(self) -> None:
        """Re-read the keys shared across tabs (inputs / output / format / ...)."""
        self._loading = True
        try:
            apply_shared_file_options(
                self.settings,
                input_row=self.input_row,
                output_row=self.output_row,
                format_row=self.format_row,
                gpu_row=self.gpu_row,
                autocast_row=self.autocast_row,
                sample_row=self.sample_row,
            )
            self.vocal_split_row.apply_from_settings(self.settings)
        finally:
            self._loading = False
        self._sync_gpu_dependent_rows()

    def _set_bool(self, key: str, value: bool, *, refresh_stems: bool = False) -> None:
        if self._loading:
            return
        self.settings.set(key, value)
        if refresh_stems:
            self._update_stems_group_metadata()

    def _on_inputs_changed(self) -> None:
        paths = list(self.input_row.paths)
        self.settings.set("input_paths", paths)
        self.context.prune_unreadable_input_paths(paths)
        self.window._refresh_start_readiness()

    def _on_output_changed(self) -> None:
        self.settings.set("export_path", self.output_row.path)
        self.window._refresh_start_readiness()

    def _on_format_changed(self, *_args) -> None:
        if not self._loading:
            self.format_row.persist_to_settings(self.settings)

    def _on_vocal_split_changed(self, *_args) -> None:
        if not self._loading:
            self.vocal_split_row.persist_to_settings(self.settings)

    def _on_gpu_changed(self, *_args) -> None:
        if not self._loading:
            self.settings.set("is_gpu_conversion", self.gpu_row.get_active())
            self._update_stems_group_metadata()
        self._sync_gpu_dependent_rows()

    def _on_autocast_changed(self, *_args) -> None:
        if not self._loading:
            self.settings.set("is_autocast", self.autocast_row.get_active())

    def _on_sample_changed(self, *_args) -> None:
        if not self._loading:
            self.settings.set("model_sample_mode", self.sample_row.get_active())
            self._update_stems_group_metadata()

    def _ensemble_stem_pair(self) -> tuple[str | None, str | None]:
        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        if main_stem and main_stem != CHOOSE_STEM_PAIR and "/" in main_stem:
            primary_stem, secondary_stem = main_stem.split("/", 1)
            return primary_stem, secondary_stem
        return None, None

    def _resolve_ensemble_semantics_model(self):
        """Best-effort model resolve for export-semantics hints (first member)."""
        tags = self._selected_model_tags()
        if not tags:
            return None
        tag = tags[0]
        if ENSEMBLE_PARTITION not in tag:
            return None
        process_method, _, model_name = tag.partition(ENSEMBLE_PARTITION)
        return self.window.context.repo.resolve_model_dry(
            self.settings, process_method.strip(), model_name.strip()
        )

    def _rebuild_stem_only_toggles(self) -> None:
        primary_stem, secondary_stem = self._ensemble_stem_pair()
        has_pair = bool(primary_stem and secondary_stem)
        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        is_multi = self._is_multi_or_four_stem(main_stem)
        # Dual-stem: full Save stems toggles. 4-stem / multi-stem: summary-only.
        # Choose stem pair: hide the group.
        self.stems_group.set_visible(has_pair or is_multi)
        if has_pair:
            model = self._resolve_ensemble_semantics_model()
            self.save_stems.configure_exclusive(
                primary_stem=primary_stem,
                secondary_stem=secondary_stem,
                primary_key=_PRIMARY_STEM_ONLY_KEY,
                secondary_key=_SECONDARY_STEM_ONLY_KEY,
                has_model=True,
                stem_label_overrides=stem_display_overrides(model),
                export_semantics_note=recommended_export_note(model),
            )
            self.save_stems.sync_from_settings()
        else:
            self.save_stems.configure_hidden(has_model=False)
        self._update_stems_group_metadata()

    def _update_stems_group_metadata(self) -> None:
        if not self.stems_group.get_visible():
            self.stems_group.set_description("")
            return
        primary_stem, _secondary = self._ensemble_stem_pair()
        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        is_multi = self._is_multi_or_four_stem(main_stem)
        has_run = bool(primary_stem) or is_multi
        repo = self.window.context.repo
        if primary_stem:
            line1 = self.save_stems.export_summary()
            export_hint = self.save_stems.active_hint()
        else:
            line1 = ensemble_export_summary(self.settings, repo=repo)
            export_hint = SAVE_STEM_ONLY_HELP
        workload = estimate_workload(
            self.settings,
            method_key=ENSEMBLE_MODE,
            save_stems=self.save_stems,
            repo=repo,
            has_model=has_run,
        )
        line2 = format_workload_line(workload)
        if line1 and line2:
            self.stems_group.set_description(f"{line1}\n{line2}")
        else:
            self.stems_group.set_description(line2 or line1)
        set_tooltip(
            self.stems_group,
            compose_stem_group_tooltip(
                export_hint,
                workload,
                workload_hint=RUN_WORKLOAD_HINT,
            ),
        )

    def _on_save_stems_changed(self) -> None:
        if self._loading:
            return
        self.save_stems.persist_to_settings()
        self._update_stems_group_metadata()

    # -- Saved ensembles --------------------------------------------------------

    def _refresh_saved_list(self) -> None:
        curated = [curated_combo_label(preset_id) for preset_id in list_curated_ensembles()]
        names = list_saved_ensembles()
        set_combo_values(self.saved_row, [CHOOSE_ENSEMBLE_OPTION, *curated, *names])
        set_combo_value(self.saved_row, self.settings.get("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION))

    def _on_saved_selected(self, *_args) -> None:
        if self._loading:
            return
        name = get_combo_value(self.saved_row)
        if not name or name == CHOOSE_ENSEMBLE_OPTION:
            self.settings.set("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION)
            return
        curated_id = curated_id_from_combo_label(name)
        if curated_id is not None:
            data = load_curated_ensemble(curated_id)
            if not data:
                self._toast(f"Could not load curated recipe '{curated_id}'.")
                return
            self.settings.set("chosen_ensemble", name)
            self._apply_saved_ensemble(data, curated_id=curated_id)
            return
        data = load_ensemble(name)
        if not data:
            self._toast(f"Could not load ensemble '{name}'.")
            return
        self.settings.set("chosen_ensemble", name)
        self._apply_saved_ensemble(data)

    def _apply_saved_ensemble(self, data: dict, *, curated_id: Optional[str] = None) -> None:
        self._loading = True
        try:
            main_stem = data.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
            self.settings.set("ensemble_main_stem", main_stem)
            set_combo_value(self.main_stem_row, main_stem)
            ensemble_type = data.get("ensemble_type", MAX_MIN)
            self.settings.set("ensemble_type", ensemble_type)
            self._refresh_ensemble_type_values()
        finally:
            self._loading = False
        self._rebuild_stem_only_toggles()
        selected = list(data.get("selected_models") or [])
        if curated_id is not None:
            selected = resolve_member_tags(selected, self.context.repo)
        self._rebuild_model_list(selected)
        self._persist_selected_models()
        if curated_id is not None:
            description = (data.get("description") or "").strip()
            if description:
                self._toast(description)
            self._offer_download_missing(data.get("selected_models") or [])

    def _offer_download_missing(self, tags: List[str]) -> None:
        _installed, missing = classify_preset_members(tags, self.context.repo)
        if not missing:
            return
        from ..download import _get_manager, _get_queue

        manager = _get_manager(self.context)
        queue = _get_queue(self.context, manager)
        entries, unresolved = download_entries_for_missing(missing, manager)
        if not entries and not unresolved:
            return

        body_parts = [f"{len(missing)} member model(s) are not installed."]
        if entries:
            body_parts.append(f"{len(entries)} can be queued from the Download Center.")
        if unresolved:
            body_parts.append(f"{len(unresolved)} could not be matched in the catalogue.")
        dialog = Adw.AlertDialog(
            heading="Download missing models?",
            body=" ".join(body_parts),
        )
        dialog.add_response("cancel", "Not now")
        if entries:
            dialog.add_response("download", "Download missing")
            dialog.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("download")
        else:
            dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dlg, response):
            if response != "download" or not entries:
                return
            ids = queue.enqueue_many(entries)
            if ids:
                self._toast(f"Queued {len(ids)} download(s) for missing members")
            else:
                self._toast("Nothing new to download for the missing members")

        dialog.connect("response", on_response)
        dialog.present(self.window)

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        selected = self._selected_model_tags()
        if len(selected) <= 1:
            self._toast("Select at least two models before saving an ensemble.")
            return
        self._present_save_dialog(selected)

    def _present_save_dialog(self, selected: List[str]) -> None:
        dialog = Adw.AlertDialog(
            heading="Save Ensemble",
            body="Enter a name for this ensemble.",
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("Ensemble name")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_dlg, response):
            if response == "save":
                name = entry.get_text().strip()
                if name:
                    self._do_save_ensemble(name, selected)
                else:
                    self._toast("Ensemble name cannot be empty.")

        dialog.connect("response", on_response)
        dialog.present(self.window)

    def _do_save_ensemble(self, name: str, selected: List[str]) -> None:
        try:
            save_ensemble(
                name,
                self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR),
                self.settings.get("ensemble_type", MAX_MIN),
                selected,
            )
        except OSError as exc:
            self._toast(f"Couldn't save ensemble: {exc}")
            return
        self.settings.set("chosen_ensemble", name)
        self._refresh_saved_list()
        self._toast(f"Saved ensemble '{name}'.")

    def _on_delete_clicked(self, _button: Gtk.Button) -> None:
        name = get_combo_value(self.saved_row)
        if not name or name == CHOOSE_ENSEMBLE_OPTION:
            self._toast("Select a saved ensemble to delete.")
            return
        if is_curated_combo_label(name):
            self._toast("Curated recipes cannot be deleted.")
            return
        dialog = Adw.AlertDialog(
            heading="Delete ensemble?",
            body=f'This permanently deletes the saved ensemble "{name}".',
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_confirmed, name)
        dialog.present(self.window)

    def _on_delete_confirmed(self, _dialog, response, name: str) -> None:
        if response != "delete":
            return
        if delete_ensemble(name):
            self.settings.set("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION)
            self._refresh_saved_list()
            self._toast(f"Deleted ensemble '{name}'.")
        else:
            self._toast(f"Ensemble '{name}' was not found.")

    # -- Stem pair / algorithm --------------------------------------------------

    def _is_multi_or_four_stem(self, main_stem: str) -> bool:
        return main_stem in (FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE)

    def _refresh_ensemble_type_values(self) -> None:
        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        multi = self._is_multi_or_four_stem(main_stem)
        current = self.settings.get("ensemble_type", MAX_MIN)
        primary, secondary = parse_ensemble_type(current)
        primary_stem, secondary_stem = self._ensemble_stem_pair()
        primary_title, secondary_title = algorithm_row_titles(
            primary_stem, secondary_stem, multi_stem=multi
        )

        was_loading = self._loading
        self._loading = True
        self._syncing_preset = True
        try:
            set_combo_values(self.primary_algo_row, list(ENSEMBLE_ALGORITHMS))
            set_combo_values(self.secondary_algo_row, list(ENSEMBLE_ALGORITHMS))
            set_combo_value(self.primary_algo_row, primary)
            set_combo_value(self.secondary_algo_row, secondary)
            set_row_title(self.primary_algo_row, primary_title)
            set_row_title(self.secondary_algo_row, secondary_title)
            set_row_subtitle(self.primary_algo_row, algorithm_blurb(primary))
            set_row_subtitle(self.secondary_algo_row, algorithm_blurb(secondary))

            if multi:
                self.preset_row.set_visible(False)
                self.secondary_algo_row.set_visible(False)
                if current != primary:
                    self.settings.set("ensemble_type", primary)
            else:
                self.preset_row.set_visible(True)
                self.secondary_algo_row.set_visible(True)
                paired = format_ensemble_type(primary, secondary)
                if current != paired:
                    self.settings.set("ensemble_type", paired)
                set_combo_value(self.preset_row, preset_for_pair(primary, secondary))
        finally:
            self._syncing_preset = False
            self._loading = was_loading

        self._update_algo_sensitivity()
        self._update_wav_ensemble_subtitle()
        self._update_ensemble_options_summary()

    def _on_main_stem_changed(self, *_args) -> None:
        if self._loading:
            return
        main_stem = get_combo_value(self.main_stem_row)
        self.settings.set("ensemble_main_stem", main_stem)
        self.settings.set("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION)
        set_combo_value(self.saved_row, CHOOSE_ENSEMBLE_OPTION)
        self._refresh_ensemble_type_values()
        # Rebuild the model list for the new stem pair first: stem-only
        # toggles resolve export-semantics hints from _selected_model_tags(),
        # which otherwise still reflects the previous stem pair's checklist.
        self._rebuild_model_list(self._selected_model_tags())
        self._rebuild_stem_only_toggles()
        self._update_ensemble_options_summary()

    def _on_preset_changed(self, *_args) -> None:
        if self._loading or self._syncing_preset:
            return
        preset = get_combo_value(self.preset_row)
        pair = pair_for_preset(preset)
        if pair is None:
            return
        primary, secondary = pair
        self._syncing_preset = True
        try:
            set_combo_value(self.primary_algo_row, primary)
            set_combo_value(self.secondary_algo_row, secondary)
            set_row_subtitle(self.primary_algo_row, algorithm_blurb(primary))
            set_row_subtitle(self.secondary_algo_row, algorithm_blurb(secondary))
            self.settings.set("ensemble_type", format_ensemble_type(primary, secondary))
        finally:
            self._syncing_preset = False
        self._update_wav_ensemble_subtitle()
        self._update_ensemble_options_summary()

    def _on_ensemble_type_changed(self, *_args) -> None:
        if self._loading or self._syncing_preset:
            return
        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        primary = get_combo_value(self.primary_algo_row)
        set_row_subtitle(self.primary_algo_row, algorithm_blurb(primary))
        if self._is_multi_or_four_stem(main_stem):
            self.settings.set("ensemble_type", primary)
        else:
            secondary = get_combo_value(self.secondary_algo_row)
            set_row_subtitle(self.secondary_algo_row, algorithm_blurb(secondary))
            self.settings.set("ensemble_type", format_ensemble_type(primary, secondary))
            self._syncing_preset = True
            try:
                set_combo_value(self.preset_row, preset_for_pair(primary, secondary))
            finally:
                self._syncing_preset = False
        self._update_wav_ensemble_subtitle()
        self._update_ensemble_options_summary()

    def _update_algo_sensitivity(self) -> None:
        enabled = self._stem_pair_chosen()
        for row in (
            getattr(self, "preset_row", None),
            getattr(self, "primary_algo_row", None),
            getattr(self, "secondary_algo_row", None),
        ):
            if row is None:
                continue
            row.set_sensitive(enabled)

    def _sync_gpu_dependent_rows(self) -> None:
        """Dim GPU-only options while GPU conversion is off."""
        self.autocast_row.set_sensitive(
            gpu_dependent_enabled(self.gpu_row.get_active())
        )

    def _update_wav_ensemble_subtitle(self) -> None:
        row = getattr(self, "wav_ensemble_row", None)
        if row is None:
            return
        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        primary, secondary = parse_ensemble_type(self.settings.get("ensemble_type", MAX_MIN))
        if self._is_multi_or_four_stem(main_stem):
            uses_chunk = primary == CHUNK_MIN
        else:
            uses_chunk = CHUNK_MIN in (primary, secondary)
        set_row_subtitle(row, wav_ensemble_subtitle(uses_chunk_min=uses_chunk))

    def _update_ensemble_options_summary(self) -> None:
        group = getattr(self, "ensemble_group", None)
        if group is None:
            return
        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        multi = self._is_multi_or_four_stem(main_stem)
        primary_stem, secondary_stem = self._ensemble_stem_pair()
        primary, secondary = parse_ensemble_type(self.settings.get("ensemble_type", MAX_MIN))
        group.set_description(
            ensemble_options_summary(
                stem_chosen=self._stem_pair_chosen(),
                main_stem=main_stem,
                primary_stem=primary_stem,
                secondary_stem=secondary_stem,
                primary_algo=primary,
                secondary_algo=secondary,
                model_count=len(self._effective_selected_models()),
                multi_stem=multi,
            )
        )

    # -- Model multi-select list ------------------------------------------------

    def _rebuild_model_list(self, preselected: List[str]) -> None:
        preselected_set = set(preselected)
        child = self.models_listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.models_listbox.remove(child)
            child = nxt
        self._model_checks = {}
        self._model_row_text = {}

        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        if main_stem == CHOOSE_STEM_PAIR:
            self.models_listbox.append(
                Adw.ActionRow(title="Choose a stem pair to list models")
            )
            self._update_models_dialog_status()
            self._update_models_summary()
            return

        try:
            tags = self.context.repo.ensemble_model_list(self.settings, main_stem)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            from ..errorlog import log_error

            log_error("Ensemble", exc, context="listing models")
            row = Adw.ActionRow()
            set_row_title(row, "Could not list models")
            set_row_subtitle(row, "See Error Log for details")
            self.models_listbox.append(row)
            self._update_models_dialog_status()
            self._update_models_summary()
            return

        if not tags:
            self.models_listbox.append(Adw.ActionRow(title="No compatible models found"))
            self._update_models_dialog_status()
            self._update_models_summary()
            return

        for tag in tags:
            title = format_tag_title(tag, self.context.repo)
            subtitle = format_tag_subtitle(tag)
            row = Adw.ActionRow()
            set_row_title(row, title)
            row.set_subtitle(subtitle)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.set_active(tag in preselected_set)
            check.connect("toggled", self._on_model_toggled)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            row._uvr_model_tag = tag  # type: ignore[attr-defined]
            self.models_listbox.append(row)
            self._model_checks[tag] = check
            self._model_row_text[tag] = (title, subtitle)

        self.models_listbox.invalidate_filter()
        self._persist_selected_models()
        self._update_models_dialog_status()
        self._update_models_summary()

    def _selected_model_tags(self) -> List[str]:
        return [tag for tag, check in self._model_checks.items() if check.get_active()]

    def _effective_selected_models(self) -> List[str]:
        """Prefer live checklist state; fall back to persisted settings."""
        if self._model_checks:
            return self._selected_model_tags()
        return list(self.settings.get("selected_models") or [])

    def _persist_selected_models(self) -> None:
        self.settings.set("selected_models", self._selected_model_tags())

    def _models_summary(self) -> str:
        """Single-line description of the current member-model selection."""
        if self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR) == CHOOSE_STEM_PAIR:
            return "Choose a stem pair first"
        count = len(self._effective_selected_models())
        if count == 0:
            return "No models selected"
        if count == 1:
            return "1 model selected"
        return f"{count} models selected"

    def _stem_pair_chosen(self) -> bool:
        return self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR) != CHOOSE_STEM_PAIR

    def _update_member_models_sensitivity(self) -> None:
        """Dim Member models rows until a stem pair is chosen."""
        enabled = self._stem_pair_chosen()
        for row in (
            getattr(self, "models_trigger_row", None),
            getattr(self, "member_options_row", None),
        ):
            if row is None:
                continue
            row.set_sensitive(enabled)
            row.set_activatable(enabled)
        self._update_algo_sensitivity()

    def _update_models_summary(self) -> None:
        row = getattr(self, "models_trigger_row", None)
        if row is not None:
            row.set_subtitle(self._models_summary())
        self._update_member_models_sensitivity()
        self._update_ensemble_options_summary()
        self._update_ensemble_banner()

    def _models_row_visible(self, row: Gtk.ListBoxRow) -> bool:
        tag = getattr(row, "_uvr_model_tag", None)
        if tag is None:
            # Placeholder / error rows stay visible.
            return True
        title, subtitle = self._model_row_text.get(tag, ("", ""))
        query = ""
        search = getattr(self, "models_search", None)
        if search is not None:
            query = search.get_text()
        return model_row_matches_query(title, subtitle, query)

    def _visible_model_tags(self) -> List[str]:
        query = ""
        search = getattr(self, "models_search", None)
        if search is not None:
            query = search.get_text()
        return [
            tag
            for tag, (title, subtitle) in self._model_row_text.items()
            if model_row_matches_query(title, subtitle, query)
        ]

    def _update_models_dialog_status(self) -> None:
        label = getattr(self, "models_status_label", None)
        if label is None:
            return
        selected = len(self._effective_selected_models())
        if not self._model_checks:
            label.set_label(models_selection_status(selected))
            return
        visible = len(self._visible_model_tags())
        label.set_label(
            models_selection_status(
                selected,
                visible_matches=visible,
            )
        )

    def _on_models_search_changed(self, *_args) -> None:
        self.models_listbox.invalidate_filter()
        self._update_models_dialog_status()

    def _on_models_select_all(self, *_args) -> None:
        for tag in self._visible_model_tags():
            check = self._model_checks.get(tag)
            if check is not None and not check.get_active():
                check.set_active(True)

    def _on_models_clear(self, *_args) -> None:
        for tag in self._visible_model_tags():
            check = self._model_checks.get(tag)
            if check is not None and check.get_active():
                check.set_active(False)

    def _open_models_dialog(self, *_args) -> None:
        if not self._stem_pair_chosen():
            return
        search = getattr(self, "models_search", None)
        if search is not None:
            search.set_text("")
        preselected = self._selected_model_tags() if self._model_checks else (self.settings.get("selected_models") or [])
        self._rebuild_model_list(preselected)
        present_modal_dialog(self.models_dialog, self.window)

    def _open_member_model_options(self, *_args) -> None:
        if not self._stem_pair_chosen():
            return
        from ..model_options import OPEN_CONTEXT_ENSEMBLE, stack_name_for_member_tag

        selected = self._selected_model_tags() or self.settings.get("selected_models") or []
        initial_stack = stack_name_for_member_tag(selected[-1]) if selected else None
        self.window._open_model_options(context=OPEN_CONTEXT_ENSEMBLE, initial_stack=initial_stack)

    def _on_models_dialog_closed(self, *_args) -> None:
        self._update_models_summary()
        self._rebuild_stem_only_toggles()
        from core.debug_log import debug

        stem = self.settings.get("ensemble_main_stem", "")
        models = len(self._selected_model_tags())
        debug("ui", f"ensemble models selected count={models} stem={stem}")

    def _on_model_toggled(self, _check: Gtk.CheckButton) -> None:
        # Changing the member set detaches the run from any saved ensemble.
        self.settings.set("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION)
        if not self._loading:
            set_combo_value(self.saved_row, CHOOSE_ENSEMBLE_OPTION)
        self._persist_selected_models()
        self._update_models_dialog_status()
        self._update_models_summary()
        self._rebuild_stem_only_toggles()

    # -- Run target interface ---------------------------------------------------

    def on_activated(self) -> None:
        """Make the ensemble method active and refresh from shared settings.

        ``chosen_process_method`` flips to ``ENSEMBLE_MODE`` here (and is restored
        by the main window on leaving this tab), so the member-model list - which
        depends on the method for the multi-stem ensemble - is rebuilt with the
        correct method in effect.
        """
        self.settings.set("chosen_process_method", ENSEMBLE_MODE)
        self._sync_shared_from_settings()
        preselected = self._selected_model_tags() if self._model_checks else (self.settings.get("selected_models") or [])
        self._rebuild_model_list(preselected)

    def on_deactivated(self) -> None:
        # Method restoration is owned by the main window's tab handler.
        pass

    def _config_blocked_reason(self) -> Optional[str]:
        """Ensemble-configuration blocker (stem pair / member models), if any.

        Excludes input/output readiness (those rows carry their own affordances);
        this is what the empty-state banner surfaces.
        """
        if self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR) == CHOOSE_STEM_PAIR:
            return _REASON_STEM_PAIR
        if len(self._effective_selected_models()) <= 1:
            return _REASON_TWO_MODELS
        return None

    def start_blocked_reason(self) -> Optional[str]:
        """First reason the ensemble run can't start, or ``None`` when ready."""
        input_reason = self.input_row.blocked_reason(
            unreadable_paths=self.context.unreadable_input_paths
        )
        if input_reason:
            return input_reason
        output_reason = self.output_row.blocked_reason()
        if output_reason:
            return output_reason
        return self._config_blocked_reason()

    def _update_ensemble_banner(self) -> None:
        """Reveal the empty-state banner while the ensemble config is incomplete."""
        banner = getattr(self, "_ensemble_banner", None)
        if banner is None:
            return
        reason = self._config_blocked_reason()
        if reason:
            banner.set_title(reason)
        banner.set_revealed(reason is not None)
        self.window._refresh_start_readiness()

    def start(self, callbacks) -> None:
        # Readiness is validated by ``MainWindow._on_start`` before dispatch.
        self.settings.set("chosen_process_method", ENSEMBLE_MODE)
        self._persist_selected_models()

        input_paths = list(self.input_row.paths)
        self.window.begin_run(self)

        try:
            error = self.context.try_save_settings(trigger="ensemble-start")
            if error:
                self._toast(error)
            from core.debug_log import debug

            stem = self.settings.get("ensemble_main_stem", "")
            models = len(self._selected_model_tags())
            debug("ui", f"ensemble start files={len(input_paths)} models={models} stem={stem}")
            self.context.runner.start_ensemble(input_paths, callbacks)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.window.fail_to_start(f"Unable to start ensemble: {exc}", exc)

    def stop(self) -> None:
        self.context.runner.stop()

    def pause(self) -> None:
        self.context.runner.pause()

    def unpause(self) -> None:
        self.context.runner.unpause()

    # -- Misc -------------------------------------------------------------------

    def _toast(self, message: str) -> None:
        self.window.toast(message)
