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

from core.run_estimate import estimate_workload, format_workload_line
from core.model_stem_semantics import recommended_export_note, stem_display_overrides
from bundled.constants import (
    CHOOSE_ENSEMBLE_OPTION,
    CHOOSE_STEM_PAIR,
    ENSEMBLE_LISTBOX_HELP,
    ENSEMBLE_MAIN_STEM,
    ENSEMBLE_MAIN_STEM_HELP,
    ENSEMBLE_MODE,
    ENSEMBLE_PARTITION,
    ENSEMBLE_TYPE,
    ENSEMBLE_TYPE_4_STEM,
    ENSEMBLE_TYPE_HELP,
    FLAC,
    FOUR_STEM_ENSEMBLE,
    IS_APPEND_ENSEMBLE_NAME_HELP,
    IS_GPU_CONVERSION_HELP,
    INPUT_FOLDER_ENTRY_HELP,
    IS_SAVE_ALL_OUTPUTS_ENSEMBLE_HELP,
    IS_WAV_ENSEMBLE_HELP,
    MAX_MIN,
    MODEL_SAMPLE_MODE_HELP,
    MP3,
    OUTPUT_FOLDER_ENTRY_HELP,
    MULTI_STEM_ENSEMBLE,
    SAVE_STEM_ONLY_HELP,
    WAV,
)

from ..dialogs.utils import present_modal_dialog, set_dialog_content
from ..spacing import inset_md
from ..help_text import (
    ENSEMBLE_DELETE_BUTTON_HINT,
    ENSEMBLE_MEMBER_MODEL_OPTIONS_HINT,
    ENSEMBLE_SAVE_BUTTON_HINT,
    ENSEMBLE_SAVED_PRESET_HINT,
    VIEW_INPUTS_BUTTON_HINT,
)
from ..hints import OUTPUT_FORMAT_HINT, set_icon_button_a11y, set_tooltip
from ..markup import set_row_title
from core.model_display import format_tag_subtitle, format_tag_title
from core import (
    delete_ensemble,
    list_saved_ensembles,
    load_ensemble,
    save_ensemble,
)

