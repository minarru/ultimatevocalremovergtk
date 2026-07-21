"""Run context captured for separation / ensemble / audio-tool error logs."""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional, Sequence

from bundled.constants import (
    CHOOSE_MODEL,
    DEFAULT,
    DEFAULT_DATA,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
)
from core.model_display import display_name_for_model

_LOCK = threading.Lock()
_CONTEXT: Dict[str, Any] = {}

_MODEL_SETTING_BY_METHOD = {
    VR_ARCH_PM: "vr_model",
    MDX_ARCH_TYPE: "mdx_net_model",
    DEMUCS_ARCH_TYPE: "demucs_model",
}

_PROCESS_SETTING_KEYS = (
    "model_sample_mode",
    "model_sample_mode_duration",
    "is_gpu_conversion",
    "device_set",
    "is_use_directml",
    "is_primary_stem_only",
    "is_secondary_stem_only",
    "is_normalization",
    "is_accept_any_input",
    "aggression_setting",
    "window_size",
    "batch_size",
    "crop_size",
    "is_tta",
    "is_post_process",
    "is_high_end_process",
    "post_process_threshold",
    "mdx_segment_size",
    "margin",
    "mdx_batch_size",
    "is_mdx_c_seg_def",
    "overlap",
    "overlap_mdx",
    "overlap_mdx23",
    "mdx_stems",
    "denoise_option",
    "semitone_shift",
    "is_invert_spec",
    "is_mdx23_combine_stems",
    "is_mdx_include_stem_complement",
    "mdx_is_secondary_model_activate",
    "vr_is_secondary_model_activate",
    "demucs_stems",
    "is_chunk_demucs",
    "is_chunk_mdxnet",
    "is_split_mode",
    "is_demucs_combine_stems",
    "demucs_is_secondary_model_activate",
    "ensemble_main_stem",
    "ensemble_type",
    "is_save_all_outputs_ensemble",
    "is_append_ensemble_name",
    "chosen_ensemble",
    "is_testing_audio",
    "is_add_model_name",
    "is_create_model_folder",
)


def clear_run_error_context() -> None:
    with _LOCK:
        _CONTEXT.clear()


def set_run_error_context(**fields: Any) -> None:
    with _LOCK:
        _CONTEXT.clear()
        _CONTEXT.update(fields)


def update_run_error_context(**fields: Any) -> None:
    with _LOCK:
        _CONTEXT.update(fields)


def get_run_error_context() -> Dict[str, Any]:
    with _LOCK:
        return dict(_CONTEXT)


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def probe_audio_file(path: str) -> Dict[str, Any]:
    """Return native file metadata for error reports."""
    info: Dict[str, Any] = {
        "path": path,
        "basename": os.path.basename(path),
        "valid": False,
        "sample_rate": None,
        "channels": None,
        "duration_sec": None,
        "frames": None,
        "format": None,
        "error": None,
    }
    if not os.path.isfile(path):
        info["error"] = "file not found"
        return info

    try:
        import soundfile as sf

        meta = sf.info(path)
        info.update(
            valid=True,
            sample_rate=int(meta.samplerate) if meta.samplerate else None,
            channels=int(meta.channels) if meta.channels else None,
            frames=int(meta.frames) if meta.frames else None,
            format=str(meta.format) if meta.format else None,
        )
        if meta.samplerate and meta.frames:
            info["duration_sec"] = meta.frames / meta.samplerate
        return info
    except Exception:
        pass

    try:
        import contextlib
        import wave

        with contextlib.closing(wave.open(path, "r")) as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
            info.update(
                valid=True,
                sample_rate=rate,
                channels=handle.getnchannels(),
                frames=frames,
                format="WAV",
            )
            if rate:
                info["duration_sec"] = frames / float(rate)
            return info
    except Exception:
        pass

    try:
        import librosa

        duration = librosa.get_duration(path=path)
        info.update(valid=True, duration_sec=float(duration))
        return info
    except Exception as exc:  # noqa: BLE001 - surfaced in the error log
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info


def non_default_setting_lines(settings) -> List[str]:
    lines: List[str] = []
    for key in _PROCESS_SETTING_KEYS:
        if key not in DEFAULT_DATA:
            continue
        value = settings.get(key)
        default = DEFAULT_DATA[key]
        if value == default:
            continue
        if value == DEFAULT and default != DEFAULT:
            continue
        lines.append(f"{key}={value!r} (default {default!r})")
    return lines


