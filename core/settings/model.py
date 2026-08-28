"""Nested Settings dataclasses and flat-dict bridge."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields, replace
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeVar, cast

from bundled.constants import (
    ALL_STEMS,
    CHOOSE_ENSEMBLE_OPTION,
    CHOOSE_MODEL,
    DEMUCS_OVERLAP,
    MAX_MIN,
    NO_MODEL,
)
from core.types import ProcessMethod, SaveFormat
from core.types.settings_enums import (
    AlignPhaseOption,
    AudioTool,
    ColorScheme,
    DbAnalysis,
    DeverbVocalOpt,
    DiagnosticLevel,
    FlacBitDepth,
    IntroAnalysis,
    ManualEnsembleOption,
    MdxDenoiseOption,
    Mp3Bitrate,
    PhaseShiftsOpt,
    TimeWindow,
    WavType,
)

from .coerce import coerce_field, coerce_json_dict
from .defaults import SETTINGS_SCHEMA_VERSION, default_settings_dict
from .flat_map import FLAT_TO_PATH

T = TypeVar("T")

if TYPE_CHECKING:
    from core.model_identity import IdentityIndex

_MODEL_SENTINELS = frozenset({CHOOSE_MODEL, NO_MODEL, ""})
_SECONDARY_MODEL_FIELDS = (
    "voc_inst_secondary_model",
    "other_secondary_model",
    "bass_secondary_model",
    "drums_secondary_model",
)
_MODEL_PATH_FAMILIES: dict[str, frozenset[str]] = {
    "vr.model": frozenset({"vr"}),
    "mdx.model": frozenset({"mdx"}),
    "demucs.model": frozenset({"demucs"}),
    "audio_tools.apollo_model": frozenset({"apollo"}),
    "process.vocal_splitter": frozenset({"vr", "mdx"}),
    "demucs.pre_proc_model": frozenset({"vr", "mdx"}),
}
for _section_name in ("vr", "mdx", "demucs"):
    for _field_name in _SECONDARY_MODEL_FIELDS:
        _MODEL_PATH_FAMILIES[f"{_section_name}.{_field_name}"] = frozenset({"vr", "mdx", "demucs"})


def _json_value(value: Any) -> Any:
    """Convert enums in dataclass payloads to stable JSON scalar values."""
    if isinstance(value, Enum):
        return value.value
    if value is None:
        return None
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _merge_dataclass(cls: type[T], base: T, overrides: dict[str, Any] | None) -> T:
    if not overrides:
        return copy.deepcopy(base)
    valid = {f.name for f in fields(cast(Any, base))}
    merged = asdict(cast(Any, base))
    for key, value in overrides.items():
        if key in valid:
            merged[key] = copy.deepcopy(value)
    return cls(**merged)


@dataclass
class ProcessSettings:
    method: ProcessMethod = ProcessMethod.MDX
    use_gpu: bool = False
    autocast: bool = False
    use_directml: bool = False
    device: str | None = None
    stem_focus: str = ""
    testing_audio: bool = False
    add_model_name: bool = False
    accept_any_input: bool = False
    normalization: bool = False
    match_mix_level: bool = False
    prevent_export_clipping: bool = False
    amplification_threshold: float = 0.0
    create_model_folder: bool = False
    auto_update_model_params: bool = True
    save_format: SaveFormat = SaveFormat.WAV
    wav_type: WavType = WavType.PCM_16
    mp3_bitrate: Mp3Bitrate = Mp3Bitrate.K320
    flac_bit_depth: FlacBitDepth = FlacBitDepth.BIT_16
    export_path: str = ""
    input_paths: list[str] = field(default_factory=list)
    last_dir: str | None = None
    sample_mode: bool = False
    sample_mode_duration: int = 30
    long_file_chunk_seconds: float = 0.0
    long_file_chunk_overlap_seconds: float = 2.0
    semitone_shift: float = 0.0
    model_hash_table: dict = field(default_factory=dict)
    vocal_splitter: str = NO_MODEL
    vocal_splitter_enabled: bool = False
    save_inst_vocal_splitter: bool = False
    deverb_vocals: bool = False
    deverb_vocal_opt: DeverbVocalOpt = DeverbVocalOpt.MAIN_VOCALS_ONLY
    voc_split_save_opt: str = "Lead Only"


@dataclass
class VrSettings:
    model: str = CHOOSE_MODEL
    aggression_setting: int = 5
    window_size: int = 512
    batch_size: int | None = None
    crop_size: int = 256
    is_tta: bool = False
    is_output_image: bool = False
    is_post_process: bool = False
    is_high_end_process: bool = False
    post_process_threshold: float = 0.2
    voc_inst_secondary_model: str = NO_MODEL
    other_secondary_model: str = NO_MODEL
    bass_secondary_model: str = NO_MODEL
    drums_secondary_model: str = NO_MODEL
    is_secondary_model_activate: bool = False
    voc_inst_secondary_model_scale: float = 0.9
    other_secondary_model_scale: float = 0.7
    bass_secondary_model_scale: float = 0.5
    drums_secondary_model_scale: float = 0.5


@dataclass
class MdxSettings:
    model: str = CHOOSE_MODEL
    segment_size: int = 256
    overlap_mdx: float | None = None
    overlap_mdx23: int = 8
    is_chunk_mdxnet: bool = False
    is_mdx23_combine_stems: bool = True
    is_mdx_include_stem_complement: bool = False
    chunks: int | str | None = None
    margin: int = 44100
    compensate: float | None = None
    is_denoise: bool = False
    denoise_option: MdxDenoiseOption = MdxDenoiseOption.NONE
    phase_option: AlignPhaseOption = AlignPhaseOption.AUTOMATIC
    phase_shifts: PhaseShiftsOpt = PhaseShiftsOpt.NONE
    is_save_align: bool = False
    is_match_frequency_pitch: bool = True
    is_match_silence: bool = True
    is_spec_match: bool = False
    is_mdx_c_seg_def: bool = False
    is_invert_spec: bool = False
    is_mixer_mode: bool = False
    batch_size: int | None = None
    voc_inst_secondary_model: str = NO_MODEL
    other_secondary_model: str = NO_MODEL
    bass_secondary_model: str = NO_MODEL
    drums_secondary_model: str = NO_MODEL
    is_secondary_model_activate: bool = False
    voc_inst_secondary_model_scale: float = 0.9
    other_secondary_model_scale: float = 0.7
    bass_secondary_model_scale: float = 0.5
    drums_secondary_model_scale: float = 0.5
    stems: str = ALL_STEMS
    stems_selected: list[str] = field(default_factory=list)


@dataclass
class DemucsSettings:
    model: str = CHOOSE_MODEL
    segment: int | None = None
    overlap: float = DEMUCS_OVERLAP[0]
    shifts: int = 2
    is_split_mode: bool = True
    is_demucs_combine_stems: bool = True
    voc_inst_secondary_model: str = NO_MODEL
    other_secondary_model: str = NO_MODEL
    bass_secondary_model: str = NO_MODEL
    drums_secondary_model: str = NO_MODEL
    is_secondary_model_activate: bool = False
    voc_inst_secondary_model_scale: float = 0.9
    other_secondary_model_scale: float = 0.7
    bass_secondary_model_scale: float = 0.5
    drums_secondary_model_scale: float = 0.5
    stems: str = ALL_STEMS
    pre_proc_model: str = NO_MODEL
    is_pre_proc_model_activate: bool = False
    is_pre_proc_model_inst_mix: bool = False


@dataclass
class EnsembleSettings:
    main_stem: str = ""
    type: str = MAX_MIN
    selected_models: list[str] = field(default_factory=list)
    chosen_ensemble: str = CHOOSE_ENSEMBLE_OPTION
    save_all_outputs: bool = True
    append_ensemble_name: bool = False
    wav_ensemble: bool = False
    cleanup_temps: bool = True


@dataclass
class AudioToolsSettings:
    chosen_audio_tool: AudioTool = AudioTool.MANUAL_ENSEMBLE
    choose_algorithm: ManualEnsembleOption = ManualEnsembleOption.MAX_SPEC
    time_stretch_rate: float = 2.0
    pitch_rate: float = 2.0
    apollo_overlap: int = 5
    apollo_chunk_size: int = 10
    apollo_model: str = CHOOSE_MODEL
    is_time_correction: bool = True
    time_window: TimeWindow = TimeWindow.V3
    intro_analysis: IntroAnalysis = IntroAnalysis.DEFAULT
    db_analysis: DbAnalysis = DbAnalysis.MEDIUM
    file_one_entry: str = ""
    file_one_entry_full: str = ""
    file_two_entry: str = ""
    file_two_entry_full: str = ""
    dual_batch_input_paths: list[str] = field(default_factory=list)


@dataclass
class UiSettings:
    color_scheme: ColorScheme = ColorScheme.AUTO
    window_width: int = 1040
    window_height: int = 720
    window_maximized: bool = False
    notify_process_complete: bool = True
    notify_process_failed: bool = True
    notify_download_complete: bool = True
    notify_download_failed: bool = True
    confirm_processing_plan: bool = True


@dataclass
class DiagnosticsSettings:
    level: DiagnosticLevel = DiagnosticLevel.ERRORS
    include_sensitive: bool = False


@dataclass
class Settings:
    schema_version: int = SETTINGS_SCHEMA_VERSION
    process: ProcessSettings = field(default_factory=ProcessSettings)
    vr: VrSettings = field(default_factory=VrSettings)
    mdx: MdxSettings = field(default_factory=MdxSettings)
    demucs: DemucsSettings = field(default_factory=DemucsSettings)
    ensemble: EnsembleSettings = field(default_factory=EnsembleSettings)
    audio_tools: AudioToolsSettings = field(default_factory=AudioToolsSettings)
    ui: UiSettings = field(default_factory=UiSettings)
    diagnostics: DiagnosticsSettings = field(default_factory=DiagnosticsSettings)
    path: str = ""
    validation_warnings: list[str] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def defaults(cls) -> Settings:
        return cls.from_json_dict(default_settings_dict())

    def to_json_dict(self) -> dict[str, Any]:
        # model_hash_table can gain entries from the JobRunner worker thread
        # (core.model_hash_cache.remember) while this runs on the main
        # thread; asdict() below iterates the live dict, so snapshot it
        # through the same lock first or a concurrent insert raises
        # "dictionary changed size during iteration".
        from core.model_hash_cache import snapshot_table

        process = replace(
            self.process,
            model_hash_table=snapshot_table(self.process.model_hash_table),
        )
        return _json_value(
            {
                "schema_version": self.schema_version,
                "process": asdict(process),
                "vr": asdict(self.vr),
                "mdx": asdict(self.mdx),
                "demucs": asdict(self.demucs),
                "ensemble": asdict(self.ensemble),
                "audio_tools": asdict(self.audio_tools),
                "ui": asdict(self.ui),
                "diagnostics": asdict(self.diagnostics),
            }
        )

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Settings:
        raw_data = data
        raw_schema = raw_data.get("schema_version", 1)
        try:
            source_schema = int(raw_schema)
        except (TypeError, ValueError):
            source_schema = 1
        raw_ensemble = raw_data.get("ensemble")
        raw_main_stem = raw_ensemble.get("main_stem") if isinstance(raw_ensemble, dict) else ""
        coerced = coerce_json_dict(data or {})
        # Stamp the current version, never the file's: ``coerce_json_dict`` has
        # already migrated the payload, so keeping the old number would leave a
        # v3 file claiming v1 and mis-gate the next migration.
        settings = cls(
            schema_version=SETTINGS_SCHEMA_VERSION,
            process=_merge_dataclass(ProcessSettings, ProcessSettings(), coerced.get("process")),
            vr=_merge_dataclass(VrSettings, VrSettings(), coerced.get("vr")),
            mdx=_merge_dataclass(MdxSettings, MdxSettings(), coerced.get("mdx")),
            demucs=_merge_dataclass(DemucsSettings, DemucsSettings(), coerced.get("demucs")),
            ensemble=_merge_dataclass(
                EnsembleSettings, EnsembleSettings(), coerced.get("ensemble")
            ),
            audio_tools=_merge_dataclass(
                AudioToolsSettings, AudioToolsSettings(), coerced.get("audio_tools")
            ),
            ui=_merge_dataclass(UiSettings, UiSettings(), coerced.get("ui")),
            diagnostics=_merge_dataclass(
                DiagnosticsSettings,
                DiagnosticsSettings(),
                coerced.get("diagnostics"),
            ),
        )
        if source_schema < SETTINGS_SCHEMA_VERSION:
            settings.validation_warnings.append(
                "ensemble.main_stem: settings schema predates semantic pair IDs; choose an ensemble stem pair again"
            )
            settings.ensemble.main_stem = ""
        elif raw_main_stem not in (None, "") and not settings.ensemble.main_stem:
            settings.validation_warnings.append(
                "ensemble.main_stem: unknown semantic pair/mode ID; choose an ensemble stem pair again"
            )
        settings.validate_model_references()
        return settings

    def _model_reference_values(self) -> list[tuple[str, Any, frozenset[str]]]:
        references: list[tuple[str, Any, frozenset[str]]] = []
        for path, allowed_families in _MODEL_PATH_FAMILIES.items():
            section_name, field_name = path.split(".", 1)
            references.append(
                (path, getattr(getattr(self, section_name), field_name), allowed_families)
            )
        references.extend(
            (
                f"ensemble.selected_models[{index}]",
                value,
                frozenset({"vr", "mdx", "demucs"}),
            )
            for index, value in enumerate(self.ensemble.selected_models)
        )
        return references

    def validate_model_references(self, index: IdentityIndex | None = None) -> list[str]:
        """Validate stored identities without replacing the original text.

        With no index this performs persistence syntax validation only.  A
        repository-bound :class:`~core.model_identity.IdentityIndex` adds
        exact existence, installation, identity-completeness, and per-field
        family checks.
        """
        from core.model_identity import parse_stored_model_id

        warnings: list[str] = list(self.validation_warnings)
        for path, value, allowed_families in self._model_reference_values():
            if isinstance(value, str) and value in _MODEL_SENTINELS:
                continue
            if not isinstance(value, str):
                warning = (
                    f"{path}: expected canonical model ID family:basename or a "
                    f"permitted sentinel; preserved {value!r}"
                )
                if warning not in warnings:
                    warnings.append(warning)
                continue
            try:
                parsed = parse_stored_model_id(value)
            except ValueError:
                warning = (
                    f"{path}: expected canonical model ID family:basename or a "
                    f"permitted sentinel; preserved {value!r}"
                )
                if warning not in warnings:
                    warnings.append(warning)
                continue
            if index is None:
                continue
            try:
                record = index.lookup(parsed.value)
            except ValueError as exc:
                warning = f"{path}: {exc}"
                if warning not in warnings:
                    warnings.append(warning)
                continue
            if record.family not in allowed_families:
                expected = ", ".join(sorted(allowed_families))
                warning = f"{path}: model {record.id!r} is not eligible; requires family {expected}"
                if warning not in warnings:
                    warnings.append(warning)
            if not record.installed:
                warning = f"{path}: model {record.id!r} is not installed"
                if warning not in warnings:
                    warnings.append(warning)
            if not record.identity_complete:
                detail = record.identity_error or "identity metadata is incomplete"
                warning = f"{path}: model {record.id!r}: {detail}"
                if warning not in warnings:
                    warnings.append(warning)
        self.validation_warnings = warnings
        return list(warnings)

    @classmethod
    def from_flat(cls, data: dict[str, Any]) -> Settings:
        settings = cls.defaults()
        settings.update(data)
        from .coerce import _migrate_exclusive_flags_to_stem_focus

        nested = {
            "process": {
                "stem_focus": settings.process.stem_focus,
                "primary_stem_only": data.get("is_primary_stem_only"),
                "secondary_stem_only": data.get("is_secondary_stem_only"),
            },
            "demucs": {
                "is_primary_stem_only": data.get("is_primary_stem_only_Demucs"),
                "is_secondary_stem_only": data.get("is_secondary_stem_only_Demucs"),
            },
        }
        _migrate_exclusive_flags_to_stem_focus(nested)
        process = nested.get("process")
        if isinstance(process, dict) and process.get("stem_focus"):
            settings.process.stem_focus = str(process["stem_focus"])
        settings.validate_model_references()
        return settings

    def get(self, key: str, default: Any = None) -> Any:
        mapping = FLAT_TO_PATH.get(key)
        if mapping is None:
            return default
        section_name, field_name = mapping
        section = getattr(self, section_name)
        return getattr(section, field_name, default)

    def set(self, key: str, value: Any) -> None:
        mapping = FLAT_TO_PATH.get(key)
        if mapping is None:
            return
        section_name, field_name = mapping
        section = getattr(self, section_name)
        setattr(
            section,
            field_name,
            coerce_field(section_name, field_name, value),
        )

    def to_dict(self) -> dict[str, Any]:
        return {flat_key: self.get(flat_key) for flat_key in FLAT_TO_PATH}

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value)

    def reset_to_default(self) -> None:
        fresh = self.defaults()
        self.schema_version = fresh.schema_version
        self.process = copy.deepcopy(fresh.process)
        self.vr = copy.deepcopy(fresh.vr)
        self.mdx = copy.deepcopy(fresh.mdx)
        self.demucs = copy.deepcopy(fresh.demucs)
        self.ensemble = copy.deepcopy(fresh.ensemble)
        self.audio_tools = copy.deepcopy(fresh.audio_tools)
        self.ui = copy.deepcopy(fresh.ui)
        self.diagnostics = copy.deepcopy(fresh.diagnostics)
        self.validation_warnings = list(fresh.validation_warnings)

    def save(self, path: str | None = None) -> None:
        from .io import save_settings

        save_settings(self, path)

    @classmethod
    def load(cls, path: str | None = None) -> Settings:
        from .io import load_settings

        return load_settings(path)
