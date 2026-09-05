"""Run context captured for separation / ensemble / audio-tool error logs."""

from __future__ import annotations

import os
import threading
import typing
from typing import Any, Dict, List, Optional, Sequence

from bundled.constants import (
    CHOOSE_MODEL,
    DEFAULT,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)
from core.model_display import display_name_for_model
from core.model_identity import ModelIdentityService
from core.settings import Settings
from core.settings.flat_map import FLAT_TO_PATH

_LOCK = threading.Lock()
# Deliberately one shared dict, not per-thread: RunController exposes a
# single ``_running_target`` and one shared Start/Stop button, so exactly one
# of {separation, ensemble, audio tools} can be mid-run at a time. Writes
# (``update_run_error_context``/``snapshot_worker_file``) happen on that run's
# worker KThread; the read (``format_error_context``, via ``log_error``) is
# dispatched back to the *main* thread through ``GLib.idle_add``, so a
# per-thread-ident store would never see the worker's data. If this
# single-active-run invariant is ever relaxed, this module needs a real
# per-run token threaded through both the writers and ``_on_error``, not a
# thread-local — don't "fix" this with thread-local storage.
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
    "is_normalization",
    "is_match_mix_level",
    "is_prevent_export_clipping",
    "amplification_threshold",
    "long_file_chunk_seconds",
    "long_file_chunk_overlap_seconds",
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
    except Exception as exc:  # surfaced in the error log
        info["error"] = f"{type(exc).__name__}: {exc}"
        return info


def non_default_setting_lines(settings: Settings) -> List[str]:
    defaults = Settings.defaults()
    lines: List[str] = []
    for key in _PROCESS_SETTING_KEYS:
        path = FLAT_TO_PATH.get(key)
        if path is None:
            continue
        section_name, field_name = path
        value = getattr(getattr(settings, section_name), field_name)
        default = getattr(getattr(defaults, section_name), field_name)
        if value == default:
            continue
        if value == DEFAULT and default != DEFAULT:
            continue
        lines.append(f"{key}={value!r} (default {default!r})")
    return lines


def model_summary_lines(model: typing.Any) -> List[str]:
    label = (
        str(getattr(model, "model_display_label", "") or "")
        or display_name_for_model(model.process_method, model.model_name, model.repo)
    )
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


def build_separation_context(
    settings: Settings,
    repo: typing.Any,
    input_paths: Sequence[str],
    method_key: str,
) -> Dict[str, Any]:
    model_setting = _MODEL_SETTING_BY_METHOD.get(method_key)
    model_path = FLAT_TO_PATH.get(model_setting) if model_setting else None
    model_name = (
        getattr(getattr(settings, model_path[0]), model_path[1])
        if model_path
        else None
    )
    models: List[str] = []
    if model_name and model_name not in (CHOOSE_MODEL, "", None):
        try:
            label = ModelIdentityService(repo).display_label(str(model_name))
        except (TypeError, ValueError):
            label = display_name_for_model(method_key, model_name, repo)
        models.append(label or str(model_name))

    return {
        "process": method_key,
        "models": models,
        "input_files": [os.path.basename(path) for path in input_paths],
        "non_default_settings": non_default_setting_lines(settings),
    }


def build_ensemble_context(
    settings: Settings,
    input_paths: Sequence[str],
    repo: typing.Any = None,
) -> Dict[str, Any]:
    references = list(settings.ensemble.selected_models or [])
    models: List[str] = []
    identities = ModelIdentityService(repo) if repo is not None else None
    for reference in references:
        if identities is None:
            models.append(str(reference))
            continue
        try:
            models.append(identities.lookup(str(reference)).display)
        except (TypeError, ValueError):
            models.append(str(reference))
    return {
        "process": ENSEMBLE_MODE,
        "models": models,
        "input_files": [os.path.basename(path) for path in input_paths],
        "non_default_settings": non_default_setting_lines(settings),
    }


def build_audio_tools_context(
    settings: Settings,
    tool: str,
    input_paths: Sequence[str],
) -> Dict[str, Any]:
    return {
        "process": "Audio Tools",
        "tool": tool,
        "input_files": [os.path.basename(path) for path in input_paths],
        "non_default_settings": non_default_setting_lines(settings),
    }


def snapshot_worker_file(path: str, model: typing.Any=None) -> None:
    """Update context with the file/model currently being processed."""
    fields: Dict[str, Any] = {
        "audio": probe_audio_file(path),
    }
    if model is not None:
        fields["model_lines"] = model_summary_lines(model)
    update_run_error_context(**fields)
