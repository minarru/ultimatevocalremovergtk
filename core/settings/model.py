"""Nested Settings dataclasses and flat-dict bridge."""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields
from typing import Any, TypeVar, cast

from bundled.constants import (
    ALL_STEMS,
    AUDIO_TOOL_OPTIONS,
    AUTO_PHASE,
    AUTO_SELECT,
    CHOOSE_ENSEMBLE_OPTION,
    CHOOSE_MODEL,
    CHOOSE_STEM_PAIR,
    CHUNKS,
    DEFAULT,
    DEF_OPT,
    DEMUCS_OVERLAP,
    DEMUCS_SEGMENTS,
    MANUAL_ENSEMBLE_OPTIONS,
    MAX_MIN,
    MDX_ARCH_TYPE,
    MDX_OVERLAP,
    NO_MODEL,
    WAV,
)

from .coerce import coerce_json_dict
from .defaults import SETTINGS_SCHEMA_VERSION, default_settings_dict
from .flat_map import FLAT_TO_PATH

T = TypeVar("T")


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
    method: str = MDX_ARCH_TYPE
    use_gpu: bool = False
    autocast: bool = False
    use_directml: bool = False
    device: str = DEFAULT
    primary_stem_only: bool = False
    secondary_stem_only: bool = False
    testing_audio: bool = False
    add_model_name: bool = False
    accept_any_input: bool = False
    normalization: bool = False
    match_mix_level: bool = False
    prevent_export_clipping: bool = False
    amplification_threshold: float = 0.0
    create_model_folder: bool = False
    auto_update_model_params: bool = True
    save_format: str = WAV
    wav_type: str = "PCM_16"
    mp3_bitrate: str = "320k"
    flac_bit_depth: str = "16-bit"
    export_path: str = ""
    input_paths: list = field(default_factory=list)
    last_dir: str | None = None
    sample_mode: bool = False
    sample_mode_duration: int = 30
    long_file_chunk_seconds: float = 0.0
    long_file_chunk_overlap_seconds: float = 2.0
    semitone_shift: str = "0"
    user_code: str = ""
    model_hash_table: dict = field(default_factory=dict)
    vocal_splitter: str = NO_MODEL
    vocal_splitter_enabled: bool = False
    save_inst_vocal_splitter: bool = False
    deverb_vocals: bool = False
    deverb_vocal_opt: str = "Main Vocals Only"
    voc_split_save_opt: str = "Lead Only"


@dataclass
class VrSettings:
    model: str = CHOOSE_MODEL
    aggression_setting: int = 5
    window_size: int = 512
    batch_size: str = DEF_OPT
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
    overlap_mdx: str | float = MDX_OVERLAP[0]
    overlap_mdx23: str = "8"
    is_chunk_mdxnet: bool = False
    is_mdx23_combine_stems: bool = True
    is_mdx_include_stem_complement: bool = False
    chunks: str = CHUNKS[0]
    margin: int = 44100
    compensate: str = AUTO_SELECT
    is_denoise: bool = False
    denoise_option: str = "None"
    phase_option: str = AUTO_PHASE
    phase_shifts: str = "None"
    is_save_align: bool = False
    is_match_frequency_pitch: bool = True
    is_match_silence: bool = True
    is_spec_match: bool = False
    is_mdx_c_seg_def: bool = False
    is_invert_spec: bool = False
    is_mixer_mode: bool = False
    batch_size: str = DEF_OPT
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
    stems_selected: list = field(default_factory=list)


@dataclass
class DemucsSettings:
    model: str = CHOOSE_MODEL
    segment: str = DEMUCS_SEGMENTS[0]
    overlap: float = DEMUCS_OVERLAP[0]
    shifts: int = 2
    chunks_demucs: str = CHUNKS[0]
    margin_demucs: int = 44100
    is_chunk_demucs: bool = False
    is_primary_stem_only: bool = False
    is_secondary_stem_only: bool = False
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
    main_stem: str = CHOOSE_STEM_PAIR
    type: str = MAX_MIN
    selected_models: list = field(default_factory=list)
    chosen_ensemble: str = CHOOSE_ENSEMBLE_OPTION
    save_all_outputs: bool = True
    append_ensemble_name: bool = False
    wav_ensemble: bool = False
    cleanup_temps: bool = True


@dataclass
class AudioToolsSettings:
    chosen_audio_tool: str = field(default_factory=lambda: AUDIO_TOOL_OPTIONS[0])
    choose_algorithm: str = field(default_factory=lambda: MANUAL_ENSEMBLE_OPTIONS[0])
    time_stretch_rate: float = 2.0
    pitch_rate: float = 2.0
    apollo_overlap: str = "5"
    apollo_chunk_size: str = "10"
    apollo_model: str = CHOOSE_MODEL
    is_time_correction: bool = True
    time_window: str = "3"
    intro_analysis: str = DEFAULT
    db_analysis: str = "Medium"
    file_one_entry: str = ""
    file_one_entry_full: str = ""
    file_two_entry: str = ""
    file_two_entry_full: str = ""
    dual_batch_input_paths: list = field(default_factory=list)


@dataclass
class UiSettings:
    color_scheme: str = "auto"
    window_width: int = 1040
    window_height: int = 720
    window_maximized: bool = False
    notify_process_complete: bool = True
    notify_process_failed: bool = True
    notify_download_complete: bool = True
    notify_download_failed: bool = True


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
    path: str = ""

    @classmethod
    def defaults(cls) -> Settings:
        return cls.from_json_dict(default_settings_dict())

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "process": asdict(self.process),
            "vr": asdict(self.vr),
            "mdx": asdict(self.mdx),
            "demucs": asdict(self.demucs),
            "ensemble": asdict(self.ensemble),
            "audio_tools": asdict(self.audio_tools),
            "ui": asdict(self.ui),
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Settings:
        coerced = coerce_json_dict(data or {})
        return cls(
            schema_version=coerced.get("schema_version", SETTINGS_SCHEMA_VERSION),
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
        )

    @classmethod
    def from_flat(cls, data: dict[str, Any]) -> Settings:
        settings = cls.defaults()
        settings.update(data)
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
        setattr(section, field_name, value)

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

    def save(self, path: str | None = None) -> None:
        from .io import save_settings

        save_settings(self, path)

    @classmethod
    def load(cls, path: str | None = None) -> Settings:
        from .io import load_settings

        return load_settings(path)
