"""Coercion helpers for JSON / legacy flat settings values."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, TypeVar, Union

from bundled.constants import AUTO_SELECT, DEF_OPT, DEFAULT, MAX_MIN
from core.stem_pairs import normalize_stem_pair_id
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
    OpusBitrate,
    PhaseShiftsOpt,
    TimeWindow,
    WavType,
)

E = TypeVar("E", bound=Enum)

_SENTINEL_LABELS = frozenset({DEF_OPT, DEFAULT, AUTO_SELECT, "Default", "Auto"})


def enum_value(value: Any) -> Any:
    """Underlying value of a settings enum; anything else passes through.

    Settings enums are ``str, Enum``, so ``==``, dict lookup and ``json.dumps``
    already behave as the value string — but ``str(member)`` and f-strings
    yield ``ClassName.MEMBER``. Route every filename, path and log line through
    this rather than ``str()``.
    """
    return value.value if isinstance(value, Enum) else value


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off", ""):
            return False
    return default


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _is_sentinel(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() in _SENTINEL_LABELS:
        return True
    return False


def as_optional_int(value: Any) -> Optional[int]:
    """``Default`` / ``Auto`` / ``None`` → ``None``; else int."""
    if _is_sentinel(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def as_optional_float(value: Any) -> Optional[float]:
    if _is_sentinel(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def as_optional_device(value: Any) -> Optional[str]:
    """GPU device index string, or ``None`` for Default."""
    if _is_sentinel(value) or value == "":
        return None
    text = str(value).strip()
    if ":" in text:
        text = text.split(":", 1)[-1].strip()
    if text in _SENTINEL_LABELS or text == "":
        return None
    return text


def as_chunks(value: Any) -> Union[int, str, None]:
    """Chunks setting: ``None`` (Auto), positive int, or ``\"full\"``."""
    if _is_sentinel(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.casefold() == "full":
            return "full"
        if text in _SENTINEL_LABELS:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def coerce_enum(enum_type: type[E], value: Any, default: E) -> E:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        pass
    if value not in (None, ""):
        try:
            from core.debug_log import debug

            debug(
                "settings",
                f"{enum_type.__name__} unknown value={value!r}; using {default.value!r}",
            )
        except Exception:
            pass
    return default


def coerce_ensemble_type(value: Any) -> str:
    """Normalize ``ensemble.type``; atoms must be ensemble algorithms."""
    from core.ensemble_algorithms import format_ensemble_type, parse_ensemble_type

    text = "" if value is None else str(value).strip()
    if not text:
        text = MAX_MIN
    primary, secondary = parse_ensemble_type(text)
    if "/" not in text:
        return primary
    return format_ensemble_type(primary, secondary)


_BOOL_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("process", "use_gpu"),
        ("process", "autocast"),
        ("process", "use_directml"),
        ("process", "testing_audio"),
        ("process", "add_model_name"),
        ("process", "accept_any_input"),
        ("process", "normalization"),
        ("process", "match_mix_level"),
        ("process", "prevent_export_clipping"),
        ("process", "create_model_folder"),
        ("process", "auto_update_model_params"),
        ("process", "sample_mode"),
        ("process", "vocal_splitter_enabled"),
        ("process", "save_inst_vocal_splitter"),
        ("process", "deverb_vocals"),
        ("vr", "is_tta"),
        ("vr", "is_output_image"),
        ("vr", "is_post_process"),
        ("vr", "is_high_end_process"),
        ("vr", "is_secondary_model_activate"),
        ("mdx", "is_chunk_mdxnet"),
        ("mdx", "is_mdx23_combine_stems"),
        ("mdx", "is_mdx_include_stem_complement"),
        ("mdx", "is_denoise"),
        ("mdx", "is_save_align"),
        ("mdx", "is_match_frequency_pitch"),
        ("mdx", "is_match_silence"),
        ("mdx", "is_spec_match"),
        ("mdx", "is_mdx_c_seg_def"),
        ("mdx", "is_invert_spec"),
        ("mdx", "is_mixer_mode"),
        ("mdx", "is_secondary_model_activate"),
        ("demucs", "is_split_mode"),
        ("demucs", "is_demucs_combine_stems"),
        ("demucs", "is_secondary_model_activate"),
        ("demucs", "is_pre_proc_model_activate"),
        ("demucs", "is_pre_proc_model_inst_mix"),
        ("ensemble", "save_all_outputs"),
        ("ensemble", "append_ensemble_name"),
        ("ensemble", "wav_ensemble"),
        ("ensemble", "cleanup_temps"),
        ("audio_tools", "is_time_correction"),
        ("ui", "window_maximized"),
        ("ui", "notify_process_complete"),
        ("ui", "notify_process_failed"),
        ("ui", "notify_download_complete"),
        ("ui", "notify_download_failed"),
        ("diagnostics", "include_sensitive"),
    }
)

