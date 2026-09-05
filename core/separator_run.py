"""One separator inference pass plus mid-run CUDA OOM recovery.

:func:`run_separator` is the JobRunner inference unit: prepare VRAM, call
``seperator.seperate()``, capture stem arrays, then release. When callbacks
and a rebuild hook are present it retries with a smaller MDX segment or
exports completed ensemble members.

Import is torch-free (``torch`` is loaded only inside :func:`is_oom_exc`).
The runner is duck-typed — this module must not import :mod:`core.job_runner`
at load time.
"""

from __future__ import annotations

import os
import typing
from typing import Any, Callable

from .audio_io import resolve_wav_type_set, save_format
from .debug_log import debug
from .ensembler import _capture_separator_stem_arrays, _capture_separator_stem_paths
from .inference_cleanup import (
    release_inference_memory as _release_inference_resources,
)
from .inference_cleanup import (
    release_separator,
)
from .model_display import display_name_for_model
from .oom_choice import (
    OOM_CHOICE_AUTO,
    OOM_CHOICE_EXPORT,
    OOM_CHOICE_RETRY,
    OOM_CHOICE_STOP,
    OomChoiceRequest,
)
from .oom_markers import is_oom_message
from .oom_segment import (
    backoff_candidates,
    default_segment,
    effective_segment,
    supports_segment_backoff,
)
from .run_control import ProcessStopped, check_stopped


def apply_segment_override(runner: Any, model: Any, seperator: Any = None) -> None:
    """Apply run-local MDX segment override to model and optional separator."""
    if runner._mdx_segment_override is None:
        return
    size = int(runner._mdx_segment_override)
    if hasattr(model, "mdx_segment_size"):
        model.mdx_segment_size = size
    if hasattr(model, "is_mdx_c_seg_def"):
        model.is_mdx_c_seg_def = False
    if seperator is not None:
        if hasattr(seperator, "mdx_segment_size"):
            seperator.mdx_segment_size = size
        if hasattr(seperator, "is_mdx_c_seg_def"):
            seperator.is_mdx_c_seg_def = False


def park_after_oom(runner: Any, seperator: Any = None) -> None:
    """Free GPU-resident weights after an OOM so the dialog is not under pressure."""
    if seperator is not None:
        release_separator(seperator)
        if runner._active_separator is seperator:
            runner._active_separator = None
    _release_inference_resources(runner, park_weights=True)


def is_oom_exc(exc: BaseException) -> bool:
    try:
        import torch

        if isinstance(exc, torch.cuda.OutOfMemoryError):
            return True
    except Exception:
        pass
    return is_oom_message(str(exc))


def prepare_separator_vram(runner: Any, seperator: typing.Any) -> None:
    """Park unused cached weights when free VRAM is tight before inference."""
    from engines.model_weight_cache import (
        ensure_weight_cache_vram_headroom,
        model_file_identity,
    )

    prefer = model_file_identity(getattr(seperator, "model_path", "") or "")
    ensure_weight_cache_vram_headroom(
        getattr(seperator, "device", None),
        protect_identities=runner._run_protect_identities or None,
        prefer_gpu_identity=prefer,
    )


def run_separate_pass(seperator: typing.Any, *, runner: Any = None) -> dict:
    """Run ``seperate()`` then ``finish_export``, always releasing the engine.

    With ``runner``, also prepare VRAM and return captured stem arrays (job
    path). Without it, return the ``finish_export`` sources dict (nested
    secondary / vocal-split path).
    """
    if runner is not None:
        runner._active_separator = seperator
        runner._last_backend_name = getattr(seperator, "_backend_name", None)
        runner._last_captured_stem_paths = {}
    try:
        if runner is not None:
            prepare_separator_vram(runner, seperator)
        from engines.stem_writer import ExportPlan, finish_export

        plan = seperator.seperate()
        if isinstance(plan, ExportPlan):
            sources = finish_export(seperator, plan)
        elif plan is None:
            sources = finish_export(seperator, ExportPlan())
        else:
            sources = finish_export(seperator, ExportPlan(sources=dict(plan)))
        if runner is not None:
            stems = _capture_separator_stem_arrays(seperator)
            runner._last_captured_stem_paths = _capture_separator_stem_paths(seperator)
            return stems
        return sources
    finally:
        debug("cleanup", f"_run_seperator finally engine={type(seperator).__name__}")
        release_separator(seperator)
        if runner is not None and runner._active_separator is seperator:
            runner._active_separator = None


def run_separator_once(runner: Any, seperator: typing.Any) -> dict:
    """Run one separator once and return captured stem arrays."""
    return run_separate_pass(seperator, runner=runner)


