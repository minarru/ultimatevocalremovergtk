"""Settings UI as an ``Adw.PreferencesDialog``.

This is the GTK4 / libadwaita port of ``UVR.py``'s ``menu_settings`` window
(tabs 1 and 2 - general + additional/audio-format/process settings). It exposes
the same options the Tkinter settings window does and binds every control to the
shared typed :class:`core.settings.Settings` through
:class:`ui.context.AppContext`.

Covered (Phase 2):

* General: help-hints toggle, reset-to-default (with confirmation) and
  saved-settings profiles (save / load / remove).
* Output format and its quality sub-option live on the Separation / Ensemble /
  Audio Tools pages (``ui/widgets/format_row.py``), not here — this dialog only
  holds settings with no per-run meaning.
* General process settings: test-mode / model-name / model-folder / accept-any-
  input / notification-chimes / normalization toggles.
* Hardware: CUDA device selection (gated on GPU conversion, set on the
  processing pages) + Windows DirectML toggle.
* Sample mode + sample-clip duration.

Saved-settings profiles mirror ``UVR.py``: each profile is a JSON file under
``profiles/`` named after the (space->underscore) profile name and
containing the full settings dict (the same files the Tk app reads/writes), so
profiles are interchangeable between the two front ends.

Anything advanced/per-method (secondary models, vocal splitter, change-model
defaults, deverb, the download center, ...) is intentionally left to later
phases.
"""

import os
import re
import threading
import typing
from typing import Optional

from gi.repository import Adw, GLib, Gtk

from bundled.constants import (
    DEFAULT,
    GPU_DEVICE_NUM_OPTS,
    IS_CUDA_SELECT_HELP,
    REG_SAVE_INPUT,
    SAMPLE_MODE_CHECKBOX,
)
from core.export_naming import preview_output_name
from core.json_store import read_json_object, safe_json_path, write_json_atomic
from core.paths import SETTINGS_CACHE_DIR
from core.platform import system_name

from .application import apply_color_scheme
from .dispatch import idle_on_main
from .help_text import (
    AMPLIFICATION_THRESHOLD_HELP,
    IS_ACCEPT_ANY_INPUT_HELP,
    IS_CREATE_MODEL_FOLDER_HELP,
    IS_MATCH_MIX_LEVEL_HELP,
    IS_MODEL_TESTING_AUDIO_HELP,
    IS_NORMALIZATION_HELP,
    IS_PREVENT_EXPORT_CLIPPING_HELP,
    LONG_FILE_CHUNK_HELP,
    LONG_FILE_CHUNK_OVERLAP_HELP,
    REMOVE_PROFILE_HINT,
)
from .hints import set_icon_button_a11y, set_tooltip
from .settings_bind import enum_value, get_flat, set_flat
from .shared_settings import gpu_dependent_enabled
from .template import load_builder, object_from_builder
from .widgets.rows import (
    configure_combo_row,
    configure_switch_row,
    get_combo_value,
    set_combo_value,
)

_PERSIST_DEBOUNCE_MS = 250

_NAMING_PREVIEW_KEYS = frozenset(
    {"is_testing_audio", "is_add_model_name", "is_create_model_folder"}
)

_NO_PROFILES = "(no saved profiles)"

#: Appearance combo display labels paired with their ``color_scheme`` values.
_COLOR_SCHEME_OPTIONS = (
    ("Follow system", "auto"),
    ("Light", "light"),
    ("Dark", "dark"),
)

_DIAGNOSTIC_LEVEL_OPTIONS = (
    ("Errors only", "errors"),
    ("Debug", "debug"),
    ("Trace", "trace"),
)


def persistence_feedback(error: Optional[str], success: str) -> str:
    """Return exactly one honest result message for a settings write."""
    return error or success


def catalogue_refresh_feedback(
    report: typing.Any,
    *,
    online: bool,
    model_settings_updated: bool | None,
    error: str = "",
) -> str:
    """Describe a manual catalogue-cache refresh without hiding stale sources."""
    detail = str(error or "").strip().rstrip(".")
    if detail:
        return f"Couldn't refresh catalogue cache: {detail}. Previous cache kept."

    sources: list[str] = []
    for entry in getattr(report, "failed", ()):
        source = entry[0] if isinstance(entry, tuple) and entry else entry
        value = str(getattr(source, "value", source) or "").strip()
        if value and value not in sources:
            sources.append(value)
    for source in getattr(report, "stale", ()):
        value = str(getattr(source, "value", source) or "").strip()
        if value and value not in sources:
            sources.append(value)

    if sources:
        labels = [source.replace("_", " ").capitalize() for source in sources]
        if len(labels) == 1:
            joined = labels[0]
        else:
            joined = ", ".join(labels[:-1]) + f" and {labels[-1]}"
        return f"Catalogue cache partially refreshed; kept previous data for {joined}"
    if model_settings_updated is False:
        return "Catalogue cache refreshed, but model parameters could not be updated"
    if online or bool(getattr(report, "usable", False)):
        return "Catalogue cache refreshed"
    return "Couldn't refresh catalogue cache. Previous cache kept."