_INT_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("process", "sample_mode_duration"),
        ("vr", "aggression_setting"),
        ("vr", "window_size"),
        ("vr", "crop_size"),
        ("mdx", "segment_size"),
        ("mdx", "margin"),
        ("mdx", "overlap_mdx23"),
        ("demucs", "shifts"),
        ("audio_tools", "apollo_overlap"),
        ("audio_tools", "apollo_chunk_size"),
        ("ui", "window_width"),
        ("ui", "window_height"),
    }
)

_FLOAT_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("process", "amplification_threshold"),
        ("process", "long_file_chunk_seconds"),
        ("process", "long_file_chunk_overlap_seconds"),
        ("process", "semitone_shift"),
        ("vr", "post_process_threshold"),
        ("vr", "voc_inst_secondary_model_scale"),
        ("vr", "other_secondary_model_scale"),
        ("vr", "bass_secondary_model_scale"),
        ("vr", "drums_secondary_model_scale"),
        ("mdx", "voc_inst_secondary_model_scale"),
        ("mdx", "other_secondary_model_scale"),
        ("mdx", "bass_secondary_model_scale"),
        ("mdx", "drums_secondary_model_scale"),
        ("demucs", "overlap"),
        ("demucs", "voc_inst_secondary_model_scale"),
        ("demucs", "other_secondary_model_scale"),
        ("demucs", "bass_secondary_model_scale"),
        ("demucs", "drums_secondary_model_scale"),
        ("audio_tools", "time_stretch_rate"),
        ("audio_tools", "pitch_rate"),
    }
)

_OPTIONAL_INT_FIELDS = frozenset(
    {
        ("vr", "batch_size"),
        ("mdx", "batch_size"),
        ("demucs", "segment"),
    }
)

_OPTIONAL_FLOAT_FIELDS = frozenset(
    {
        ("mdx", "overlap_mdx"),
        ("mdx", "compensate"),
    }
)

_CHUNKS_FIELDS = frozenset(
    {
        ("mdx", "chunks"),
    }
)

_DEVICE_FIELDS = frozenset({("process", "device")})

_ENSEMBLE_PAIR_FIELDS = frozenset({("ensemble", "main_stem")})

_ENSEMBLE_TYPE_FIELDS = frozenset({("ensemble", "type")})

_STEM_FOCUS_FIELDS = frozenset({("process", "stem_focus")})

# (section, field) → (enum type, default member)
_ENUM_FIELDS: dict[tuple[str, str], tuple[type[Enum], Enum]] = {
    ("process", "method"): (ProcessMethod, ProcessMethod.MDX),
    ("process", "save_format"): (SaveFormat, SaveFormat.FLAC),
    ("process", "wav_type"): (WavType, WavType.PCM_16),
    ("process", "mp3_bitrate"): (Mp3Bitrate, Mp3Bitrate.K320),
    ("process", "opus_bitrate"): (OpusBitrate, OpusBitrate.K192),
    ("process", "flac_bit_depth"): (FlacBitDepth, FlacBitDepth.BIT_16),
    ("process", "deverb_vocal_opt"): (
        DeverbVocalOpt,
        DeverbVocalOpt.MAIN_VOCALS_ONLY,
    ),
    ("mdx", "denoise_option"): (MdxDenoiseOption, MdxDenoiseOption.NONE),
    ("mdx", "phase_option"): (AlignPhaseOption, AlignPhaseOption.AUTOMATIC),
    ("mdx", "phase_shifts"): (PhaseShiftsOpt, PhaseShiftsOpt.NONE),
    ("ui", "color_scheme"): (ColorScheme, ColorScheme.AUTO),
    ("diagnostics", "level"): (DiagnosticLevel, DiagnosticLevel.ERRORS),
    ("audio_tools", "chosen_audio_tool"): (
        AudioTool,
        AudioTool.MANUAL_ENSEMBLE,
    ),
    ("audio_tools", "choose_algorithm"): (
        ManualEnsembleOption,
        ManualEnsembleOption.MAX_SPEC,
    ),
    ("audio_tools", "time_window"): (TimeWindow, TimeWindow.V3),
    ("audio_tools", "intro_analysis"): (IntroAnalysis, IntroAnalysis.DEFAULT),
    ("audio_tools", "db_analysis"): (DbAnalysis, DbAnalysis.MEDIUM),
}


