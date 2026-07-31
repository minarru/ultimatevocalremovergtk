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
import typing

import json
import os
import re
import threading
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
from core.platform import system_name
from core.paths import SETTINGS_CACHE_DIR

from .application import apply_color_scheme
from .dispatch import idle_on_main
from .help_text import (
    AMPLIFICATION_THRESHOLD_HELP,
    IS_MATCH_MIX_LEVEL_HELP,
    IS_NORMALIZATION_HELP,
    IS_PREVENT_EXPORT_CLIPPING_HELP,
    LONG_FILE_CHUNK_HELP,
    LONG_FILE_CHUNK_OVERLAP_HELP,
    REMOVE_PROFILE_HINT,
)
from .hints import set_icon_button_a11y, set_tooltip
from .settings_bind import get_flat, set_flat
from .widgets.rows import get_combo_value, make_combo_row, set_combo_value

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
        return os.path.join(self.directory, f"{name.replace(' ', '_')}.json")

    def list_profiles(self):
        try:
            entries = os.listdir(self.directory)
        except OSError:
            return []
        return sorted(
            os.path.splitext(entry)[0]
            for entry in entries
            if entry.endswith(".json")
        )

    def save(self, name: str, data: dict) -> Optional[str]:
        """Write ``data`` as a profile. Returns an error message, or ``None`` on success."""
        try:
            os.makedirs(self.directory, exist_ok=True)
            with open(self._path(name), "w") as outfile:
                outfile.write(json.dumps(data, indent=4))
        except OSError as exc:
            return f"Couldn't save profile: {exc}"
        return None

    def load(self, name: str):
        path = self._path(name)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r") as infile:
                data = json.load(infile)
        except (ValueError, OSError):
            return None
        return data if isinstance(data, dict) else None

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

    def __init__(self, context: typing.Any, on_settings_reloaded: typing.Any=None, on_settings_applied: typing.Any=None):
        super().__init__()
        self.context = context
        self.settings = context.settings
        self._on_settings_reloaded = on_settings_reloaded
        self._on_settings_applied = on_settings_applied
        self._profiles = ProfileStore()
        # Guards programmatic widget updates from being treated as user edits.
        self._loading = False
        self._persist_timeout_id = 0

        self.set_title("Settings")

        self.add(self._build_general_page())
        self.add(self._build_processing_page())

        self._reload_widgets()
        self.connect("closed", self._on_dialog_closed)

    # -- Page construction ------------------------------------------------------

    def _build_general_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="General", icon_name="emblem-system-symbolic")

        appearance_group = Adw.PreferencesGroup(title="Appearance")
        self.color_scheme_row = make_combo_row(
            "Color scheme",
            [label for label, _value in _COLOR_SCHEME_OPTIONS],
        )
        self.color_scheme_row.connect("notify::selected", self._on_color_scheme_changed)
        appearance_group.add(self.color_scheme_row)
        page.add(appearance_group)

        profiles_group = Adw.PreferencesGroup(
            title="Saved settings profiles",
            description="Save the current settings as a named profile, or load / remove an existing one",
        )

        self.profile_combo = make_combo_row("Profile", [_NO_PROFILES])
        load_button = Gtk.Button(label="_Load", use_underline=True, valign=Gtk.Align.CENTER)
        load_button.connect("clicked", self._on_load_profile)
        remove_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        set_icon_button_a11y(remove_button, REMOVE_PROFILE_HINT)
        remove_button.add_css_class("destructive-action")
        remove_button.connect("clicked", self._on_remove_profile)
        self.profile_combo.add_suffix(load_button)
        self.profile_combo.add_suffix(remove_button)
        profiles_group.add(self.profile_combo)

        self.profile_name_row = Adw.EntryRow(title="Save current settings as")
        self.profile_name_row.set_show_apply_button(True)
        self.profile_name_row.connect("apply", self._on_save_profile)
        profiles_group.add(self.profile_name_row)
        page.add(profiles_group)

        reset_group = Adw.PreferencesGroup(title="Reset")
        reset_row = Adw.ActionRow(
            title="Reset all settings to default",
            subtitle="Restore every option to its built-in default value",
        )
        reset_button = Gtk.Button(label="Reset", valign=Gtk.Align.CENTER)
        reset_button.add_css_class("destructive-action")
        reset_button.connect("clicked", self._on_reset_clicked)
        reset_row.add_suffix(reset_button)
        reset_group.add(reset_row)
        page.add(reset_group)

        notifications_group = Adw.PreferencesGroup(
            title="Desktop notifications",
            description="System notifications when tasks finish in the background",
        )
        self._notification_switches = {}
        for key, title, subtitle in (
            (
                "notify_process_complete",
                "Processing complete",
                "When separation, ensemble, or audio tools finish successfully",
            ),
            (
                "notify_process_failed",
                "Processing failed",
                "When a run stops with an error",
            ),
            (
                "notify_download_complete",
                "Downloads finished",
                "When queued model downloads complete successfully",
            ),
            (
                "notify_download_failed",
                "Download failed",
                "When a queued model download fails",
            ),
        ):
            row = Adw.SwitchRow(title=title, subtitle=subtitle)
            row.connect("notify::active", self._on_bool_changed, key)
            notifications_group.add(row)
            self._notification_switches[key] = row
        page.add(notifications_group)

        return page

    def _build_processing_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Processing", icon_name="applications-system-symbolic")

        process_group = Adw.PreferencesGroup(title="General process settings")
        self._process_switches = {}
        for key, title, subtitle in (
            ("is_testing_audio", "Settings test mode", "Prefix outputs with a timestamp for testing"),
            ("is_add_model_name", "Model test mode", "Append the model name to output file names"),
            ("is_create_model_folder", "Generate model folder", "Save outputs inside a per-model subfolder"),
            ("is_accept_any_input", "Accept any input", "Allow any input file type, not just common audio"),
            ("is_normalization", "Normalize output", "Limit peaks above 1.0 on saved audio"),
            (
                "is_match_mix_level",
                "Match stem levels to mix",
                "Scale multi-stem outputs so their sum matches the input mix",
            ),
            (
                "is_prevent_export_clipping",
                "Prevent export clipping",
                "Scale peaks to fit PCM/FLAC/MP3 without hard clipping",
            ),
        ):
            row = Adw.SwitchRow(title=title, subtitle=subtitle)
            row.connect("notify::active", self._on_bool_changed, key)
            process_group.add(row)
            self._process_switches[key] = row
        set_tooltip(self._process_switches["is_normalization"], IS_NORMALIZATION_HELP)
        set_tooltip(self._process_switches["is_match_mix_level"], IS_MATCH_MIX_LEVEL_HELP)
        set_tooltip(
            self._process_switches["is_prevent_export_clipping"],
            IS_PREVENT_EXPORT_CLIPPING_HELP,
        )

        amp_adjustment = Gtk.Adjustment(
            lower=0.0, upper=1.0, step_increment=0.05, page_increment=0.1
        )
        self.amplification_row = Adw.SpinRow(
            title="Amplification threshold",
            subtitle="Raise quiet outputs to this peak level (0 = off)",
            adjustment=amp_adjustment,
            digits=2,
        )
        set_tooltip(self.amplification_row, AMPLIFICATION_THRESHOLD_HELP)
        self.amplification_row.connect("notify::value", self._on_amplification_changed)
        process_group.add(self.amplification_row)

        self.output_name_preview_row = Adw.ActionRow(
            title="Example output name",
            subtitle=preview_output_name(self.settings),
        )
        self.output_name_preview_row.set_subtitle_lines(2)
        process_group.add(self.output_name_preview_row)
        page.add(process_group)

        hardware_group = Adw.PreferencesGroup(title="Hardware")

        # Populate asynchronously — ``nvidia-smi`` can take up to ~2s.
        cached = getattr(self.context, "gpu_devices", None)
        if cached is not None:
            device_opts, device_subtitle = self._device_row_options(cached)
        else:
            device_opts = list(GPU_DEVICE_NUM_OPTS)
            device_subtitle = "Detecting…"

        self.device_row = make_combo_row("GPU device", device_opts, subtitle=device_subtitle)
        set_tooltip(self.device_row, IS_CUDA_SELECT_HELP)
        self.device_row.connect("notify::selected", self._on_combo_changed, "device_set")
        hardware_group.add(self.device_row)
        if cached is None:
            threading.Thread(target=self._probe_gpu_devices, daemon=True).start()

        self.directml_row = Adw.SwitchRow(
            title="Use DirectML",
            subtitle="Windows AMD/Intel GPU via DirectML (PyTorch models only; MDX ONNX stays on CPU)",
        )
        self.directml_row.connect("notify::active", self._on_bool_changed, "is_use_directml")
        if system_name() == "Windows":
            hardware_group.add(self.directml_row)
        page.add(hardware_group)

        sample_group = Adw.PreferencesGroup(title="Sample mode")
        self.sample_mode_row = Adw.SwitchRow(
            title="Sample mode",
            subtitle="Process only a short clip of each input",
        )
        self.sample_mode_row.connect("notify::active", self._on_bool_changed, "model_sample_mode")
        sample_group.add(self.sample_mode_row)

        adjustment = Gtk.Adjustment(lower=5, upper=120, step_increment=5, page_increment=10)
        self.sample_duration_row = Adw.SpinRow(title="Sample clip duration (seconds)", adjustment=adjustment)
        self.sample_duration_row.connect("notify::value", self._on_duration_changed)
        sample_group.add(self.sample_duration_row)
        page.add(sample_group)

        long_group = Adw.PreferencesGroup(
            title="Long files",
            description="Whole-file time slicing for hour+ tracks (not MDX/Demucs segment size)",
        )
        chunk_adjustment = Gtk.Adjustment(
            lower=0, upper=3600, step_increment=60, page_increment=300
        )
        self.long_chunk_row = Adw.SpinRow(
            title="Chunk duration (seconds)",
            subtitle="0 = off; try 600 for long podcasts",
            adjustment=chunk_adjustment,
            digits=0,
        )
        set_tooltip(self.long_chunk_row, LONG_FILE_CHUNK_HELP)
        self.long_chunk_row.connect("notify::value", self._on_long_chunk_changed)
        long_group.add(self.long_chunk_row)

        overlap_adjustment = Gtk.Adjustment(
            lower=0.0, upper=30.0, step_increment=0.5, page_increment=1.0
        )
        self.long_chunk_overlap_row = Adw.SpinRow(
            title="Chunk overlap (seconds)",
            subtitle="Crossfade between slices",
            adjustment=overlap_adjustment,
            digits=1,
        )
        set_tooltip(self.long_chunk_overlap_row, LONG_FILE_CHUNK_OVERLAP_HELP)
        self.long_chunk_overlap_row.connect("notify::value", self._on_long_chunk_overlap_changed)
        long_group.add(self.long_chunk_overlap_row)
        page.add(long_group)

        maintenance_group = Adw.PreferencesGroup(
            title="Maintenance",
            description="Automatic cleanup of leftover working files",
        )
        self.cleanup_ensemble_temps_row = Adw.SwitchRow(
            title="Clean up old ensemble temp folders",
            subtitle="On startup, remove folders in ensemble_temps older than 7 days",
        )
        self.cleanup_ensemble_temps_row.connect(
            "notify::active",
            self._on_bool_changed,
            "is_cleanup_ensemble_temps",
        )
        maintenance_group.add(self.cleanup_ensemble_temps_row)

        self.auto_update_model_params_row = Adw.SwitchRow(
            title="Update model parameters with catalogue",
            subtitle=(
                "Refresh recognition data when the Download Center catalogue "
                "is refreshed"
            ),
        )
        self.auto_update_model_params_row.connect(
            "notify::active",
            self._on_bool_changed,
            "is_auto_update_model_params",
        )
        maintenance_group.add(self.auto_update_model_params_row)
        page.add(maintenance_group)

        return page

    # -- Load settings into widgets ---------------------------------------------

    def _reload_widgets(self) -> None:
        self._loading = True
        try:
            scheme = getattr(
                self.settings.ui.color_scheme, "value", self.settings.ui.color_scheme
            ) or "auto"
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

            if hasattr(self, "directml_row"):
                self.directml_row.set_active(bool(self.settings.process.use_directml))
            if not set_combo_value(self.device_row, self.settings.process.device or DEFAULT):
                set_combo_value(self.device_row, DEFAULT)

            from ui.shared_settings import gpu_dependent_enabled

            self.device_row.set_sensitive(
                gpu_dependent_enabled(self.settings.process.use_gpu)
            )

            self.sample_mode_row.set_active(bool(self.settings.process.sample_mode))
            self.cleanup_ensemble_temps_row.set_active(
                bool(self.settings.ensemble.cleanup_temps)
            )
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
                long_overlap = float(
                    self.settings.process.long_file_chunk_overlap_seconds or 2.0
                )
            except (TypeError, ValueError):
                long_overlap = 2.0
            self.long_chunk_overlap_row.set_value(max(0.0, min(30.0, long_overlap)))

            self._refresh_profile_list()
        finally:
            self._loading = False

    def _refresh_profile_list(self, select: typing.Any=None) -> None:
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
        self._persist_timeout_id = GLib.timeout_add(
            _PERSIST_DEBOUNCE_MS, self._flush_persist
        )

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

    def _probe_gpu_devices(self) -> None:
        from core.gpu import list_gpu_devices

        devices = list_gpu_devices()
        self.context.gpu_devices = devices
        idle_on_main(self._apply_gpu_devices, devices)

    def _apply_gpu_devices(self, devices: typing.Any) -> None:
        if not hasattr(self, "device_row"):
            return
        current = get_combo_value(self.device_row)
        opts, subtitle = self._device_row_options(devices)
        self._loading = True
        try:
            from .widgets.rows import set_combo_values

            set_combo_values(self.device_row, opts)
            self.device_row.set_subtitle(subtitle)
            if current in opts:
                set_combo_value(self.device_row, current)
        finally:
            self._loading = False

    # -- Profiles ---------------------------------------------------------------

    def _on_save_profile(self, entry_row: typing.Any) -> None:
        name = entry_row.get_text().strip()
        if not _is_valid_profile_name(name):
            self.add_toast(Adw.Toast.new("Invalid name. Use up to 25 letters, numbers, spaces or dashes"))
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

    def _on_save_profile_confirmed(self, _dialog: typing.Any, response: typing.Any, entry_row: typing.Any, name: str) -> None:
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

    def _on_load_profile_confirmed(self, _dialog: typing.Any, response: typing.Any, name: str) -> None:
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
        error = self.context.try_save_settings(trigger="profile-load")
        if error:
            self.add_toast(Adw.Toast.new(error))
        from core.debug_log import debug

        debug("settings", f"profile load name={name}")
        self._reload_widgets()
        if self._on_settings_reloaded is not None:
            self._on_settings_reloaded()
        self.add_toast(Adw.Toast.new(f'Loaded profile "{name}"'))

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

    def _on_remove_confirmed(self, _dialog: typing.Any, response: typing.Any, name: typing.Any) -> None:
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
        error = self.context.try_save_settings(trigger="reset")
        if error:
            self.add_toast(Adw.Toast.new(error))
        debug("settings", "profile reset confirmed")
        self._reload_widgets()
        if self._on_settings_reloaded is not None:
            self._on_settings_reloaded()
        self.add_toast(Adw.Toast.new("Settings reset to default"))