from ..widgets.columns import build_columns_box, wrap_options_scroller
from ..widgets.file_chooser import InputFilesRow, OutputFolderRow
from ..shared_settings import (
    SAMPLE_MODE_TITLE,
    apply_sample_mode_label,
    apply_shared_file_options,
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
        self._model_checks: Dict[str, Gtk.CheckButton] = {}

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
        self.input_row = InputFilesRow(self._on_inputs_changed, on_toast=self.window.toast)
        set_tooltip(self.input_row, INPUT_FOLDER_ENTRY_HELP)
        self.output_row = OutputFolderRow(self._on_output_changed)
        set_tooltip(self.output_row, OUTPUT_FOLDER_ENTRY_HELP)
        group.add(self.input_row)
        group.add(self.output_row)
        return group

    def _build_ensemble_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Ensemble options")

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
        set_tooltip(self.main_stem_row,ENSEMBLE_MAIN_STEM_HELP)
        self.main_stem_row.connect("notify::selected", self._on_main_stem_changed)
        group.add(self.main_stem_row)

        self.ensemble_type_row = make_combo_row("Ensemble algorithm", list(ENSEMBLE_TYPE), icon_name="media-playlist-shuffle-symbolic")
        set_tooltip(self.ensemble_type_row,ENSEMBLE_TYPE_HELP)
        self.ensemble_type_row.connect("notify::selected", self._on_ensemble_type_changed)
        group.add(self.ensemble_type_row)

        self._build_models_dialog()
        self.models_trigger_row = Adw.ActionRow(
            title="Member models",
            subtitle=self._models_summary(),
            activatable=True,
        )
        set_tooltip(self.models_trigger_row,ENSEMBLE_LISTBOX_HELP)
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

        return group

    def _build_models_dialog(self) -> None:
        """Build the modal member-model checklist (the inline boxed list lives
        here now, opened from the compact trigger row in "Ensemble options")."""
        self.models_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.models_listbox.add_css_class("boxed-list")
        set_tooltip(self.models_listbox,ENSEMBLE_LISTBOX_HELP)
        self.models_listbox.append(
            Adw.ActionRow(title="Choose a stem pair to list models")
        )

        self.models_listbox.set_valign(Gtk.Align.START)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(320)
        scroller.set_vexpand(True)
        scroller.set_child(self.models_listbox)
        set_tooltip(scroller,ENSEMBLE_LISTBOX_HELP)

        description = Gtk.Label(
            label="Select two or more models compatible with the chosen stem pair.",
            wrap=True,
            xalign=0.0,
        )
        description.add_css_class("dim-label")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inset_md(content)
        content.append(description)
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

        self.format_row = make_combo_row("Output format", [WAV, FLAC, MP3], icon_name="audio-x-generic-symbolic")
        set_tooltip(self.format_row, OUTPUT_FORMAT_HINT)
        self.format_row.connect("notify::selected", self._on_format_changed)
        group.add(self.format_row)

        self.gpu_row = make_switch_row("GPU conversion", icon_name="pci-card-symbolic")
        set_tooltip(self.gpu_row,IS_GPU_CONVERSION_HELP)
        self.gpu_row.connect("notify::active", self._on_gpu_changed)
        group.add(self.gpu_row)

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
            lambda *_a: self._set_bool("is_save_all_outputs_ensemble", self.save_all_row.get_active()),
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
            "Combine in the time domain instead of spectrograms",
        )
        set_tooltip(self.wav_ensemble_row, IS_WAV_ENSEMBLE_HELP)
        self.wav_ensemble_row.connect(
            "notify::active",
            lambda *_a: self._set_bool("is_wav_ensemble", self.wav_ensemble_row.get_active()),
        )
        expander.add_row(self.wav_ensemble_row)

        group.add(expander)
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
            set_combo_value(self.format_row, self.settings.get("save_format", WAV))
            self.gpu_row.set_active(bool(self.settings.get("is_gpu_conversion")))
            apply_sample_mode_label(self.sample_row, self.settings.get("model_sample_mode_duration", 30))
            self.sample_row.set_active(bool(self.settings.get("model_sample_mode")))

            self._refresh_saved_list()
            set_combo_value(self.main_stem_row, self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR))
            self._refresh_ensemble_type_values()
            set_combo_value(self.ensemble_type_row, self.settings.get("ensemble_type", MAX_MIN))

            self._rebuild_stem_only_toggles()
            self.save_all_row.set_active(bool(self.settings.get("is_save_all_outputs_ensemble")))
            self.append_name_row.set_active(bool(self.settings.get("is_append_ensemble_name")))
            self.wav_ensemble_row.set_active(bool(self.settings.get("is_wav_ensemble")))
        finally:
            self._loading = False

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
                sample_row=self.sample_row,
            )
        finally:
            self._loading = False

    def _set_bool(self, key: str, value: bool) -> None:
        if self._loading:
            return
        self.settings.set(key, value)

    def _on_inputs_changed(self) -> None:
        self.settings.set("input_paths", list(self.input_row.paths))
        self.window._refresh_start_readiness()

    def _on_output_changed(self) -> None:
        self.settings.set("export_path", self.output_row.path)
        self.window._refresh_start_readiness()

    def _on_format_changed(self, *_args) -> None:
        if not self._loading:
            self.settings.set("save_format", get_combo_value(self.format_row))

    def _on_gpu_changed(self, *_args) -> None:
        if not self._loading:
            self.settings.set("is_gpu_conversion", self.gpu_row.get_active())

    def _on_sample_changed(self, *_args) -> None:
        if not self._loading:
            self.settings.set("model_sample_mode", self.sample_row.get_active())

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
        # Hide the whole group until a stem pair exists so the empty Save stems
        # placeholder does not compete with the page banner.
        self.stems_group.set_visible(has_pair)
        if not has_pair:
            self.save_stems.configure_hidden(has_model=False)
        else:
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
        self._update_stems_group_metadata()

    def _update_stems_group_metadata(self) -> None:
        if not self.stems_group.get_visible():
            self.stems_group.set_description("")
            return
        line1 = self.save_stems.export_summary()
        workload = estimate_workload(
            self.settings,
            method_key=ENSEMBLE_MODE,
            save_stems=self.save_stems,
            repo=self.window.context.repo,
            has_model=bool(self._ensemble_stem_pair()[0]),
        )
        line2 = format_workload_line(workload)
        self.stems_group.set_description(f"{line1}\n{line2}" if line2 else line1)
        set_tooltip(self.stems_group, self.save_stems.active_hint())

    def _on_save_stems_changed(self) -> None:
        if self._loading:
            return
        self.save_stems.persist_to_settings()
        self._update_stems_group_metadata()

    # -- Saved ensembles --------------------------------------------------------

    def _refresh_saved_list(self) -> None:
        names = list_saved_ensembles()
        set_combo_values(self.saved_row, [CHOOSE_ENSEMBLE_OPTION, *names])
        set_combo_value(self.saved_row, self.settings.get("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION))

    def _on_saved_selected(self, *_args) -> None:
        if self._loading:
            return
        name = get_combo_value(self.saved_row)
        if not name or name == CHOOSE_ENSEMBLE_OPTION:
            self.settings.set("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION)
            return
        data = load_ensemble(name)
        if not data:
            self._toast(f"Could not load ensemble '{name}'.")
            return
        self.settings.set("chosen_ensemble", name)
        self._apply_saved_ensemble(data)

    def _apply_saved_ensemble(self, data: dict) -> None:
        self._loading = True
        try:
            main_stem = data.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
            self.settings.set("ensemble_main_stem", main_stem)
            set_combo_value(self.main_stem_row, main_stem)
            self._refresh_ensemble_type_values()
            ensemble_type = data.get("ensemble_type", MAX_MIN)
            self.settings.set("ensemble_type", ensemble_type)
            set_combo_value(self.ensemble_type_row, ensemble_type)
        finally:
            self._loading = False
        self._rebuild_stem_only_toggles()
        self._rebuild_model_list(data.get("selected_models") or [])
        self._persist_selected_models()

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
        save_ensemble(
            name,
            self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR),
            self.settings.get("ensemble_type", MAX_MIN),
            selected,
        )
        self.settings.set("chosen_ensemble", name)
        self._refresh_saved_list()
        self._toast(f"Saved ensemble '{name}'.")

    def _on_delete_clicked(self, _button: Gtk.Button) -> None:
        name = get_combo_value(self.saved_row)
        if not name or name == CHOOSE_ENSEMBLE_OPTION:
            self._toast("Select a saved ensemble to delete.")
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
        values = ENSEMBLE_TYPE_4_STEM if self._is_multi_or_four_stem(main_stem) else ENSEMBLE_TYPE
        current = self.settings.get("ensemble_type", MAX_MIN)
        set_combo_values(self.ensemble_type_row, list(values))
        if current not in values:
            current = values[0]
            self.settings.set("ensemble_type", current)
        set_combo_value(self.ensemble_type_row, current)

    def _on_main_stem_changed(self, *_args) -> None:
        if self._loading:
            return
        main_stem = get_combo_value(self.main_stem_row)
        self.settings.set("ensemble_main_stem", main_stem)
        self.settings.set("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION)
        set_combo_value(self.saved_row, CHOOSE_ENSEMBLE_OPTION)
        self._refresh_ensemble_type_values()
        self._rebuild_stem_only_toggles()
        self._rebuild_model_list(self._selected_model_tags())

    def _on_ensemble_type_changed(self, *_args) -> None:
        if self._loading:
            return
        self.settings.set("ensemble_type", get_combo_value(self.ensemble_type_row))

    # -- Model multi-select list ------------------------------------------------

    def _rebuild_model_list(self, preselected: List[str]) -> None:
        preselected_set = set(preselected)
        child = self.models_listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.models_listbox.remove(child)
            child = nxt
        self._model_checks = {}

        main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
        if main_stem == CHOOSE_STEM_PAIR:
            self.models_listbox.append(
                Adw.ActionRow(title="Choose a stem pair to list models")
            )
            self._update_models_summary()
            return

        try:
            tags = self.context.repo.ensemble_model_list(self.settings, main_stem)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.models_listbox.append(Adw.ActionRow(title=f"Could not list models: {exc}"))
            self._update_models_summary()
            return

        if not tags:
            self.models_listbox.append(Adw.ActionRow(title="No compatible models found"))
            self._update_models_summary()
            return

        for tag in tags:
            row = Adw.ActionRow()
            set_row_title(row, format_tag_title(tag, self.context.repo))
            row.set_subtitle(format_tag_subtitle(tag))
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.set_active(tag in preselected_set)
            check.connect("toggled", self._on_model_toggled)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self.models_listbox.append(row)
            self._model_checks[tag] = check

        self._persist_selected_models()
        self._update_models_summary()

    def _selected_model_tags(self) -> List[str]:
        return [tag for tag, check in self._model_checks.items() if check.get_active()]

    def _persist_selected_models(self) -> None:
        self.settings.set("selected_models", self._selected_model_tags())

    def _models_summary(self) -> str:
        """Single-line description of the current member-model selection."""
        if self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR) == CHOOSE_STEM_PAIR:
            return "Choose a stem pair first"
        count = len(self._selected_model_tags())
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

    def _update_models_summary(self) -> None:
        row = getattr(self, "models_trigger_row", None)
        if row is not None:
            row.set_subtitle(self._models_summary())
        self._update_member_models_sensitivity()
        self._update_ensemble_banner()

    def _open_models_dialog(self, *_args) -> None:
        if not self._stem_pair_chosen():
            return
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
        if len(self._selected_model_tags()) <= 1:
            return _REASON_TWO_MODELS
        return None

    def start_blocked_reason(self) -> Optional[str]:
        """First reason the ensemble run can't start, or ``None`` when ready."""
        input_reason = self.input_row.blocked_reason()
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
        self.context.save_settings()
        self.window.begin_run(self)

        try:
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