def coerce_field(section_name: str, field: str, value: Any) -> Any:
    """Coerce one nested setting value through the canonical field rules."""
    path = (section_name, field)
    if path in _BOOL_FIELDS:
        return as_bool(value)
    if path in _INT_FIELDS:
        return as_int(value)
    if path in _FLOAT_FIELDS:
        return as_float(value)
    if path in _OPTIONAL_INT_FIELDS:
        return as_optional_int(value)
    if path in _OPTIONAL_FLOAT_FIELDS:
        return as_optional_float(value)
    if path in _CHUNKS_FIELDS:
        return as_chunks(value)
    if path in _DEVICE_FIELDS:
        return as_optional_device(value)
    if path in _ENSEMBLE_PAIR_FIELDS:
        return normalize_stem_pair_id(value)
    if path in _ENSEMBLE_TYPE_FIELDS:
        return coerce_ensemble_type(value)
    if path in _STEM_FOCUS_FIELDS:
        from core.stems import normalize_stem_focus

        return normalize_stem_focus(value)
    if enum_entry := _ENUM_FIELDS.get(path):
        enum_type, default = enum_entry
        return coerce_enum(enum_type, value, default)
    return value


def _coerce_section(section_name: str, section_data: Any) -> dict[str, Any]:
    if not isinstance(section_data, dict):
        return {}
    coerced: dict[str, Any] = {}
    for field, value in section_data.items():
        coerced[field] = coerce_field(section_name, field, value)
    return coerced


def _migrate_exclusive_flags_to_stem_focus(result: dict[str, Any]) -> None:
    """Lift leftover exclusive booleans into ``process.stem_focus`` sentinels."""
    from core.stems import FOCUS_PRIMARY, FOCUS_SECONDARY

    process = result.get("process")
    demucs = result.get("demucs")
    if not isinstance(process, dict) and not isinstance(demucs, dict):
        return
    if not isinstance(process, dict):
        process = {}
        result["process"] = process
    focus = str(process.get("stem_focus") or "").strip()
    if not focus:
        primary = bool(process.get("primary_stem_only"))
        secondary = bool(process.get("secondary_stem_only"))
        if not primary and not secondary and isinstance(demucs, dict):
            primary = bool(demucs.get("is_primary_stem_only"))
            secondary = bool(demucs.get("is_secondary_stem_only"))
        if primary and not secondary:
            process["stem_focus"] = FOCUS_PRIMARY
        elif secondary and not primary:
            process["stem_focus"] = FOCUS_SECONDARY
    process.pop("primary_stem_only", None)
    process.pop("secondary_stem_only", None)
    if isinstance(demucs, dict):
        demucs.pop("is_primary_stem_only", None)
        demucs.pop("is_secondary_stem_only", None)


def coerce_json_dict(data: Any) -> dict[str, Any]:
    """Coerce typed fields in a nested settings JSON document.

    ``Any`` in, validated ``dict`` out: this is the untrusted-JSON boundary, so
    a non-object payload degrades to ``{}`` rather than raising.
    """
    if not isinstance(data, dict):
        return {}
    result = dict(data)
    for section in (
        "process",
        "vr",
        "mdx",
        "demucs",
        "ensemble",
        "audio_tools",
        "ui",
        "diagnostics",
    ):
        if section in result:
            result[section] = _coerce_section(section, result[section])
    if "schema_version" in result:
        result["schema_version"] = as_int(result["schema_version"], 1)
    _migrate_exclusive_flags_to_stem_focus(result)
    return result


#: Flat-key → display label when the stored value is ``None`` (Default/Auto).
FLAT_SENTINEL_LABELS: dict[str, str] = {
    "device_set": DEFAULT,
    "batch_size": DEF_OPT,
    "mdx_batch_size": DEF_OPT,
    "overlap_mdx": DEF_OPT,
    "compensate": AUTO_SELECT,
    "chunks": AUTO_SELECT,
    "segment": DEF_OPT,
}


def setting_for_combo(flat_key: str, value: Any) -> Any:
    """Map a stored setting to a combo/scale display value."""
    if value is None:
        return FLAT_SENTINEL_LABELS.get(flat_key)
    if value == "full" and flat_key == "chunks":
        return "Full"
    return enum_value(value)
