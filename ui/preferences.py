"""Settings UI as an ``Adw.PreferencesDialog``.

This is the GTK4 / libadwaita port of ``UVR.py``'s ``menu_settings`` window
(tabs 1 and 2 - general + additional/audio-format/process settings). It exposes
the same options the Tkinter settings window does and binds every control to the
shared :class:`core.settings.SettingsModel` through
:class:`ui.context.AppContext`, using the exact ``DEFAULT_DATA`` keys.

Covered (Phase 2):

* General: help-hints toggle, reset-to-default (with confirmation) and
  saved-settings profiles (save / load / remove).
* Audio format: ``save_format`` and the WAV bit-depth / MP3 bitrate / FLAC bit-depth sub-options.
* General process settings: test-mode / model-name / model-folder / accept-any-
  input / notification-chimes / normalization toggles.
* Hardware: GPU conversion + CUDA device selection.
* Sample mode + sample-clip duration.

Saved-settings profiles mirror ``UVR.py``: each profile is a JSON file under
``profiles/`` named after the (space->underscore) profile name and
containing the full settings dict (the same files the Tk app reads/writes), so
profiles are interchangeable between the two front ends.

Anything advanced/per-method (secondary models, vocal splitter, change-model
defaults, deverb, the download center, ...) is intentionally left to later
phases.
"""

import json
import os
import re

from gi.repository import Adw, Gtk

from bundled.constants import (
    DEFAULT,
    DEFAULT_DATA,
    FLAC,
    FLAC_BIT_DEPTHS,
    GPU_DEVICE_NUM_OPTS,
    IS_CUDA_SELECT_HELP,
    MP3,
    MP3_BIT_RATES,
    REG_SAVE_INPUT,
    SAMPLE_MODE_CHECKBOX,
    WAV,
    WAV_TYPE,
)
from core.export_naming import preview_output_name
from core.gpu import list_gpu_devices
from core.platform import system_name
from core.paths import SETTINGS_CACHE_DIR

from .application import apply_color_scheme
from .help_text import (
    AMPLIFICATION_THRESHOLD_HELP,
    IS_AUTOCAST_HELP,
    IS_NORMALIZATION_HELP,
    LONG_FILE_CHUNK_HELP,
    LONG_FILE_CHUNK_OVERLAP_HELP,
    REMOVE_PROFILE_HINT,
    FLAC_BIT_DEPTH_HINT,
)
from .hints import set_tooltip
from .widgets.rows import get_combo_value, make_combo_row, set_combo_value, set_row_icon

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

    def save(self, name: str, data: dict) -> None:
        os.makedirs(self.directory, exist_ok=True)
        with open(self._path(name), "w") as outfile:
            outfile.write(json.dumps(data, indent=4))

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

    def remove(self, name: str) -> bool:
        path = self._path(name)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False


def _is_valid_profile_name(name: str) -> bool:
    """Mirror ``UVR.py``'s ``REG_SAVE_INPUT`` rule for profile names."""
    if not name or name != name.strip():
        return False
    if name.startswith("-") or name.endswith("-"):
        return False
    return re.fullmatch(REG_SAVE_INPUT, f" {name} ".strip()) is not None and len(name) <= 25