def catalogue_evidence_refresh_feedback(summary: typing.Any) -> str:
    """Describe aggregate config-evidence completion without hiding LKG use."""
    unavailable = int(getattr(summary, "unavailable", 0) or 0)
    stale = int(getattr(summary, "stale", 0) or 0)
    if unavailable and stale:
        return (
            "Catalogue refreshed; output details finished with "
            f"{unavailable} unavailable and {stale} using previous details"
        )
    if unavailable:
        noun = "model" if unavailable == 1 else "models"
        return f"Catalogue refreshed; output details unavailable for {unavailable} {noun}"
    if stale:
        noun = "model" if stale == 1 else "models"
        return f"Catalogue refreshed; using previous output details for {stale} {noun}"
    return "Catalogue refreshed; output details updated"


class ProfileStore:
    """Read/write named settings profiles as JSON, matching ``UVR.py``.

    Profiles live in ``profiles/`` under the writable data directory as
    ``<name>.json`` (spaces in
    the name become underscores in the filename), holding the full settings dict
    - identical to how ``pop_up_save_current_settings_sub_json_dump`` /
    ``handle_saved_settings`` persist and reload them.
    """

    def __init__(self, directory: str = SETTINGS_CACHE_DIR):
        self.directory = directory

    def _path(self, name: str) -> str:
        return safe_json_path(self.directory, name.replace(" ", "_"))

    def list_profiles(self):
        try:
            entries = os.listdir(self.directory)
        except OSError:
            return []
        return sorted(os.path.splitext(entry)[0] for entry in entries if entry.endswith(".json"))

    def save(self, name: str, data: dict) -> Optional[str]:
        """Write ``data`` as a profile. Returns an error message, or ``None`` on success."""
        try:
            write_json_atomic(self._path(name), data)
        except (OSError, ValueError) as exc:
            return f"Couldn't save profile: {exc}"
        return None

    def load(self, name: str):
        path = self._path(name)
        if not os.path.isfile(path):
            return None
        try:
            data = read_json_object(path)
        except (ValueError, OSError):
            return None
        return data

    def remove(self, name: str) -> tuple[bool, Optional[str]]:
        """Remove a profile. Returns ``(removed, error_message)``."""
        path = self._path(name)
        if not os.path.isfile(path):
            return False, None
        try:
            os.remove(path)
        except OSError as exc:
            return False, f"Couldn't remove profile: {exc}"
        return True, None


def _is_valid_profile_name(name: str) -> bool:
    """Mirror ``UVR.py``'s ``REG_SAVE_INPUT`` rule for profile names."""
    if not name or name != name.strip():
        return False
    if name.startswith("-") or name.endswith("-"):
        return False
    return re.fullmatch(REG_SAVE_INPUT, f" {name} ".strip()) is not None and len(name) <= 25