def model_summary_lines(model) -> List[str]:
    label = display_name_for_model(model.process_method, model.model_name, model.repo)
    lines = [
        f"model={label or model.model_name}",
        f"basename={model.model_basename or '(unknown)'}",
    ]
    if model.process_method == MDX_ARCH_TYPE:
        engine = "MDX-C"
        if getattr(model, "is_roformer", False):
            engine = "Roformer"
        elif getattr(model, "is_mdx_c", False):
            engine = "MDX-C"
        else:
            engine = "MDX-Net"
        lines.append(f"engine={engine}")
        lines.append(f"mdx_segment_size={model.mdx_segment_size}")
        if getattr(model, "is_mdx_c_seg_def", False):
            lines.append("segment_size_source=inference.dim_t")
        if getattr(model, "overlap_mdx23", None) is not None:
            lines.append(f"overlap_mdx23={model.overlap_mdx23}")
        if getattr(model, "overlap_mdx", None) is not None:
            lines.append(f"overlap_mdx={model.overlap_mdx}")
        config_yaml = ""
        model_data = getattr(model, "model_data", None) or {}
        if isinstance(model_data, dict):
            config_yaml = str(model_data.get("config_yaml") or "")
        if config_yaml:
            lines.append(f"config_yaml={config_yaml}")
    elif model.process_method == VR_ARCH_TYPE:
        lines.append("engine=VR")
        lines.append(f"window_size={model.window_size}")
        lines.append(f"aggression_setting={model.aggression_setting}")
        lines.append(f"model_samplerate={model.model_samplerate}")
    elif model.process_method == DEMUCS_ARCH_TYPE:
        lines.append("engine=Demucs")
        lines.append(f"demucs_stems={model.demucs_stems}")
        if getattr(model, "overlap", None) is not None:
            lines.append(f"overlap={model.overlap}")
    if getattr(model, "is_secondary_model_activated", False):
        lines.append("secondary_model=enabled")
    return lines


def _audio_lines(info: Dict[str, Any]) -> List[str]:
    if not info:
        return []
    lines = [f"file={info.get('basename') or info.get('path') or '(unknown)'}"]
    if info.get("valid"):
        if info.get("sample_rate") is not None:
            lines.append(f"native_sample_rate={info['sample_rate']} Hz")
        if info.get("channels") is not None:
            lines.append(f"channels={info['channels']}")
        if info.get("duration_sec") is not None:
            lines.append(f"duration={_format_duration(info['duration_sec'])} ({info['duration_sec']:.2f}s)")
        if info.get("frames") is not None:
            lines.append(f"frames={info['frames']}")
        if info.get("format"):
            lines.append(f"format={info['format']}")
        lines.append("processing_sample_rate=44100 Hz")
    elif info.get("error"):
        lines.append(f"audio_probe_error={info['error']}")
    return lines


def format_error_context(context: Optional[Dict[str, Any]] = None) -> str:
    """Render the stored run context for inclusion in the error log."""
    ctx = context if context is not None else get_run_error_context()
    if not ctx:
        return ""

    lines = ["Run Context:", ""]

    process = ctx.get("process")
    if process:
        lines.append(f"Process: {process}")

    tool = ctx.get("tool")
    if tool:
        lines.append(f"Tool: {tool}")

    models = ctx.get("models") or []
    if models:
        lines.append("Models:")
        lines.extend(f"  - {name}" for name in models)

    model_lines = ctx.get("model_lines") or []
    if model_lines:
        lines.append("Active model:")
        lines.extend(f"  {line}" for line in model_lines)

    input_files = ctx.get("input_files") or []
    if input_files:
        lines.append("Input files:")
        lines.extend(f"  - {path}" for path in input_files)

    audio_lines = _audio_lines(ctx.get("audio") or {})
    if audio_lines:
        lines.append("Current input:")
        lines.extend(f"  {line}" for line in audio_lines)

    settings_lines = ctx.get("non_default_settings") or []
    if settings_lines:
        lines.append("Non-default settings:")
        lines.extend(f"  {line}" for line in settings_lines)

    if lines[-1] != "":
        lines.append("")
    return "\n".join(lines)


def build_separation_context(settings, repo, input_paths: Sequence[str], method_key: str) -> Dict[str, Any]:
    model_setting = _MODEL_SETTING_BY_METHOD.get(method_key)
    model_name = settings.get(model_setting) if model_setting else None
    models: List[str] = []
    if model_name and model_name not in (CHOOSE_MODEL, "", None):
        label = display_name_for_model(method_key, model_name, repo)
        models.append(label or str(model_name))

    return {
        "process": method_key,
        "models": models,
        "input_files": [os.path.basename(path) for path in input_paths],
        "non_default_settings": non_default_setting_lines(settings),
    }


def build_ensemble_context(settings, input_paths: Sequence[str]) -> Dict[str, Any]:
    models = list(settings.get("selected_models") or [])
    return {
        "process": ENSEMBLE_MODE,
        "models": models,
        "input_files": [os.path.basename(path) for path in input_paths],
        "non_default_settings": non_default_setting_lines(settings),
    }


def build_audio_tools_context(
    settings,
    tool: str,
    input_paths: Sequence[str],
) -> Dict[str, Any]:
    return {
        "process": "Audio Tools",
        "tool": tool,
        "input_files": [os.path.basename(path) for path in input_paths],
        "non_default_settings": non_default_setting_lines(settings),
    }


def snapshot_worker_file(path: str, model=None) -> None:
    """Update context with the file/model currently being processed."""
    fields: Dict[str, Any] = {
        "audio": probe_audio_file(path),
    }
    if model is not None:
        fields["model_lines"] = model_summary_lines(model)
    update_run_error_context(**fields)