class PreferencesDialog(Adw.PreferencesDialog):
    """libadwaita settings dialog bound to the shared :class:`SettingsModel`."""

    def __init__(self, context, on_settings_reloaded=None):
        super().__init__()
        self.context = context
        self.settings = context.settings
        self._on_settings_reloaded = on_settings_reloaded
        self._profiles = ProfileStore()
        # Guards programmatic widget updates from being treated as user edits.
        self._loading = False

        self.set_title("Settings")
        self.set_search_enabled(False)

        self.add(self._build_general_page())
        self.add(self._build_audio_page())
        self.add(self._build_processing_page())

        self._reload_widgets()

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
        load_button = Gtk.Button(label="Load", valign=Gtk.Align.CENTER)
        load_button.connect("clicked", self._on_load_profile)
        remove_button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        set_tooltip(remove_button, REMOVE_PROFILE_HINT)
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

    def _build_audio_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title="Audio", icon_name="audio-x-generic-symbolic")

        group = Adw.PreferencesGroup(title="Audio format settings")

        self.format_row = make_combo_row("Output format", [WAV, FLAC, MP3], icon_name="waveform-symbolic")
        self.format_row.connect("notify::selected", self._on_format_changed)
        group.add(self.format_row)

        self.wav_type_row = make_combo_row("WAV type", WAV_TYPE)
        self.wav_type_row.connect("notify::selected", self._on_combo_changed, "wav_type_set")
        group.add(self.wav_type_row)

        self.mp3_bit_row = make_combo_row("MP3 bitrate", MP3_BIT_RATES)
        self.mp3_bit_row.connect("notify::selected", self._on_combo_changed, "mp3_bit_set")
        group.add(self.mp3_bit_row)

        self.flac_bit_row = make_combo_row("FLAC bit depth", FLAC_BIT_DEPTHS)
        self.flac_bit_row.connect("notify::selected", self._on_combo_changed, "flac_bit_set")
        set_tooltip(self.flac_bit_row, FLAC_BIT_DEPTH_HINT)
        group.add(self.flac_bit_row)

        page.add(group)
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
        ):
            row = Adw.SwitchRow(title=title, subtitle=subtitle)
            row.connect("notify::active", self._on_bool_changed, key)
            process_group.add(row)
            self._process_switches[key] = row
        set_tooltip(self._process_switches["is_normalization"], IS_NORMALIZATION_HELP)

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
        self.gpu_row = Adw.SwitchRow(
            title="GPU conversion",
            subtitle="Use GPU acceleration when available (CUDA, MPS, or DirectML)",
        )
        self.gpu_row.connect("notify::active", self._on_bool_changed, "is_gpu_conversion")
        set_row_icon(self.gpu_row, "pci-card-symbolic")
        hardware_group.add(self.gpu_row)

        self.autocast_row = Adw.SwitchRow(
            title="FP16 autocast",
            subtitle="Faster VR/MDX/Roformer on modern NVIDIA GPUs",
        )
        self.autocast_row.connect("notify::active", self._on_bool_changed, "is_autocast")
        set_row_icon(self.autocast_row, "emblem-system-symbolic")
        set_tooltip(self.autocast_row, IS_AUTOCAST_HELP)
        hardware_group.add(self.autocast_row)

        devices = list_gpu_devices()
        if devices:
            device_opts = [DEFAULT] + [idx for idx, _name in devices]
            device_subtitle = "Detected: " + ", ".join(
                f"{idx}: {name}" if name else idx for idx, name in devices
            )
        else:
            device_opts = list(GPU_DEVICE_NUM_OPTS)
            device_subtitle = "No GPU detected"

        self.device_row = make_combo_row("GPU device", device_opts, subtitle=device_subtitle)
        set_tooltip(self.device_row, IS_CUDA_SELECT_HELP)
        self.device_row.connect("notify::selected", self._on_combo_changed, "device_set")
        hardware_group.add(self.device_row)

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
            scheme = self.settings.get("color_scheme", "auto")
            scheme_index = next(
                (i for i, (_label, value) in enumerate(_COLOR_SCHEME_OPTIONS) if value == scheme),
                0,
            )
            self.color_scheme_row.set_selected(scheme_index)

            set_combo_value(self.format_row, self.settings.get("save_format", WAV))
            set_combo_value(self.wav_type_row, self.settings.get("wav_type_set", "PCM_16"))
            set_combo_value(self.mp3_bit_row, self.settings.get("mp3_bit_set", "320k"))
            set_combo_value(self.flac_bit_row, self.settings.get("flac_bit_set", "16-bit"))
            self._sync_format_rows()

            for key, row in self._process_switches.items():
                row.set_active(bool(self.settings.get(key)))
            try:
                amp = float(self.settings.get("amplification_threshold") or 0.0)
            except (TypeError, ValueError):
                amp = 0.0
            self.amplification_row.set_value(max(0.0, min(1.0, amp)))
            self._refresh_output_name_preview()

            for key, row in self._notification_switches.items():
                row.set_active(bool(self.settings.get(key, True)))

            self.gpu_row.set_active(bool(self.settings.get("is_gpu_conversion")))
            self.autocast_row.set_active(bool(self.settings.get("is_autocast")))
            if hasattr(self, "directml_row"):
                self.directml_row.set_active(bool(self.settings.get("is_use_directml")))
            if not set_combo_value(self.device_row, self.settings.get("device_set", DEFAULT)):
                set_combo_value(self.device_row, DEFAULT)

            self.sample_mode_row.set_active(bool(self.settings.get("model_sample_mode")))
            self.cleanup_ensemble_temps_row.set_active(
                bool(self.settings.get("is_cleanup_ensemble_temps", True))
            )
            self.auto_update_model_params_row.set_active(
                bool(self.settings.get("is_auto_update_model_params", True))
            )
            duration = self.settings.get("model_sample_mode_duration", 30)
            try:
                duration = float(duration)
            except (TypeError, ValueError):
                duration = 30.0
            self.sample_duration_row.set_value(duration)
            self._update_sample_duration_subtitle(duration)

            try:
                long_chunk = float(self.settings.get("long_file_chunk_seconds") or 0)
            except (TypeError, ValueError):
                long_chunk = 0.0
            self.long_chunk_row.set_value(max(0.0, min(3600.0, long_chunk)))
            try:
                long_overlap = float(self.settings.get("long_file_chunk_overlap_seconds") or 2.0)
            except (TypeError, ValueError):
                long_overlap = 2.0
            self.long_chunk_overlap_row.set_value(max(0.0, min(30.0, long_overlap)))

            self._refresh_profile_list()
        finally:
            self._loading = False

    def _refresh_profile_list(self, select=None) -> None:
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

    def _update_sample_duration_subtitle(self, duration) -> None:
        self.sample_duration_row.set_subtitle(SAMPLE_MODE_CHECKBOX(int(duration)))

    # -- Change handlers --------------------------------------------------------

    def _on_bool_changed(self, row, _pspec, key) -> None:
        if self._loading:
            return
        self.settings.set(key, bool(row.get_active()))
        if key in _NAMING_PREVIEW_KEYS:
            self._refresh_output_name_preview()
        self._persist()

    def _on_amplification_changed(self, row, _pspec) -> None:
        if self._loading:
            return
        value = float(row.get_value())
        self.settings.set("amplification_threshold", max(0.0, min(1.0, value)))
        self._persist()

    def _on_long_chunk_changed(self, row, _pspec) -> None:
        if self._loading:
            return
        self.settings.set("long_file_chunk_seconds", int(round(float(row.get_value()))))
        self._persist()

    def _on_long_chunk_overlap_changed(self, row, _pspec) -> None:
        if self._loading:
            return
        self.settings.set("long_file_chunk_overlap_seconds", float(row.get_value()))
        self._persist()

    def _refresh_output_name_preview(self) -> None:
        if not hasattr(self, "output_name_preview_row"):
            return
        self.output_name_preview_row.set_subtitle(preview_output_name(self.settings))

    def _on_color_scheme_changed(self, row, _pspec) -> None:
        if self._loading:
            return
        index = row.get_selected()
        if index == Gtk.INVALID_LIST_POSITION:
            return
        value = _COLOR_SCHEME_OPTIONS[index][1]
        self.settings.set("color_scheme", value)
        self._persist()
        apply_color_scheme(value)

    def _on_combo_changed(self, row, _pspec, key) -> None:
        if self._loading:
            return
        value = get_combo_value(row)
        if value is None:
            return
        self.settings.set(key, value)
        self._persist()

    def _on_format_changed(self, row, _pspec) -> None:
        self._sync_format_rows()
        self._on_combo_changed(row, _pspec, "save_format")
        self._refresh_output_name_preview()

    def _sync_format_rows(self) -> None:
        output_format = get_combo_value(self.format_row) or WAV
        self.wav_type_row.set_visible(output_format == WAV)
        self.mp3_bit_row.set_visible(output_format == MP3)
        self.flac_bit_row.set_visible(output_format == FLAC)

    def _on_duration_changed(self, row, _pspec) -> None:
        if self._loading:
            return
        value = int(row.get_value())
        self.settings.set("model_sample_mode_duration", value)
        self._update_sample_duration_subtitle(value)
        self._persist()

    def _persist(self) -> None:
        self.context.save_settings()
        if self._on_settings_reloaded is not None:
            self._on_settings_reloaded()

    # -- Profiles ---------------------------------------------------------------

    def _on_save_profile(self, entry_row) -> None:
        name = entry_row.get_text().strip()
        if not _is_valid_profile_name(name):
            self.add_toast(Adw.Toast.new("Invalid name. Use up to 25 letters, numbers, spaces or dashes"))
            return
        self._profiles.save(name, self.settings.to_dict())
        entry_row.set_text("")
        from core.debug_log import debug

        debug("settings", f"profile save name={name}")
        # Profiles are listed by file-name stem (spaces become underscores),
        # mirroring UVR.py; select that canonical form after saving.
        self._refresh_profile_list(select=name.replace(" ", "_"))
        self.add_toast(Adw.Toast.new(f'Saved profile "{name}"'))

    def _on_load_profile(self, _button) -> None:
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

    def _on_load_profile_confirmed(self, _dialog, response, name: str) -> None:
        if response != "load":
            return
        data = self._profiles.load(name)
        if data is None:
            self.add_toast(Adw.Toast.new(f'Could not load profile "{name}"'))
            return
        # Only adopt keys the settings schema knows about.
        self.settings.update({k: v for k, v in data.items() if k in DEFAULT_DATA})
        self.context.save_settings()
        from core.debug_log import debug

        debug("settings", f"profile load name={name}")
        self._reload_widgets()
        if self._on_settings_reloaded is not None:
            self._on_settings_reloaded()
        self.add_toast(Adw.Toast.new(f'Loaded profile "{name}"'))

    def _on_remove_profile(self, _button) -> None:
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

    def _on_remove_confirmed(self, _dialog, response, name) -> None:
        if response != "remove":
            return
        if self._profiles.remove(name):
            from core.debug_log import debug

            debug("settings", f"profile remove name={name}")
            self._refresh_profile_list()
            self.add_toast(Adw.Toast.new(f'Removed profile "{name}"'))

    # -- Reset ------------------------------------------------------------------

    def _on_reset_clicked(self, _button) -> None:
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

    def _on_reset_confirmed(self, _dialog, response) -> None:
        if response != "reset":
            return
        from core.debug_log import debug

        self.settings.reset_to_default()
        self.context.save_settings()
        debug("settings", "profile reset confirmed")
        self._reload_widgets()
        if self._on_settings_reloaded is not None:
            self._on_settings_reloaded()
        self.add_toast(Adw.Toast.new("Settings reset to default"))
