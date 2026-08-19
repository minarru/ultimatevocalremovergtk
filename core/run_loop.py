"""Shared file/chunk pass over models for single and ensemble runs.

:func:`run_models_on_files` owns mix planning, missing-file skip, progress
binding, and the files × models × chunks loop. PCM is decoded when a file
starts and dropped after ``after_file`` so a batch holds one mix at a time.
Per-mode naming, stem collection, concat/salvage, and ensemble combine stay
on hooks supplied by the caller.

Import is torch-free. The runner is duck-typed — this module must not import
:mod:`core.job_runner` at load time.
"""
from __future__ import annotations

import os
import time
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Protocol

from bundled.constants import PROCESS_STOPPED_BY_USER

from .audio_chunking import (
    DEFAULT_SAMPLE_RATE,
    chunk_count_for_samples,
    overlaps_for_chunks,
    slice_mix,
)
from .debug_log import debug
from .error_context import snapshot_worker_file
from .inference_cleanup import release_inference_memory as _release_inference_resources
from .model_display import display_name_for_model
from .process_data import ProcessData
from .run_control import ProcessStopped, check_stopped, pausable_callback
from .separator_run import run_separator
from .settings import Settings


def _decoded_mix_for_process(audio_file: typing.Any):
    """Decode once per track so ensemble / secondary models reuse the same mix."""
    from engines.mix import prepare_mix

    return prepare_mix(audio_file)


def _progress_detail(
    *,
    file_num: int,
    file_total: int,
    model: typing.Any,
    model_num: int,
    model_count: int,
    chunk_num: int = 0,
    chunk_total: int = 0,
) -> Optional[str]:
    """Short status detail for the progress line (file / chunk / member model)."""
    parts: List[str] = []
    if file_total > 1:
        parts.append(f"File {file_num}/{file_total}")
    if chunk_total > 1 and chunk_num > 0:
        parts.append(f"Chunk {chunk_num}/{chunk_total}")
    if model is not None:
        label = (
            display_name_for_model(
                model.process_method, model.model_name, model.repo
            )
            or getattr(model, "model_basename", "")
            or ""
        )
        if model_count > 1:
            parts.append(f"Model {model_num}/{model_count}" + (f" · {label}" if label else ""))
        elif label:
            parts.append(label)
    return " · ".join(parts) if parts else None


@dataclass
class _ProgressSink:
    """Mutable last-fraction holder shared by a run's progress callback."""

    fraction: float = 0.0


@dataclass
class _ChunkUnitBudget:
    """Mutable chunk-unit total so progress can correct a duration-probe miss."""

    total: int = 0


def _bind_set_progress_bar(
    runner: Any,
    callbacks: Any,
    progress_ctx: dict[str, Any],
    *,
    total_files: int,
    units: _ChunkUnitBudget,
    sink: _ProgressSink,
) -> Callable[..., None]:
    """Map engine ``set_progress_bar(step, iterations)`` onto ``callbacks.progress``."""

    def set_progress_bar(
        step: typing.Any, inference_iterations: typing.Any = 0
    ) -> None:
        total_count = max(1, runner.true_model_count * units.total)
        base = 1.0 / total_count
        local_step = step + inference_iterations
        fraction = base * runner.iteration - base + base * local_step
        sink.fraction = fraction
        callbacks.progress(
            fraction,
            local_step=local_step,
            pass_index=max(1, runner.iteration),
            pass_total=total_count,
            detail=_progress_detail(
                file_num=progress_ctx["file_num"],
                file_total=total_files,
                model=progress_ctx["model"],
                model_num=progress_ctx["model_num"],
                model_count=progress_ctx["model_count"],
                chunk_num=progress_ctx["chunk_num"],
                chunk_total=progress_ctx["chunk_total"],
            ),
        )

    return set_progress_bar


def _long_file_chunk_settings(settings: Settings) -> tuple:
    """Return ``(chunk_seconds, overlap_seconds)``; chunk ``<= 0`` means off."""
    try:
        chunk_seconds = float(settings.process.long_file_chunk_seconds or 0.0)
    except (TypeError, ValueError):
        chunk_seconds = 0.0
    try:
        overlap_seconds = float(
            settings.process.long_file_chunk_overlap_seconds or 0.0
        )
    except (TypeError, ValueError):
        overlap_seconds = 0.0
    return chunk_seconds, overlap_seconds


def _estimated_chunk_count(
    audio_file: str, chunk_seconds: float, overlap_seconds: float
) -> int:
    """Chunk units for progress before PCM is decoded. ``1`` when chunking is off."""
    if chunk_seconds <= 0:
        return 1
    from .audio_probe import audio_duration_seconds

    duration = audio_duration_seconds(audio_file)
    if duration is None:
        return 1
    samples = max(0, int(round(float(duration) * DEFAULT_SAMPLE_RATE)))
    return max(
        1,
        chunk_count_for_samples(
            samples,
            sample_rate=DEFAULT_SAMPLE_RATE,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
        ),
    )