def run_separator(
    runner: Any,
    seperator: Any,
    *,
    callbacks: Any = None,
    model: Any = None,
    process_kind: str = "separation",
    rebuild: Callable[[], Any] | None = None,
) -> dict:
    """Run one separator with mid-run CUDA OOM recovery when callbacks allow it."""
    if callbacks is None or rebuild is None or model is None:
        return run_separator_once(runner, seperator)

    build = rebuild
    active = seperator
    apply_segment_override(runner, model, active)

    while True:
        check_stopped(runner)
        try:
            return run_separator_once(runner, active)
        except ProcessStopped:
            raise
        except Exception as exc:
            if not is_oom_exc(exc):
                raise
            debug("worker", f"oom during separate: {type(exc).__name__}: {exc}")
            park_after_oom(runner, active)
            active = None

            current = effective_segment(model)
            default = default_segment(model)
            candidates = (
                backoff_candidates(current, default) if supports_segment_backoff(model) else []
            )
            can_retry = bool(candidates)
            can_export = process_kind == "ensemble" and bool(runner._ensemble_salvage_members)
            first_retry = candidates[0] if candidates else None
            try:
                model_label = (
                    str(getattr(model, "model_display_label", "") or "")
                    or (
                        display_name_for_model(model.process_method, model.model_name, model.repo)
                        if model is not None
                        else ""
                    )
                    or getattr(model, "model_basename", "")
                    or ""
                )
            except Exception:  # best-effort label for the dialog
                model_label = str(
                    getattr(model, "model_name", None) or getattr(model, "model_basename", "") or ""
                )

            while True:
                check_stopped(runner)
                request = OomChoiceRequest(
                    process_kind=process_kind,
                    model_label=model_label,
                    current_segment=current,
                    default_segment=default,
                    first_retry_segment=first_retry,
                    can_export=can_export,
                    can_retry=can_retry,
                    completed_members=len(runner._ensemble_salvage_members),
                )
                choice = callbacks.request_oom_choice(request, runner)

                if choice == OOM_CHOICE_EXPORT:
                    if can_export:
                        export_ensemble_salvage(runner, callbacks)
                    raise ProcessStopped() from exc

                if choice == OOM_CHOICE_STOP:
                    raise ProcessStopped() from exc

                if choice in (OOM_CHOICE_RETRY, OOM_CHOICE_AUTO):
                    if not candidates:
                        if choice == OOM_CHOICE_AUTO:
                            raise exc
                        can_retry = False
                        first_retry = None
                        continue

                    last_oom = exc
                    for segment in candidates:
                        check_stopped(runner)
                        runner._mdx_segment_override = int(segment)
                        apply_segment_override(runner, model)
                        callbacks.console(f"CUDA OOM — retrying with segment size {segment}\n")
                        try:
                            active = build()
                            apply_segment_override(runner, model, active)
                            return run_separator_once(runner, active)
                        except ProcessStopped:
                            raise
                        except Exception as retry_exc:
                            if not is_oom_exc(retry_exc):
                                raise
                            last_oom = retry_exc
                            debug(
                                "worker",
                                f"oom retry failed segment={segment}: {retry_exc}",
                            )
                            park_after_oom(runner, active)
                            active = None
                    if choice == OOM_CHOICE_AUTO:
                        raise last_oom from exc
                    # Both candidates failed — re-ask (retry may now be empty).
                    current = effective_segment(model)
                    candidates = (
                        backoff_candidates(current, default)
                        if supports_segment_backoff(model)
                        else []
                    )
                    can_retry = bool(candidates)
                    first_retry = candidates[0] if candidates else None
                    can_export = process_kind == "ensemble" and bool(
                        runner._ensemble_salvage_members
                    )
                    continue

                # Unknown choice — treat as stop.
                raise ProcessStopped() from exc


def export_ensemble_salvage(runner: Any, callbacks: Any) -> None:
    """Write completed ensemble member stems into the user export folder."""
    from .run_loop import _write_captured_stems

    export_root = str(runner.settings.process.export_path or "")
    if not export_root:
        callbacks.console("OOM export skipped — export path is empty\n")
        return
    os.makedirs(export_root, exist_ok=True)
    members = list(runner._ensemble_salvage_members)
    if not members:
        callbacks.console("OOM export skipped — no completed members\n")
        return

    wav_type_set = resolve_wav_type_set(runner.settings)
    save_format_name = runner.settings.process.save_format.value
    mp3_bit_set = runner.settings.process.mp3_bitrate
    flac_bit_set = runner.settings.process.flac_bit_depth
    opus_bit_set = runner.settings.process.opus_bitrate
    try:
        amplification_threshold = float(runner.settings.process.amplification_threshold or 0.0)
    except (TypeError, ValueError):
        amplification_threshold = 0.0
    written = 0
    for member in members:
        arrays = member.get("arrays") or {}
        paths = member.get("paths") or {}
        remapped: dict[str, str] = {}
        for stem_tag, path in paths.items():
            name = os.path.basename(path) if path else f"{stem_tag}.wav"
            remapped[stem_tag] = os.path.join(export_root, name)
        if not remapped and arrays:
            base = member.get("audio_file_base") or "ensemble_member"
            for stem_tag in arrays:
                remapped[stem_tag] = os.path.join(export_root, f"{base} ({stem_tag}).wav")
        if not arrays:
            # Save-all (or disk) path: copy any known member files into export root.
            for stem_tag, path in paths.items():
                if path and os.path.isfile(path):
                    dest = remapped.get(stem_tag) or os.path.join(
                        export_root, os.path.basename(path)
                    )
                    if os.path.abspath(path) != os.path.abspath(dest):
                        import shutil

                        shutil.copy2(path, dest)
                    save_format(dest, save_format_name, mp3_bit_set, flac_bit_set, opus_bit_set)
                    written += 1
            continue
        _write_captured_stems(
            arrays,
            remapped,
            is_normalization=bool(runner.settings.process.normalization),
            amplification_threshold=amplification_threshold,
            wav_type_set=wav_type_set,
            save_format_name=save_format_name,
            mp3_bit_set=mp3_bit_set,
            flac_bit_set=flac_bit_set,
            opus_bit_set=opus_bit_set,
        )
        written += len(arrays)
    if written == 0:
        raise RuntimeError("OOM salvage found no usable completed ensemble outputs")
    runner._last_oom_exported = True
    callbacks.console(f"Exported {written} completed ensemble stem(s) to {export_root}\n")


__all__ = ["run_separator", "run_separate_pass"]
