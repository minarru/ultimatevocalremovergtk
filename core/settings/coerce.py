"""Coercion helpers for JSON / legacy flat settings values."""

from __future__ import annotations

from typing import Any


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


_BOOL_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("process", "use_gpu"),
        ("process", "autocast"),
        ("process", "use_directml"),
        ("process", "primary_stem_only"),
        ("process", "secondary_stem_only"),
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
        ("demucs", "is_chunk_demucs"),
        ("demucs", "is_primary_stem_only"),
        ("demucs", "is_secondary_stem_only"),
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
    }
)

_INT_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("process", "sample_mode_duration"),
        ("process", "long_file_chunk_seconds"),
        ("vr", "aggression_setting"),
        ("vr", "window_size"),
        ("vr", "crop_size"),
        ("mdx", "segment_size"),
        ("mdx", "margin"),
        ("demucs", "margin_demucs"),
        ("demucs", "shifts"),
        ("ui", "window_width"),
        ("ui", "window_height"),
    }
)

_FLOAT_FIELDS: frozenset[tuple[str, str]] = frozenset(
    {
        ("process", "amplification_threshold"),
        ("process", "long_file_chunk_overlap_seconds"),
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


def _coerce_section(section_name: str, section_data: Any) -> dict[str, Any]:
    if not isinstance(section_data, dict):
        return {}
    coerced: dict[str, Any] = {}
    for field, value in section_data.items():
        path = (section_name, field)
        if path in _BOOL_FIELDS:
            coerced[field] = as_bool(value)
        elif path in _INT_FIELDS:
            coerced[field] = as_int(value)
        elif path in _FLOAT_FIELDS:
            coerced[field] = as_float(value)
        else:
            coerced[field] = value
    return coerced


def coerce_json_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce typed fields in a nested settings JSON document."""
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
    ):
        if section in result:
            result[section] = _coerce_section(section, result[section])
    if "schema_version" in result:
        result["schema_version"] = as_int(result["schema_version"], 1)
    return result