def _write_captured_stems(
    stem_arrays: dict,
    stem_paths: dict,
    *,
    is_normalization: bool,
    amplification_threshold: float,
    wav_type_set: typing.Any,
    save_format_name: typing.Any,
    mp3_bit_set: typing.Any,
    flac_bit_set: typing.Any,
) -> None:
    """Write deferred stem arrays to their original export paths."""
    import soundfile as sf
    from engines.separate import save_format as _save_format
    from ml import spec_utils
    from bundled.constants import FLAC
    from core.audio_io import flac_subtype, replace_audio_suffix

    for stem_name, source in stem_arrays.items():
        path = stem_paths.get(stem_name)
        if not path:
            continue
        wave = spec_utils.normalize(
            source,
            is_normalization,
            min_peak=amplification_threshold,
        )
        if save_format_name == FLAC:
            flac_path = replace_audio_suffix(path, ".flac")
            sf.write(
                flac_path,
                wave,
                44100,
                format="FLAC",
                subtype=flac_subtype(flac_bit_set),
            )
            continue
        sf.write(path, wave, 44100, subtype=wav_type_set)
        _save_format(path, save_format_name, mp3_bit_set, flac_bit_set)


@dataclass
class FileState:
    """Per-file context handed to :class:`FilePassHooks`."""

    audio_file: str
    decoded_mix: Any
    chunks: list
    chunked: bool
    ov_samples: list
    base_text: str
    file_num: int
    total_files: int
    model_count: int
    progress_ctx: dict[str, Any]
    set_progress_bar: Any
    progress_sink: _ProgressSink
    callbacks: Any
    scratch: dict = field(default_factory=dict)

    @property
    def n_chunks(self) -> int:
        return len(self.chunks)


class FilePassHooks(Protocol):
    """Per-mode callbacks for :func:`run_models_on_files`."""

    process_kind: str

    def before_file(self, runner: Any, state: FileState) -> None: ...

    def export_and_base(
        self, runner: Any, state: FileState, model: Any
    ) -> tuple[str, str]: ...

    def extra_process_data(
        self, runner: Any, state: FileState, model: Any
    ) -> dict: ...

    def after_chunk(
        self,
        runner: Any,
        state: FileState,
        model: Any,
        stems: dict,
        paths: dict,
        chunked: bool,
    ) -> None: ...

    def after_model(self, runner: Any, state: FileState, model: Any) -> None: ...

    def after_file(self, runner: Any, state: FileState) -> None: ...


def with_worker_lifecycle(
    runner: Any,
    callbacks: Any,
    label: str,
    body: Callable[[], None],
) -> None:
    """Run ``body`` and map stop/error/success onto job callbacks."""
    stime = time.perf_counter()
    time_elapsed = lambda: (
        f'Time Elapsed: {time.strftime("%H:%M:%S", time.gmtime(int(time.perf_counter() - stime)))}'
    )
    try:
        body()
        callbacks.progress(1.0)
        callbacks.console(f"\nProcess complete\n{time_elapsed()}\n")
        callbacks.complete()
    except ProcessStopped:
        debug("worker", f"{label} ProcessStopped")
        callbacks.console(PROCESS_STOPPED_BY_USER)
        callbacks.stopped()
        _release_inference_resources(runner)
    except Exception as exc:  # noqa: BLE001 - surfaced through the callback
        if runner._is_stopped:
            debug("worker", f"{label} stopped during error path")
            callbacks.console(PROCESS_STOPPED_BY_USER)
            callbacks.stopped()
            _release_inference_resources(runner)
            return
        debug("worker", f"{label} failed {type(exc).__name__}: {exc}")
        callbacks.console(f"\nProcess failed\n{time_elapsed()}\n")
        callbacks.error(exc)
        # Park GPU-resident weights so a retry is not blocked by VRAM from
        # the failed attempt (common after CUDA OOM).
        _release_inference_resources(runner, park_weights=True)
    else:
        _release_inference_resources(runner)