class PreferencesDialog(Adw.PreferencesDialog):
    """libadwaita settings dialog bound to the shared typed settings.

    Two callbacks, deliberately asymmetric:

    * ``on_settings_applied`` — fired after every debounced edit. Must be cheap:
      the main window only needs to re-read the handful of keys it mirrors.
    * ``on_settings_reloaded`` — fired only when the settings model is replaced
      wholesale (profile load, reset to defaults), where a full rebuild of the
      window's widgets is the point.
    """

    def __init__(
        self,
        context: typing.Any,
        on_settings_reloaded: typing.Any = None,
        on_settings_applied: typing.Any = None,
    ):
        super().__init__()
        self.context = context
        self.settings = context.settings
        self._on_settings_reloaded = on_settings_reloaded
        self._on_settings_applied = on_settings_applied
        self._profiles = ProfileStore()
        # Guards programmatic widget updates from being treated as user edits.
        self._loading = False
        self._persist_timeout_id = 0
        self._catalogue_refresh_generation = 0

        self.set_title("Settings")

        builder = load_builder("preferences")
        self.add(self._build_general_page(builder))
        self.add(self._build_processing_page(builder))

        self._reload_widgets()
        from .lifetime import UiLifetime

        self._lifetime = UiLifetime()
        self.connect("closed", self._on_dialog_closed)

    # -- Page construction ------------------------------------------------------

    def _build_general_page(self, builder: Gtk.Builder) -> Adw.PreferencesPage:
        page = object_from_builder(builder, "general_page", Adw.PreferencesPage)

        self.color_scheme_row = configure_combo_row(
            object_from_builder(builder, "color_scheme_row", Adw.ComboRow),
            [label for label, _value in _COLOR_SCHEME_OPTIONS],
        )
        self.color_scheme_row.connect("notify::selected", self._on_color_scheme_changed)

        self.diagnostic_level_row = configure_combo_row(
            object_from_builder(builder, "diagnostic_level_row", Adw.ComboRow),
            [label for label, _value in _DIAGNOSTIC_LEVEL_OPTIONS],
        )
        self.diagnostic_level_row.connect("notify::selected", self._on_diagnostic_level_changed)
        self.diagnostic_sensitive_row = configure_switch_row(
            object_from_builder(builder, "diagnostic_sensitive_row", Adw.SwitchRow)
        )
        self.diagnostic_sensitive_row.connect(
            "notify::active", self._on_diagnostic_sensitive_changed
        )

        self.profile_combo = configure_combo_row(
            object_from_builder(builder, "profile_combo", Adw.ComboRow),
            [_NO_PROFILES],
        )
        load_button = object_from_builder(builder, "profile_load_button", Gtk.Button)
        load_button.connect("clicked", self._on_load_profile)
        remove_button = object_from_builder(builder, "profile_remove_button", Gtk.Button)
        set_icon_button_a11y(remove_button, REMOVE_PROFILE_HINT)
        remove_button.connect("clicked", self._on_remove_profile)

        self.profile_name_row = object_from_builder(builder, "profile_name_row", Adw.EntryRow)
        self.profile_name_row.connect("apply", self._on_save_profile)

        reset_button = object_from_builder(builder, "reset_button", Gtk.Button)
        reset_button.connect("clicked", self._on_reset_clicked)

        self._notification_switches: dict[str, Adw.SwitchRow] = {
            key: configure_switch_row(object_from_builder(builder, f"{key}_row", Adw.SwitchRow))
            for key in (
                "notify_process_complete",
                "notify_process_failed",
                "notify_download_complete",
                "notify_download_failed",
            )
        }
        for key, row in self._notification_switches.items():
            row.connect("notify::active", self._on_bool_changed, key)

        self.confirm_processing_plan_row = configure_switch_row(
            object_from_builder(builder, "confirm_processing_plan_row", Adw.SwitchRow)
        )
        self.confirm_processing_plan_row.connect(
            "notify::active", self._on_bool_changed, "confirm_processing_plan"
        )

        return page

    def _build_processing_page(self, builder: Gtk.Builder) -> Adw.PreferencesPage:
        page = object_from_builder(builder, "processing_page", Adw.PreferencesPage)

        self._process_switches: dict[str, Adw.SwitchRow] = {
            key: configure_switch_row(object_from_builder(builder, f"{key}_row", Adw.SwitchRow))
            for key in (
                "is_testing_audio",
                "is_add_model_name",
                "is_create_model_folder",
                "is_accept_any_input",
                "is_normalization",
                "is_match_mix_level",
                "is_prevent_export_clipping",
            )
        }
        for key, row in self._process_switches.items():
            row.connect("notify::active", self._on_bool_changed, key)
        set_tooltip(self._process_switches["is_add_model_name"], IS_MODEL_TESTING_AUDIO_HELP)
        set_tooltip(self._process_switches["is_create_model_folder"], IS_CREATE_MODEL_FOLDER_HELP)
        set_tooltip(self._process_switches["is_accept_any_input"], IS_ACCEPT_ANY_INPUT_HELP)
        set_tooltip(self._process_switches["is_normalization"], IS_NORMALIZATION_HELP)
        set_tooltip(self._process_switches["is_match_mix_level"], IS_MATCH_MIX_LEVEL_HELP)
        set_tooltip(
            self._process_switches["is_prevent_export_clipping"],
            IS_PREVENT_EXPORT_CLIPPING_HELP,
        )

        self.amplification_row = object_from_builder(builder, "amplification_row", Adw.SpinRow)
        set_tooltip(self.amplification_row, AMPLIFICATION_THRESHOLD_HELP)
        self.amplification_row.connect("notify::value", self._on_amplification_changed)
        self.output_name_preview_row = object_from_builder(
            builder, "output_name_preview_row", Adw.ActionRow
        )

        # Populate asynchronously — ``nvidia-smi`` can take up to ~2s.
        cached = getattr(self.context, "gpu_devices", None)
        if cached is not None:
            device_opts, device_subtitle = self._device_row_options(cached)
        else:
            device_opts = list(GPU_DEVICE_NUM_OPTS)
            device_subtitle = "Detecting…"

        self.device_row = configure_combo_row(
            object_from_builder(builder, "device_row", Adw.ComboRow),
            device_opts,
        )
        self._device_detection_subtitle = device_subtitle
        self._sync_gpu_device_row()
        set_tooltip(self.device_row, IS_CUDA_SELECT_HELP)
        self.device_row.connect("notify::selected", self._on_combo_changed, "device_set")
        if cached is None:
            threading.Thread(target=self._probe_gpu_devices, daemon=True).start()

        self.directml_row = configure_switch_row(
            object_from_builder(builder, "directml_row", Adw.SwitchRow)
        )
        self.directml_row.connect("notify::active", self._on_bool_changed, "is_use_directml")
        if system_name() != "Windows":
            hardware_group = object_from_builder(builder, "hardware_group", Adw.PreferencesGroup)
            hardware_group.remove(self.directml_row)

        self.sample_mode_row = configure_switch_row(
            object_from_builder(builder, "sample_mode_row", Adw.SwitchRow)
        )
        self.sample_mode_row.connect("notify::active", self._on_bool_changed, "model_sample_mode")
        self.sample_duration_row = object_from_builder(builder, "sample_duration_row", Adw.SpinRow)
        self.sample_duration_row.connect("notify::value", self._on_duration_changed)
        self.long_chunk_row = object_from_builder(builder, "long_chunk_row", Adw.SpinRow)
        set_tooltip(self.long_chunk_row, LONG_FILE_CHUNK_HELP)
        self.long_chunk_row.connect("notify::value", self._on_long_chunk_changed)
        self.long_chunk_overlap_row = object_from_builder(
            builder, "long_chunk_overlap_row", Adw.SpinRow
        )
        set_tooltip(self.long_chunk_overlap_row, LONG_FILE_CHUNK_OVERLAP_HELP)
        self.long_chunk_overlap_row.connect("notify::value", self._on_long_chunk_overlap_changed)
        self.cleanup_ensemble_temps_row = configure_switch_row(
            object_from_builder(builder, "cleanup_ensemble_temps_row", Adw.SwitchRow)
        )
        self.cleanup_ensemble_temps_row.connect(
            "notify::active",
            self._on_bool_changed,
            "is_cleanup_ensemble_temps",
        )
        self.auto_update_model_params_row = configure_switch_row(
            object_from_builder(builder, "auto_update_model_params_row", Adw.SwitchRow)
        )
        self.auto_update_model_params_row.connect(
            "notify::active",
            self._on_bool_changed,
            "is_auto_update_model_params",
        )
        self.catalogue_cache_refresh_row = object_from_builder(
            builder, "catalogue_cache_refresh_row", Adw.ActionRow
        )
        self.catalogue_cache_refresh_button = object_from_builder(
            builder, "catalogue_cache_refresh_button", Gtk.Button
        )
        self.catalogue_cache_refresh_button.connect("clicked", self._on_catalogue_cache_refresh)
        self.catalogue_cache_refresh_spinner = object_from_builder(
            builder, "catalogue_cache_refresh_spinner", Gtk.Spinner
        )

        return page

    def _on_catalogue_cache_refresh(self, _button: Gtk.Button) -> None:
        if getattr(self, "_catalogue_cache_refreshing", False):
            return
        self._catalogue_refresh_generation += 1
        self._catalogue_cache_refreshing = True
        self.catalogue_cache_refresh_button.set_sensitive(False)
        self.catalogue_cache_refresh_spinner.set_visible(True)
        self.catalogue_cache_refresh_spinner.start()
        self.catalogue_cache_refresh_row.set_subtitle("Refreshing catalogue cache…")
        threading.Thread(
            target=self._catalogue_cache_refresh_worker,
            args=(self._catalogue_refresh_generation,),
            daemon=True,
        ).start()

    def _catalogue_cache_refresh_worker(self, generation: int) -> None:
        from core.debug_log import debug

        try:
            manager = self.context.download_manager
            online = bool(manager.refresh())
            model_settings_updated: bool | None = None
            if online and self.settings.process.auto_update_model_params:
                model_settings_updated = bool(manager.update_model_settings(self.context.repo))
            final_message = catalogue_refresh_feedback(
                manager.last_refresh_report,
                online=online,
                model_settings_updated=model_settings_updated,
            )
            report_usable = bool(getattr(manager.last_refresh_report, "usable", False))
            if online or report_usable:
                completion_lock = threading.Lock()
                completion_published = False
                early_completion: typing.Any = None

                def evidence_completed(summary: typing.Any) -> None:
                    nonlocal early_completion
                    with completion_lock:
                        if not completion_published:
                            early_completion = summary
                            return
                    self._on_catalogue_evidence_refresh_completed(summary, generation)

                queued = manager.force_revalidate_catalogue_evidence(evidence_completed)
                if queued:
                    idle_on_main(
                        self._finish_catalogue_cache_refresh,
                        "Catalogue refreshed; output details updating",
                        generation,
                    )
                    with completion_lock:
                        completion_published = True
                        completed = early_completion
                    if completed is not None:
                        self._on_catalogue_evidence_refresh_completed(completed, generation)
                    debug(
                        "download",
                        f"preferences catalogue evidence queued={len(queued)}",
                    )
                    return
            message = final_message
        except Exception as exc:  # shown in Preferences and log
            from .errorlog import log_error

            log_error("Preferences", exc, context="refreshing catalogue cache")
            message = catalogue_refresh_feedback(
                None,
                online=False,
                model_settings_updated=None,
                error=str(exc).strip() or type(exc).__name__,
            )
        debug("download", f"preferences catalogue refresh result={message!r}")
        idle_on_main(self._finish_catalogue_cache_refresh, message, generation)

    def _on_catalogue_evidence_refresh_completed(
        self, summary: typing.Any, generation: int
    ) -> None:
        """Marshal a cache-worker aggregate result onto the GTK main thread."""
        idle_on_main(self._finish_catalogue_evidence_refresh, summary, generation)

    def _finish_catalogue_evidence_refresh(self, summary: typing.Any, generation: int) -> None:
        if self._lifetime.disposed or generation != self._catalogue_refresh_generation:
            return
        message = catalogue_evidence_refresh_feedback(summary)
        self.catalogue_cache_refresh_row.set_subtitle(message)
        self.add_toast(Adw.Toast.new(message))

    def _finish_catalogue_cache_refresh(self, message: str, generation: int) -> None:
        if self._lifetime.disposed or generation != self._catalogue_refresh_generation:
            return
        self._catalogue_cache_refreshing = False
        self.catalogue_cache_refresh_button.set_sensitive(True)
        self.catalogue_cache_refresh_spinner.stop()
        self.catalogue_cache_refresh_spinner.set_visible(False)
        self.catalogue_cache_refresh_row.set_subtitle(message)
        self.add_toast(Adw.Toast.new(message))

    # -- Load settings into widgets ---------------------------------------------

    def _reload_widgets(self) -> None:
        self._loading = True
        try:
            scheme = enum_value(self.settings.ui.color_scheme) or "auto"
            scheme_index = next(
                (i for i, (_label, value) in enumerate(_COLOR_SCHEME_OPTIONS) if value == scheme),
                0,
            )
            self.color_scheme_row.set_selected(scheme_index)

            for key, row in self._process_switches.items():
                row.set_active(bool(get_flat(self.settings, key)))
            try:
                amp = float(self.settings.process.amplification_threshold or 0.0)
            except (TypeError, ValueError):
                amp = 0.0
            self.amplification_row.set_value(max(0.0, min(1.0, amp)))
            self._refresh_output_name_preview()

            for key, row in self._notification_switches.items():
                row.set_active(bool(get_flat(self.settings, key, True)))
            self.confirm_processing_plan_row.set_active(
                bool(self.settings.ui.confirm_processing_plan)
            )
            diagnostic_level = str(
                getattr(
                    self.settings.diagnostics.level,
                    "value",
                    self.settings.diagnostics.level,
                )
            )
            diagnostic_index = next(
                (
                    index
                    for index, (_label, value) in enumerate(_DIAGNOSTIC_LEVEL_OPTIONS)
                    if value == diagnostic_level
                ),
                0,
            )
            self.diagnostic_level_row.set_selected(diagnostic_index)
            self.diagnostic_sensitive_row.set_active(
                bool(self.settings.diagnostics.include_sensitive)
            )

            if hasattr(self, "directml_row"):
                self.directml_row.set_active(bool(self.settings.process.use_directml))
            if not set_combo_value(self.device_row, self.settings.process.device or DEFAULT):
                set_combo_value(self.device_row, DEFAULT)

            self._sync_gpu_device_row()

            self.sample_mode_row.set_active(bool(self.settings.process.sample_mode))
            self.cleanup_ensemble_temps_row.set_active(bool(self.settings.ensemble.cleanup_temps))
            self.auto_update_model_params_row.set_active(
                bool(self.settings.process.auto_update_model_params)
            )
            duration = self.settings.process.sample_mode_duration
            try:
                duration = float(duration)
            except (TypeError, ValueError):
                duration = 30.0
            self.sample_duration_row.set_value(duration)
            self._update_sample_duration_subtitle(duration)

            try:
                long_chunk = float(self.settings.process.long_file_chunk_seconds or 0)
            except (TypeError, ValueError):
                long_chunk = 0.0
            self.long_chunk_row.set_value(max(0.0, min(3600.0, long_chunk)))
            try:
                long_overlap = float(self.settings.process.long_file_chunk_overlap_seconds)
            except (TypeError, ValueError):
                long_overlap = 2.0
            self.long_chunk_overlap_row.set_value(max(0.0, min(30.0, long_overlap)))

            self._refresh_profile_list()
        finally:
            self._loading = False

    def _refresh_profile_list(self, select: typing.Any = None) -> None:
        profiles = self._profiles.list_profiles()
        values = profiles if profiles else [_NO_PROFILES]
        # set_combo_values lives in rows.py; rebuild the model here to stay self-contained.
        model = Gtk.StringList()
        for value in values:
            model.append(value)
        self.profile_combo.set_model(model)
        self.profile_combo.set_sensitive(bool(profiles))
        if select and select in profiles:
            set_combo_value(self.profile_combo, select)

    def _update_sample_duration_subtitle(self, duration: typing.Any) -> None:
        self.sample_duration_row.set_subtitle(SAMPLE_MODE_CHECKBOX(int(duration)))

    # -- Change handlers --------------------------------------------------------

    def _on_bool_changed(self, row: typing.Any, _pspec: typing.Any, key: typing.Any) -> None:
        if self._loading:
            return
        set_flat(self.settings, key, bool(row.get_active()))
        if key in _NAMING_PREVIEW_KEYS:
            self._refresh_output_name_preview()
        self._persist()

    def _on_amplification_changed(self, row: typing.Any, _pspec: typing.Any) -> None:
        if self._loading:
            return
        value = float(row.get_value())
        self.settings.process.amplification_threshold = max(0.0, min(1.0, value))
        self._persist()

    def _on_long_chunk_changed(self, row: typing.Any, _pspec: typing.Any) -> None:
        if self._loading:
            return
        # The row is digits=0, so this is already whole; store it as the float
        # the field declares so CLI-set fractional values survive a reload too.
        self.settings.process.long_file_chunk_seconds = float(row.get_value())
        self._persist()

    def _on_long_chunk_overlap_changed(self, row: typing.Any, _pspec: typing.Any) -> None:
        if self._loading:
            return
        self.settings.process.long_file_chunk_overlap_seconds = float(row.get_value())
        self._persist()

    def _refresh_output_name_preview(self) -> None:
        if not hasattr(self, "output_name_preview_row"):
            return
        self.output_name_preview_row.set_subtitle(preview_output_name(self.settings))

    def _on_color_scheme_changed(self, row: typing.Any, _pspec: typing.Any) -> None:
        if self._loading:
            return
        index = row.get_selected()
        if index == Gtk.INVALID_LIST_POSITION:
            return
        value = _COLOR_SCHEME_OPTIONS[index][1]
        from core.settings.coerce import coerce_field

        self.settings.ui.color_scheme = coerce_field("ui", "color_scheme", value)
        self._persist()
        apply_color_scheme(value)

    def _on_diagnostic_level_changed(self, row: typing.Any, _pspec: typing.Any) -> None:
        if self._loading:
            return
        index = row.get_selected()
        if index == Gtk.INVALID_LIST_POSITION:
            return
        from core.types.settings_enums import DiagnosticLevel

        value = _DIAGNOSTIC_LEVEL_OPTIONS[index][1]
        self.settings.diagnostics.level = DiagnosticLevel(value)
        self._apply_diagnostic_policy()
        self._persist()

    def _on_diagnostic_sensitive_changed(self, row: typing.Any, _pspec: typing.Any) -> None:
        if self._loading:
            return
        self.settings.diagnostics.include_sensitive = bool(row.get_active())
        self._apply_diagnostic_policy()
        self._persist()

    def _apply_runtime_settings(self) -> None:
        """Apply profile/reset values whose widget handlers are suppressed on reload."""
        apply_color_scheme(enum_value(self.settings.ui.color_scheme) or "auto")
        self._apply_diagnostic_policy()

    def _apply_diagnostic_policy(self) -> None:
        from core.debug_log import update_policy

        level = str(
            getattr(
                self.settings.diagnostics.level,
                "value",
                self.settings.diagnostics.level,
            )
        )
        update_policy(
            level=level,
            include_sensitive=self.settings.diagnostics.include_sensitive,
        )

    def _on_combo_changed(self, row: typing.Any, _pspec: typing.Any, key: typing.Any) -> None:
        if self._loading:
            return
        value = get_combo_value(row)
        if value is None:
            return
        set_flat(self.settings, key, value)
        self._persist()

    def _on_duration_changed(self, row: typing.Any, _pspec: typing.Any) -> None:
        if self._loading:
            return
        value = int(row.get_value())
        self.settings.process.sample_mode_duration = value
        self._update_sample_duration_subtitle(value)
        self._persist()

    def _persist(self) -> None:
        """Debounce disk writes so spin-row ticks do not rewrite settings JSON."""
        if self._persist_timeout_id:
            GLib.source_remove(self._persist_timeout_id)
        self._persist_timeout_id = GLib.timeout_add(_PERSIST_DEBOUNCE_MS, self._flush_persist)

    def _flush_persist(self) -> bool:
        self._persist_timeout_id = 0
        error = self.context.try_save_settings(trigger="preferences")
        if error:
            self.add_toast(Adw.Toast.new(error))
        elif self._on_settings_applied is not None:
            self._on_settings_applied()
        return GLib.SOURCE_REMOVE

    def _on_dialog_closed(self, *_args: typing.Any) -> None:
        if self._persist_timeout_id:
            GLib.source_remove(self._persist_timeout_id)
            self._persist_timeout_id = 0
            self._flush_persist()

        self._lifetime.dispose()

    @staticmethod
    def _device_row_options(devices: typing.Any):
        if devices:
            opts = [DEFAULT] + [idx for idx, _name in devices]
            subtitle = "Detected: " + ", ".join(
                f"{idx}: {name}" if name else idx for idx, name in devices
            )
        else:
            opts = list(GPU_DEVICE_NUM_OPTS)
            subtitle = "No GPU detected"
        return opts, subtitle

    def _sync_gpu_device_row(self) -> None:
        enabled = gpu_dependent_enabled(self.settings.process.use_gpu)
        self.device_row.set_sensitive(enabled)
        subtitle = self._device_detection_subtitle
        if not enabled:
            subtitle = (
                "Enable GPU conversion on Separation or Ensemble to choose a device.\n" + subtitle
            )
        self.device_row.set_subtitle(subtitle)

    def _probe_gpu_devices(self) -> None:
        from core.gpu import list_gpu_devices

        devices = list_gpu_devices()
        self.context.gpu_devices = devices
        idle_on_main(self._apply_gpu_devices, devices)

    def _apply_gpu_devices(self, devices: typing.Any) -> None:
        if self._lifetime.disposed:
            return
        if not hasattr(self, "device_row"):
            return
        current = get_combo_value(self.device_row)
        opts, subtitle = self._device_row_options(devices)
        self._loading = True
        try:
            from .widgets.rows import set_combo_values

            set_combo_values(self.device_row, opts)
            self._device_detection_subtitle = subtitle
            self._sync_gpu_device_row()
            if current in opts:
                set_combo_value(self.device_row, current)
        finally:
            self._loading = False

    # -- Profiles ---------------------------------------------------------------

    def _on_save_profile(self, entry_row: typing.Any) -> None:
        name = entry_row.get_text().strip()
        if not _is_valid_profile_name(name):
            self.add_toast(
                Adw.Toast.new("Invalid name. Use up to 25 letters, numbers, spaces or dashes")
            )
            return
        canonical = name.replace(" ", "_")
        if canonical in self._profiles.list_profiles():
            dialog = Adw.AlertDialog(
                heading=f'Replace profile "{name}"?',
                body="A profile with this name already exists. Replacing it overwrites the saved settings.",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("replace", "Replace")
            dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect("response", self._on_save_profile_confirmed, entry_row, name)
            dialog.present(self)
            return
        self._write_profile(entry_row, name)

    def _on_save_profile_confirmed(
        self, _dialog: typing.Any, response: typing.Any, entry_row: typing.Any, name: str
    ) -> None:
        if response != "replace":
            return
        self._write_profile(entry_row, name)

    def _write_profile(self, entry_row: typing.Any, name: str) -> None:
        error = self._profiles.save(name, self.settings.to_dict())
        if error:
            self.add_toast(Adw.Toast.new(error))
            return
        entry_row.set_text("")
        from core.debug_log import debug

        debug("settings", f"profile save name={name}")
        # Profiles are listed by file-name stem (spaces become underscores),
        # mirroring UVR.py; select that canonical form after saving.
        self._refresh_profile_list(select=name.replace(" ", "_"))
        self.add_toast(Adw.Toast.new(f'Saved profile "{name}"'))

    def _on_load_profile(self, _button: typing.Any) -> None:
        name = get_combo_value(self.profile_combo)
        if not name or name == _NO_PROFILES:
            return
        dialog = Adw.AlertDialog(
            heading=f'Load profile "{name}"?',
            body="This replaces the current settings and file selections.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("load", "Load")
        dialog.set_response_appearance("load", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_load_profile_confirmed, name)
        dialog.present(self)

    def _on_load_profile_confirmed(
        self, _dialog: typing.Any, response: typing.Any, name: str
    ) -> None:
        if response != "load":
            return
        data = self._profiles.load(name)
        if data is None:
            self.add_toast(Adw.Toast.new(f'Could not load profile "{name}"'))
            return
        # Adopt flat keys the typed schema knows about (includes ensemble keys
        # that were never in DEFAULT_DATA). Nested profile JSON is accepted too.
        from core.settings.flat_map import FLAT_TO_PATH
        from core.settings.model import Settings as TypedSettings

        if "schema_version" in data or "process" in data:
            loaded = TypedSettings.from_json_dict(data)
            self.settings.update(loaded.to_dict())
        else:
            self.settings.update({k: v for k, v in data.items() if k in FLAT_TO_PATH})
        self._apply_runtime_settings()
        error = self.context.try_save_settings(trigger="profile-load")
        from core.debug_log import debug

        debug("settings", f"profile load name={name}")
        self._reload_widgets()
        if self._on_settings_reloaded is not None:
            self._on_settings_reloaded()
        self.add_toast(Adw.Toast.new(persistence_feedback(error, f'Loaded profile "{name}"')))

    def _on_remove_profile(self, _button: typing.Any) -> None:
        name = get_combo_value(self.profile_combo)
        if not name or name == _NO_PROFILES:
            return
        dialog = Adw.AlertDialog(
            heading="Remove profile?",
            body=f'This permanently deletes the saved profile "{name}".',
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_remove_confirmed, name)
        dialog.present(self)

    def _on_remove_confirmed(
        self, _dialog: typing.Any, response: typing.Any, name: typing.Any
    ) -> None:
        if response != "remove":
            return
        removed, error = self._profiles.remove(name)
        if error:
            self.add_toast(Adw.Toast.new(error))
            return
        if not removed:
            self.add_toast(Adw.Toast.new(f'Could not remove profile "{name}"'))
            self._refresh_profile_list()
            return
        from core.debug_log import debug

        debug("settings", f"profile remove name={name}")
        self._refresh_profile_list()
        self.add_toast(Adw.Toast.new(f'Removed profile "{name}"'))

    # -- Reset ------------------------------------------------------------------

    def _on_reset_clicked(self, _button: typing.Any) -> None:
        dialog = Adw.AlertDialog(
            heading="Reset all settings?",
            body="Every option will be restored to its default value. This cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Reset")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_reset_confirmed)
        dialog.present(self)

    def _on_reset_confirmed(self, _dialog: typing.Any, response: typing.Any) -> None:
        if response != "reset":
            return
        from core.debug_log import debug

        self.settings.reset_to_default()
        self._apply_runtime_settings()
        error = self.context.try_save_settings(trigger="reset")
        debug("settings", "profile reset confirmed")
        self._reload_widgets()
        if self._on_settings_reloaded is not None:
            self._on_settings_reloaded()
        self.add_toast(Adw.Toast.new(persistence_feedback(error, "Settings reset to default")))