def run_models_on_files(
    runner: Any,
    input_paths: list[str],
    callbacks: Any,
    models: list,
    *,
    engines: tuple,
    hooks: FilePassHooks,
) -> None:
    """Decode each mix as its file starts, then run every model/chunk via ``hooks``."""
    *_, clear_gpu_cache = engines

    chunk_seconds, overlap_seconds = _long_file_chunk_settings(runner.settings)
    total_files = len(input_paths)
    file_plans: list[tuple[str, int] | None] = []
    units = _ChunkUnitBudget()
    for audio_file in input_paths:
        if not os.path.isfile(audio_file):
            file_plans.append(None)
            continue
        estimated = _estimated_chunk_count(
            audio_file, chunk_seconds, overlap_seconds
        )
        file_plans.append((audio_file, estimated))
        units.total += estimated
    if units.total <= 0:
        units.total = max(1, total_files)

    progress_sink = _ProgressSink()
    progress_ctx = {
        "file_num": 1,
        "model": None,
        "model_num": 0,
        "model_count": len(models),
        "chunk_num": 0,
        "chunk_total": 0,
    }
    debug_prefix = "ensemble separate" if hooks.process_kind == "ensemble" else "separate"

    for file_num, plan in enumerate(file_plans, start=1):
        check_stopped(runner)
        runner._cached_sources_clear()
        base_text = f"File {file_num}/{total_files} "
        progress_ctx["file_num"] = file_num

        if plan is None:
            audio_file = input_paths[file_num - 1]
            callbacks.console(
                f'\n{base_text}"{os.path.basename(audio_file)}" was not found.\n'
            )
            runner.iteration += runner.true_model_count
            continue

        audio_file, estimated_chunks = plan
        decoded_mix = _decoded_mix_for_process(audio_file)
        chunks = slice_mix(
            decoded_mix,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
        )
        units.total += len(chunks) - estimated_chunks
        if units.total < 1:
            units.total = 1
        n_chunks = len(chunks)
        progress_ctx["chunk_total"] = n_chunks
        chunked = n_chunks > 1
        if chunked:
            callbacks.console(
                f"{base_text}Long-file chunking: {n_chunks} chunks "
                f"({chunk_seconds:g}s, overlap {overlap_seconds:g}s)\n"
            )
        ov_samples = overlaps_for_chunks(chunks) if chunked else []

        set_progress_bar = pausable_callback(
            runner,
            _bind_set_progress_bar(
                runner,
                callbacks,
                progress_ctx,
                total_files=total_files,
                units=units,
                sink=progress_sink,
            ),
        )
        state = FileState(
            audio_file=audio_file,
            decoded_mix=decoded_mix,
            chunks=chunks,
            chunked=chunked,
            ov_samples=ov_samples,
            base_text=base_text,
            file_num=file_num,
            total_files=total_files,
            model_count=len(models),
            progress_ctx=progress_ctx,
            set_progress_bar=set_progress_bar,
            progress_sink=progress_sink,
            callbacks=callbacks,
        )
        hooks.before_file(runner, state)

        for model_num, current_model in enumerate(models, start=1):
            check_stopped(runner)
            progress_ctx["model"] = current_model
            progress_ctx["model_num"] = model_num
            write_to_console = pausable_callback(
                runner,
                lambda text, base_text=base_text: callbacks.console(base_text + text),
            )
            audio_file_base, export_path = hooks.export_and_base(
                runner, state, current_model
            )
            extra = hooks.extra_process_data(runner, state, current_model)

            for chunk_num, (_start, _end, mix_slice) in enumerate(chunks, start=1):
                check_stopped(runner)
                snapshot_worker_file(audio_file, current_model)
                runner._process_iteration()
                progress_ctx["chunk_num"] = chunk_num
                if chunked:
                    # Avoid cache hits from a prior chunk for the same model.
                    runner._cached_sources_clear()

                process_data = ProcessData(
                    export_path=export_path,
                    audio_file_base=audio_file_base,
                    audio_file=mix_slice if chunked else decoded_mix,
                    set_progress_bar=set_progress_bar,
                    write_to_console=write_to_console,
                    process_iteration=pausable_callback(
                        runner, runner._process_iteration
                    ),
                    check_run_control=pausable_callback(
                        runner, lambda: check_stopped(runner)
                    ),
                    cached_source_callback=runner._cached_source_callback,
                    cached_model_source_holder=runner._cached_model_source_holder,
                    list_all_models=runner.all_models,
                    capture_stems_only=chunked,
                    **extra,
                )

                def _rebuild(
                    model: Any = current_model, pdata: ProcessData = process_data
                ) -> Any:
                    return runner._build_separator(model, pdata)

                seperator = _rebuild()
                engine = type(seperator).__name__
                debug(
                    "worker",
                    f"{debug_prefix} start engine={engine} "
                    f"model={current_model.model_basename!r} "
                    f"chunk={chunk_num}/{n_chunks}",
                )
                member_stems = run_separator(
                    runner,
                    seperator,
                    callbacks=callbacks,
                    model=current_model,
                    process_kind=hooks.process_kind,
                    rebuild=_rebuild,
                ) or {}
                paths = getattr(runner, "_last_captured_stem_paths", None) or {}
                hooks.after_chunk(
                    runner, state, current_model, member_stems, paths, chunked
                )
                debug("worker", f"{debug_prefix} done engine={engine}")

            hooks.after_model(runner, state, current_model)

        hooks.after_file(runner, state)
        state.decoded_mix = None
        state.chunks = []
        state.ov_samples = []
        decoded_mix = None
        chunks = None
        clear_gpu_cache(getattr(runner, "_last_backend_name", None))


__all__ = ["run_models_on_files"]
