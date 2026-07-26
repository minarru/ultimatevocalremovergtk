"""Framework-agnostic separation job runner.

``JobRunner`` reimplements the orchestration in ``MainWindow.process_start`` and
its ``KThread`` worker, but without any Tkinter coupling: progress, console and
completion are delivered through plain callbacks. The runner deliberately knows
nothing about GTK; the ``ui`` layer wraps these callbacks with
``GLib.idle_add`` (see :mod:`ui.dispatch`) so they run on the main loop.

Supports single-model separation, ensemble runs, sample mode, and secondary /
vocal-splitter / Demucs pre-process machinery. Audio tools live in
:mod:`core.audio_tools`.
"""

import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

from bundled.constants import (
    CHOOSE_ENSEMBLE_OPTION,
    CHOOSE_STEM_PAIR,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    FOUR_STEM_ENSEMBLE,
    INST_STEM,
    MAX_MIN,
    MAX_SPEC,
    MDX_ARCH_TYPE,
    MULTI_STEM_ENSEMBLE,
    PRIMARY_STEM,
    PROCESS_STOPPED_BY_USER,
    SECONDARY_STEM,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

from . import paths
from .audio_io import resolve_wav_type_set
from .export_naming import (
    format_stem_basename,
    format_track_base,
    sanitize_filename_component,
    testing_timestamp_prefix,
    track_basename_from_path,
)
from .model_data import (
    ModelData,
    ModelRepository,
    assemble_model_data,
)
from .sample_mode import prepare_input_paths
from .settings import SettingsModel
from .run_control import ProcessStopped, check_stopped, pausable_callback
from .run_estimate import combine_progress_local_step, count_inference_passes_from_models
from .debug_log import debug, debug_elapsed, next_seq, preview_text, set_correlation_seq, verbose
from .error_context import snapshot_worker_file
from .model_display import display_name_for_model
from .separate_import import import_separate_engines
from .inference_cleanup import (
    clear_source_mapper,
    release_inference_memory as _release_inference_resources,
    release_separator,
)


def collect_run_model_paths(models: Sequence[ModelData]) -> set:
    """Collect on-disk model paths for every model participating in this run."""
    found: set = set()

    def add(model: Optional[ModelData]) -> None:
        if model is None:
            return
        path = getattr(model, "model_path", None)
        if path:
            found.add(str(path))
        secondary = getattr(model, "secondary_model", None)
        if secondary is not None:
            add(secondary)
        pre_proc = getattr(model, "pre_proc_model", None)
        if pre_proc is not None:
            add(pre_proc)
        for stem_model in getattr(model, "secondary_model_4_stem", None) or []:
            add(stem_model)

    for model in models:
        add(model)
    return found


def _decoded_mix_for_process(audio_file):
    """Decode once per track so ensemble / secondary models reuse the same mix."""
    from engines.mix import prepare_mix

    return prepare_mix(audio_file)


_MODEL_KEY_BY_METHOD = {
    VR_ARCH_PM: "vr_model",
    MDX_ARCH_TYPE: "mdx_net_model",
    DEMUCS_ARCH_TYPE: "demucs_model",
}


def _model_output_label(model: ModelData) -> str:
    """Return the user-facing model label for export paths and test mode."""
    label = display_name_for_model(model.process_method, model.model_name, model.repo)
    return label or model.model_basename or ""


def _progress_detail(
    *,
    file_num: int,
    file_total: int,
    model,
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
        label = _model_output_label(model)
        if model_count > 1:
            parts.append(f"Model {model_num}/{model_count}" + (f" · {label}" if label else ""))
        elif label:
            parts.append(label)
    return " · ".join(parts) if parts else None


def _long_file_chunk_settings(settings: SettingsModel) -> tuple:
    """Return ``(chunk_seconds, overlap_seconds)``; chunk ``<= 0`` means off."""
    try:
        chunk_seconds = float(settings.get("long_file_chunk_seconds") or 0.0)
    except (TypeError, ValueError):
        chunk_seconds = 0.0
    try:
        overlap_seconds = float(settings.get("long_file_chunk_overlap_seconds") or 0.0)
    except (TypeError, ValueError):
        overlap_seconds = 0.0
    return chunk_seconds, overlap_seconds


def _write_captured_stems(
    stem_arrays: dict,
    stem_paths: dict,
    *,
    is_normalization: bool,
    amplification_threshold: float,
    wav_type_set,
    save_format_name,
    mp3_bit_set,
    flac_bit_set,
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
class JobCallbacks:
    """Callbacks invoked from the worker thread.

    ``on_progress`` receives a float in ``[0.0, 1.0]`` plus optional keyword
    metadata (``local_step``, ``pass_index``, ``pass_total``, ``detail``,
    ``combine_index``, ``combine_total``). ``on_console`` receives text chunks;
    ``on_complete`` fires once on success; ``on_error`` receives the raised
    exception. The GTK layer marshals each of these onto the main loop.
    """

    on_progress: Optional[Callable[..., None]] = None
    on_console: Optional[Callable[[str], None]] = None
    on_complete: Optional[Callable[[], None]] = None
    on_stopped: Optional[Callable[[], None]] = None
    on_error: Optional[Callable[[BaseException], None]] = None

    def progress(
        self,
        fraction: float,
        *,
        local_step: Optional[float] = None,
        pass_index: Optional[int] = None,
        pass_total: Optional[int] = None,
        detail: Optional[str] = None,
        combine_index: Optional[int] = None,
        combine_total: Optional[int] = None,
    ) -> None:
        if not self.on_progress:
            return
        clamped = max(0.0, min(1.0, fraction))
        self.on_progress(
            clamped,
            local_step=local_step,
            pass_index=pass_index,
            pass_total=pass_total,
            detail=detail,
            combine_index=combine_index,
            combine_total=combine_total,
        )

    def console(self, text: str) -> None:
        seq = next_seq()
        set_correlation_seq(seq)
        if verbose():
            debug("worker", f"console emit {preview_text(text)!r}", seq=seq)
        if self.on_console:
            self.on_console(text)

    def complete(self) -> None:
        debug("worker", "complete")
        if self.on_complete:
            self.on_complete()

    def stopped(self) -> None:
        debug("worker", "stopped")
        if self.on_stopped:
            self.on_stopped()

    def error(self, exc: BaseException) -> None:
        debug("worker", f"error {type(exc).__name__}: {exc}")
        if self.on_error:
            self.on_error(exc)


class JobRunner:
    """Runs separation on a ``KThread`` worker and reports through callbacks."""

    def __init__(self, settings: SettingsModel, repo: Optional[ModelRepository] = None):
        self.settings = settings
        self.repo = repo or ModelRepository()
        self._thread = None
        self._is_stopped = False
        self._is_paused = False
        self.iteration = 0
        self.true_model_count = 0
        # Per-run secondary-source caches consumed by the engines.
        self._vr_cache_source_mapper: dict = {}
        self._mdx_cache_source_mapper: dict = {}
        self._demucs_cache_source_mapper: dict = {}
        self.all_models: List[str] = []
        self._active_separator = None
        self._run_protect_identities: set = set()
        self._last_backend_name: Optional[str] = None

    # -- Public control ---------------------------------------------------------

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, input_paths: Sequence[str], callbacks: JobCallbacks) -> None:
        """Launch the worker thread. No-op if a run is already in flight.

        Routes to the ensemble worker when ``chosen_process_method`` is
        ``ENSEMBLE_MODE`` (mirroring ``process_start``'s branch), otherwise the
        single-method worker.
        """
        if self.is_running():
            return
        if self.settings.get("chosen_process_method") == ENSEMBLE_MODE:
            self.start_ensemble(input_paths, callbacks)
            return
        from kthread import KThread

        self._is_stopped = False
        self._is_paused = False
        paths = list(input_paths)
        self._thread = KThread(
            target=self._run,
            args=(paths, callbacks),
        )
        debug("worker", f"KThread start files={len(paths)}")
        self._thread.start()

    def start_ensemble(self, input_paths: Sequence[str], callbacks: JobCallbacks) -> None:
        """Launch the ensemble worker thread explicitly. No-op if already running."""
        if self.is_running():
            return
        from kthread import KThread

        self._is_stopped = False
        self._is_paused = False
        paths = list(input_paths)
        self._thread = KThread(
            target=self._run_ensemble,
            args=(paths, callbacks),
        )
        debug("worker", f"KThread ensemble start files={len(paths)}")
        self._thread.start()

    def _prepare_paths_for_run(
        self, input_paths: List[str], callbacks: JobCallbacks
    ) -> List[str]:
        """Build sample clips on the worker thread and report any fallbacks."""
        if self.settings.get("model_sample_mode"):
            callbacks.console("Preparing sample clips...\n")
            callbacks.progress(0.0, detail="Preparing sample clips")

        def on_fallback(path: str, exc: Exception) -> None:
            name = os.path.basename(path)
            message = (
                f'Sample clip failed for "{name}"; processing the full file '
                f"({type(exc).__name__}: {exc})"
            )
            callbacks.console(f"{message}\n")
            try:
                # Lazy import: keep core free of a hard ui dependency at load time.
                from ui import errorlog as errorlog_mod

                errorlog_mod.log_error("Sample mode", exc, context=message)
            except Exception:  # noqa: BLE001 - logging must not abort the run
                debug("model", f"sample clip fallback log failed: {exc}")

        prep_started = time.perf_counter()
        prepared = prepare_input_paths(
            self.settings, input_paths, on_fallback=on_fallback
        )
        debug_elapsed("worker", "prepare_input_paths", prep_started, files=len(prepared))
        return prepared

    def pause(self) -> None:
        """Pause the worker between files/models (e.g. while a confirm dialog is open)."""
        debug("worker", "pause requested")
        self._is_paused = True

    def unpause(self) -> None:
        debug("worker", "unpause requested")
        self._is_paused = False

    def stop(self, *, force: bool = False) -> None:
        """Request a cooperative stop; only kill the worker thread when ``force``."""
        debug("worker", f"stop requested force={force} alive={self.is_running()}")
        self._is_paused = False
        self._is_stopped = True
        if force and self.is_running():
            thread = self._thread
            if thread is not None:
                try:
                    thread.terminate()
                    debug("worker", "stop force thread.terminate()")
                    thread.join(timeout=0.25)
                except Exception:
                    pass

    def release_inference_memory(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
        clear_weight_cache: bool = False,
        park_weights: bool = False,
    ) -> None:
        """Drop cached stems and return GPU memory after a run or halt."""
        _release_inference_resources(
            self,
            wait_for_stop=wait_for_stop,
            force_if_alive=force_if_alive,
            clear_weight_cache=clear_weight_cache,
            park_weights=park_weights,
        )

    # -- Source cache helpers (ported from MainWindow) --------------------------

    def _cached_sources_clear(self) -> None:
        clear_source_mapper(self._vr_cache_source_mapper)
        clear_source_mapper(self._mdx_cache_source_mapper)
        clear_source_mapper(self._demucs_cache_source_mapper)
        self._vr_cache_source_mapper = {}
        self._mdx_cache_source_mapper = {}
        self._demucs_cache_source_mapper = {}

    def _cached_source_callback(self, process_method, model_name=None):
        mapper = self._mapper_for(process_method)
        if model_name and model_name in mapper:
            return model_name, mapper[model_name]
        return None, None

    def _cached_model_source_holder(self, process_method, sources, model_name=None):
        mapper = self._mapper_for(process_method)
        mapper[model_name] = sources

    def _mapper_for(self, process_method) -> dict:
        if process_method == VR_ARCH_TYPE:
            return self._vr_cache_source_mapper
        if process_method == MDX_ARCH_TYPE:
            return self._mdx_cache_source_mapper
        return self._demucs_cache_source_mapper

    def _process_iteration(self) -> None:
        self.iteration += 1

    # -- Worker -----------------------------------------------------------------

    def resolve_models(self) -> List[ModelData]:
        """Build the ``ModelData`` list for the currently chosen method."""
        method = self.settings.get("chosen_process_method")
        if method not in _MODEL_KEY_BY_METHOD:
            raise NotImplementedError(f"process method '{method}' is implemented in a later phase")
        model_name = self.settings.get(_MODEL_KEY_BY_METHOD[method])
        return assemble_model_data(self.settings, self.repo, model_name, method)

    def _count_true_models(self, models: List[ModelData]) -> int:
        """Progress denominator: shared with the Save stems workload estimate."""
        return count_inference_passes_from_models(models)

    def _build_all_models(self, models: List[ModelData]) -> None:
        """Port of ``cached_source_model_list_check``'s ``all_models`` list.

        The engines use ``list_all_models`` to decide whether a referenced
        primary/secondary model participates in the current run.
        """
        primary = [m.model_basename for m in models if m.model_basename]
        secondary = []
        for m in models:
            if not m.is_secondary_model_activated or m.secondary_model is None:
                continue
            name = m.secondary_model.model_basename
            if name:
                secondary.append(name)
        pre_proc: List[str] = []
        for m in models:
            proc = getattr(m, "pre_proc_model", None)
            if proc is not None and proc.model_basename:
                pre_proc.append(proc.model_basename)
        demucs_4_stem: List[str] = []
        for m in models:
            if m.process_method == DEMUCS_ARCH_TYPE and getattr(m, "is_demucs_4_stem_secondaries", False):
                demucs_4_stem.extend(n for n in m.secondary_model_4_stem_model_names_list if n)
        self.all_models = [n for n in primary + secondary + pre_proc + demucs_4_stem if n]

    def _set_run_protect_identities(self, models: List[ModelData]) -> None:
        from engines.model_weight_cache import model_file_identity

        identities = set()
        for path in collect_run_model_paths(models):
            ident = model_file_identity(path)
            if ident is not None:
                identities.add(ident)
        self._run_protect_identities = identities

    def _ensure_vram_for_job(
        self,
        callbacks: JobCallbacks,
        device: Any = None,
        *,
        prefer_gpu_identity: Any = None,
    ) -> None:
        """Park or clear cached weights when free VRAM is too low for this job."""
        from engines.model_weight_cache import ensure_weight_cache_vram_headroom

        target = device
        if target is None:
            target = self.settings.get("device_set")
        action = ensure_weight_cache_vram_headroom(
            target,
            protect_identities=self._run_protect_identities or None,
            prefer_gpu_identity=prefer_gpu_identity,
        )
        if action in {"parked_other", "cleared_other"}:
            callbacks.console(
                "Low GPU memory — freed unused cached models for this run\n"
            )
        elif action in {"parked_all", "cleared_all"}:
            callbacks.console(
                "Low GPU memory — freed all cached models for this run\n"
            )

    def _run_seperator(self, seperator):
        """Run one separator and return captured stem arrays (for ensemble RAM path)."""
        self._active_separator = seperator
        self._last_backend_name = getattr(seperator, "_backend_name", None)
        self._last_captured_stem_paths = {}
        stems: dict = {}
        try:
            from engines.model_weight_cache import (
                ensure_weight_cache_vram_headroom,
                model_file_identity,
            )

            prefer = model_file_identity(getattr(seperator, "model_path", "") or "")
            ensure_weight_cache_vram_headroom(
                getattr(seperator, "device", None),
                protect_identities=self._run_protect_identities or None,
                prefer_gpu_identity=prefer,
            )
            seperator.seperate()
            stems = _capture_separator_stem_arrays(seperator)
            self._last_captured_stem_paths = _capture_separator_stem_paths(seperator)
            return stems
        finally:
            debug("cleanup", f"_run_seperator finally engine={type(seperator).__name__}")
            release_separator(seperator)
            if self._active_separator is seperator:
                self._active_separator = None

    def _run(self, input_paths: List[str], callbacks: JobCallbacks) -> None:
        debug("worker", "_run entered")
        import_started = time.perf_counter()
        (
            SeperateDemucs,
            SeperateMDX,
            SeperateMDXC,
            SeperateVR,
            clear_gpu_cache,
        ) = import_separate_engines()
        debug_elapsed("worker", "separate engines ready", import_started)

        stime = time.perf_counter()
        time_elapsed = lambda: f'Time Elapsed: {time.strftime("%H:%M:%S", time.gmtime(int(time.perf_counter() - stime)))}'

        try:
            input_paths = self._prepare_paths_for_run(input_paths, callbacks)
            export_path = self.settings.get("export_path")
            if not export_path:
                raise ValueError("export_path is required")
            resolve_started = time.perf_counter()
            models = self.resolve_models()
            debug_elapsed("worker", "resolve_models", resolve_started, count=len(models))
            self.iteration = 0
            self._build_all_models(models)
            self._set_run_protect_identities(models)
            self._ensure_vram_for_job(callbacks)
            self.true_model_count = self._count_true_models(models)

            from core.audio_chunking import (
                concat_stems,
                overlaps_for_chunks,
                slice_mix,
            )

            chunk_seconds, overlap_seconds = _long_file_chunk_settings(self.settings)
            total_files = len(input_paths)
            file_plans = []
            total_chunk_units = 0
            for audio_file in input_paths:
                if not os.path.isfile(audio_file):
                    file_plans.append(None)
                    continue
                decoded_mix = _decoded_mix_for_process(audio_file)
                chunks = slice_mix(
                    decoded_mix,
                    chunk_seconds=chunk_seconds,
                    overlap_seconds=overlap_seconds,
                )
                file_plans.append((audio_file, decoded_mix, chunks))
                total_chunk_units += len(chunks)
            if total_chunk_units <= 0:
                total_chunk_units = max(1, total_files)

            last_progress_fraction = 0.0
            progress_ctx = {
                "file_num": 1,
                "model": None,
                "model_num": 0,
                "model_count": len(models),
                "chunk_num": 0,
                "chunk_total": 0,
            }

            def make_progress():
                def set_progress_bar(step, inference_iterations=0):
                    nonlocal last_progress_fraction
                    total_count = max(1, self.true_model_count * total_chunk_units)
                    base = 1.0 / total_count
                    local_step = step + inference_iterations
                    fraction = base * self.iteration - base + base * local_step
                    last_progress_fraction = fraction
                    callbacks.progress(
                        fraction,
                        local_step=local_step,
                        pass_index=max(1, self.iteration),
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

            try:
                amp_threshold = float(self.settings.get("amplification_threshold") or 0.0)
            except (TypeError, ValueError):
                amp_threshold = 0.0

            for file_num, plan in enumerate(file_plans, start=1):
                check_stopped(self)
                self._cached_sources_clear()
                base_text = f"File {file_num}/{total_files} "
                progress_ctx["file_num"] = file_num

                if plan is None:
                    audio_file = input_paths[file_num - 1]
                    callbacks.console(f'\n{base_text}"{os.path.basename(audio_file)}" was not found.\n')
                    self.iteration += self.true_model_count
                    continue

                audio_file, decoded_mix, chunks = plan
                n_chunks = len(chunks)
                progress_ctx["chunk_total"] = n_chunks
                chunked = n_chunks > 1
                if chunked:
                    callbacks.console(
                        f"{base_text}Long-file chunking: {n_chunks} chunks "
                        f"({chunk_seconds:g}s, overlap {overlap_seconds:g}s)\n"
                    )
                ov_samples = overlaps_for_chunks(chunks) if chunked else []

                set_progress_bar = pausable_callback(self, make_progress())

                for model_num, current_model in enumerate(models, start=1):
                    check_stopped(self)
                    progress_ctx["model"] = current_model
                    progress_ctx["model_num"] = model_num
                    write_to_console = pausable_callback(
                        self,
                        lambda text, base_text=base_text: callbacks.console(base_text + text),
                    )

                    track_title = track_basename_from_path(audio_file)
                    model_label = _model_output_label(current_model)
                    audio_file_base = format_track_base(
                        track=track_title,
                        model=model_label if self.settings.get("is_add_model_name") else None,
                        file_index=file_num,
                        file_total=total_files,
                        timestamp=testing_timestamp_prefix(self.settings),
                    )

                    model_export_path = export_path
                    if self.settings.get("is_create_model_folder"):
                        if model_label:
                            model_export_path = os.path.join(
                                export_path,
                                sanitize_filename_component(model_label),
                                track_title,
                            )
                            os.makedirs(model_export_path, exist_ok=True)

                    stem_parts: dict = {}
                    stem_paths: dict = {}
                    for chunk_num, (_start, _end, mix_slice) in enumerate(chunks, start=1):
                        check_stopped(self)
                        snapshot_worker_file(audio_file, current_model)
                        self._process_iteration()
                        progress_ctx["chunk_num"] = chunk_num
                        if chunked:
                            # Avoid cache hits from a prior chunk for the same model.
                            self._cached_sources_clear()

                        process_data = {
                            "model_data": current_model,
                            "export_path": model_export_path,
                            "audio_file_base": audio_file_base,
                            "audio_file": mix_slice if chunked else decoded_mix,
                            "audio_file_path": audio_file,
                            "set_progress_bar": set_progress_bar,
                            "write_to_console": write_to_console,
                            "process_iteration": pausable_callback(self, self._process_iteration),
                            "check_run_control": pausable_callback(self, lambda: check_stopped(self)),
                            "cached_source_callback": self._cached_source_callback,
                            "cached_model_source_holder": self._cached_model_source_holder,
                            "list_all_models": self.all_models,
                            "is_ensemble_master": False,
                            "is_4_stem_ensemble": False,
                            "capture_stems_only": chunked,
                        }

                        if current_model.process_method == VR_ARCH_TYPE:
                            seperator = SeperateVR(current_model, process_data)
                        elif current_model.process_method == MDX_ARCH_TYPE:
                            seperator = SeperateMDXC(current_model, process_data) if current_model.is_mdx_c else SeperateMDX(current_model, process_data)
                        elif current_model.process_method == DEMUCS_ARCH_TYPE:
                            seperator = SeperateDemucs(current_model, process_data)
                        else:
                            raise NotImplementedError(f"engine for '{current_model.process_method}' not available")

                        engine = type(seperator).__name__
                        debug(
                            "worker",
                            f"separate start engine={engine} model={current_model.model_basename!r} "
                            f"chunk={chunk_num}/{n_chunks}",
                        )
                        member_stems = self._run_seperator(seperator) or {}
                        if chunked:
                            paths = getattr(self, "_last_captured_stem_paths", None) or {}
                            for stem_tag, arr in member_stems.items():
                                stem_parts.setdefault(stem_tag, []).append(arr)
                                if stem_tag in paths:
                                    stem_paths[stem_tag] = paths[stem_tag]
                        debug("worker", f"separate done engine={engine}")

                    if chunked and stem_parts:
                        final_stems = {
                            stem: concat_stems(parts, overlap_samples=ov_samples)
                            for stem, parts in stem_parts.items()
                        }
                        _write_captured_stems(
                            final_stems,
                            stem_paths,
                            is_normalization=bool(self.settings.get("is_normalization")),
                            amplification_threshold=amp_threshold,
                            wav_type_set=resolve_wav_type_set(self.settings),
                            save_format_name=self.settings.get("save_format"),
                            mp3_bit_set=self.settings.get("mp3_bit_set"),
                            flac_bit_set=self.settings.get("flac_bit_set", "16-bit"),
                        )

                clear_gpu_cache(getattr(self, "_last_backend_name", None))

            callbacks.progress(1.0)
            callbacks.console(f"\nProcess complete\n{time_elapsed()}\n")
            callbacks.complete()
        except ProcessStopped:
            debug("worker", "_run ProcessStopped")
            callbacks.console(PROCESS_STOPPED_BY_USER)
            callbacks.stopped()
            _release_inference_resources(self)
        except Exception as exc:  # noqa: BLE001 - surfaced through the callback
            if self._is_stopped:
                debug("worker", "_run stopped during error path")
                callbacks.console(PROCESS_STOPPED_BY_USER)
                callbacks.stopped()
                _release_inference_resources(self)
                return
            debug("worker", f"_run failed {type(exc).__name__}: {exc}")
            callbacks.console(f"\nProcess failed\n{time_elapsed()}\n")
            callbacks.error(exc)
            # Park GPU-resident weights so a retry is not blocked by VRAM from
            # the failed attempt (common after CUDA OOM).
            _release_inference_resources(self, park_weights=True)
        else:
            _release_inference_resources(self)

    def _run_ensemble(self, input_paths: List[str], callbacks: JobCallbacks) -> None:
        """Run every selected ensemble member then combine their outputs.

        Tk-free port of ``process_start``'s ``ENSEMBLE_MODE`` branch: each member
        model is run with ``is_ensemble_master`` so the engines write per-member
        stems into the ensemble temp folder, then :class:`Ensembler` combines
        those stems per the chosen algorithm into the final outputs.
        """
        import shutil

        debug("worker", "_run_ensemble entered")
        import_started = time.perf_counter()
        (
            SeperateDemucs,
            SeperateMDX,
            SeperateMDXC,
            SeperateVR,
            clear_gpu_cache,
        ) = import_separate_engines()
        debug_elapsed("worker", "separate engines ready", import_started)

        stime = time.perf_counter()
        time_elapsed = lambda: f'Time Elapsed: {time.strftime("%H:%M:%S", time.gmtime(int(time.perf_counter() - stime)))}'

        try:
            input_paths = self._prepare_paths_for_run(input_paths, callbacks)
            models = assemble_model_data(self.settings, self.repo, arch_type=ENSEMBLE_MODE)
            if len(models) <= 1:
                raise RuntimeError("Select at least two models to run an ensemble")

            ensemble = Ensembler(self.settings)
            export_path = ensemble.ensemble_folder_name
            ensemble_main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
            is_4_stem = ensemble_main_stem in (FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE)

            self.iteration = 0
            self._build_all_models(models)
            self._set_run_protect_identities(models)
            self._ensure_vram_for_job(callbacks)
            self.true_model_count = self._count_true_models(models)

            from core.audio_chunking import (
                concat_stems,
                overlaps_for_chunks,
                slice_mix,
            )

            chunk_seconds, overlap_seconds = _long_file_chunk_settings(self.settings)
            total_files = len(input_paths)
            file_plans = []
            total_chunk_units = 0
            for audio_file in input_paths:
                if not os.path.isfile(audio_file):
                    file_plans.append(None)
                    continue
                decoded_mix = _decoded_mix_for_process(audio_file)
                chunks = slice_mix(
                    decoded_mix,
                    chunk_seconds=chunk_seconds,
                    overlap_seconds=overlap_seconds,
                )
                file_plans.append((audio_file, decoded_mix, chunks))
                total_chunk_units += len(chunks)
            if total_chunk_units <= 0:
                total_chunk_units = max(1, total_files)

            last_progress_fraction = 0.0
            progress_ctx = {
                "file_num": 1,
                "model": None,
                "model_num": 0,
                "model_count": len(models),
                "chunk_num": 0,
                "chunk_total": 0,
            }

            def make_progress():
                def set_progress_bar(step, inference_iterations=0):
                    nonlocal last_progress_fraction
                    total_count = max(1, self.true_model_count * total_chunk_units)
                    base = 1.0 / total_count
                    local_step = step + inference_iterations
                    fraction = base * self.iteration - base + base * local_step
                    last_progress_fraction = fraction
                    callbacks.progress(
                        fraction,
                        local_step=local_step,
                        pass_index=max(1, self.iteration),
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

            for file_num, plan in enumerate(file_plans, start=1):
                check_stopped(self)
                self._cached_sources_clear()
                base_text = f"File {file_num}/{total_files} "
                progress_ctx["file_num"] = file_num

                if plan is None:
                    audio_file = input_paths[file_num - 1]
                    callbacks.console(f'\n{base_text}"{os.path.basename(audio_file)}" was not found.\n')
                    self.iteration += self.true_model_count
                    continue

                audio_file, decoded_mix, chunks = plan
                n_chunks = len(chunks)
                progress_ctx["chunk_total"] = n_chunks
                chunked = n_chunks > 1
                if chunked:
                    callbacks.console(
                        f"{base_text}Long-file chunking: {n_chunks} chunks "
                        f"({chunk_seconds:g}s, overlap {overlap_seconds:g}s)\n"
                    )
                ov_samples = overlaps_for_chunks(chunks) if chunked else []

                set_progress_bar = pausable_callback(self, make_progress())
                current_model = None
                # stem_tag -> list of member waveforms for in-memory combine
                ensemble_stem_arrays: dict = {}
                track_title = track_basename_from_path(audio_file)
                stamp = testing_timestamp_prefix(self.settings)
                ensemble_final_base = format_track_base(
                    track=track_title,
                    model=None,
                    file_index=file_num,
                    file_total=total_files,
                    timestamp=stamp,
                    ensemble=ensemble.append_ensemble_label,
                )

                for current_model_num, current_model in enumerate(models, start=1):
                    check_stopped(self)
                    progress_ctx["model"] = current_model
                    progress_ctx["model_num"] = current_model_num
                    callbacks.console(
                        f"Ensemble Mode - {_model_output_label(current_model)} - "
                        f"Model {current_model_num}/{len(models)}\n"
                    )
                    write_to_console = pausable_callback(
                        self,
                        lambda text, base_text=base_text: callbacks.console(base_text + text),
                    )

                    model_label = _model_output_label(current_model)
                    audio_file_base = format_track_base(
                        track=track_title,
                        model=model_label,
                        file_index=file_num,
                        file_total=total_files,
                        timestamp=stamp,
                    )

                    member_stem_parts: dict = {}
                    for chunk_num, (_start, _end, mix_slice) in enumerate(chunks, start=1):
                        check_stopped(self)
                        snapshot_worker_file(audio_file, current_model)
                        self._process_iteration()
                        progress_ctx["chunk_num"] = chunk_num
                        if chunked:
                            self._cached_sources_clear()

                        process_data = {
                            "model_data": current_model,
                            "export_path": export_path,
                            "audio_file_base": audio_file_base,
                            "audio_file": mix_slice if chunked else decoded_mix,
                            "audio_file_path": audio_file,
                            "set_progress_bar": set_progress_bar,
                            "write_to_console": write_to_console,
                            "process_iteration": pausable_callback(self, self._process_iteration),
                            "check_run_control": pausable_callback(self, lambda: check_stopped(self)),
                            "cached_source_callback": self._cached_source_callback,
                            "cached_model_source_holder": self._cached_model_source_holder,
                            "list_all_models": self.all_models,
                            "is_ensemble_master": True,
                            "is_4_stem_ensemble": is_4_stem,
                            "is_save_all_outputs_ensemble": bool(
                                self.settings.get("is_save_all_outputs_ensemble")
                            ),
                            "capture_stems_only": chunked,
                        }

                        if current_model.process_method == VR_ARCH_TYPE:
                            seperator = SeperateVR(current_model, process_data)
                        elif current_model.process_method == MDX_ARCH_TYPE:
                            seperator = SeperateMDXC(current_model, process_data) if current_model.is_mdx_c else SeperateMDX(current_model, process_data)
                        elif current_model.process_method == DEMUCS_ARCH_TYPE:
                            seperator = SeperateDemucs(current_model, process_data)
                        else:
                            raise NotImplementedError(f"engine for '{current_model.process_method}' not available")

                        engine = type(seperator).__name__
                        debug(
                            "worker",
                            f"ensemble separate start engine={engine} model={current_model.model_basename!r} "
                            f"chunk={chunk_num}/{n_chunks}",
                        )
                        member_stems = self._run_seperator(seperator) or {}
                        if chunked:
                            for stem_tag, arr in member_stems.items():
                                member_stem_parts.setdefault(stem_tag, []).append(arr)
                        else:
                            for stem_tag, arr in member_stems.items():
                                ensemble_stem_arrays.setdefault(stem_tag, []).append(arr)
                        debug("worker", f"ensemble separate done engine={engine}")

                    if chunked:
                        for stem_tag, parts in member_stem_parts.items():
                            ensemble_stem_arrays.setdefault(stem_tag, []).append(
                                concat_stems(parts, overlap_samples=ov_samples)
                            )
                    callbacks.console("\n")

                # Combine each member's stems into the final ensemble outputs.
                callbacks.console(base_text + "Ensembling outputs...\n")
                combine_started = time.perf_counter()

                combine_steps: List[tuple] = []
                if is_4_stem:
                    stem_names = [
                        name
                        for name, arrs in ensemble_stem_arrays.items()
                        if len(arrs) > 1
                    ]
                    if not stem_names:
                        stem_names = _extract_stems(ensemble_final_base, export_path)
                    combine_steps = [
                        (output_stem, {"is_4_stem": True}) for output_stem in stem_names
                    ]
                else:
                    if not self.settings.get("is_secondary_stem_only"):
                        combine_steps.append((PRIMARY_STEM, {}))
                    if not self.settings.get("is_primary_stem_only"):
                        combine_steps.append((SECONDARY_STEM, {}))
                        combine_steps.append((SECONDARY_STEM, {"is_inst_mix": True}))

                combine_total = max(1, len(combine_steps))
                combine_start = last_progress_fraction
                combine_end = file_num / max(1, total_files)
                for combine_idx, (stem_name, kwargs) in enumerate(combine_steps):
                    ensemble.ensemble_outputs(
                        ensemble_final_base,
                        export_path,
                        stem_name,
                        stem_arrays=ensemble_stem_arrays,
                        **kwargs,
                    )
                    span = max(combine_end - combine_start, 0.0)
                    fraction = combine_start + span * ((combine_idx + 1) / combine_total)
                    local_step = combine_progress_local_step(combine_idx, combine_total)
                    last_progress_fraction = fraction
                    total_count = max(1, self.true_model_count * total_files)
                    callbacks.progress(
                        fraction,
                        local_step=local_step,
                        pass_index=total_count,
                        pass_total=total_count,
                        combine_index=combine_idx + 1,
                        combine_total=combine_total,
                        detail=f"Combining {combine_idx + 1}/{combine_total}",
                    )

                debug_elapsed("worker", "ensemble combine", combine_started)
                callbacks.console("Done\n")
                clear_gpu_cache(getattr(self, "_last_backend_name", None))

            # Drop the temp folder if it was a scratch dir and is now empty.
            try:
                if os.path.isdir(export_path) and len(os.listdir(export_path)) == 0:
                    shutil.rmtree(export_path)
            except OSError:
                pass

            callbacks.progress(1.0)
            callbacks.console(f"\nProcess complete\n{time_elapsed()}\n")
            callbacks.complete()
        except ProcessStopped:
            debug("worker", "_run_ensemble ProcessStopped")
            callbacks.console(PROCESS_STOPPED_BY_USER)
            callbacks.stopped()
            _release_inference_resources(self)
        except Exception as exc:  # noqa: BLE001 - surfaced through the callback
            if self._is_stopped:
                debug("worker", "_run_ensemble stopped during error path")
                callbacks.console(PROCESS_STOPPED_BY_USER)
                callbacks.stopped()
                _release_inference_resources(self)
                return
            debug("worker", f"_run_ensemble failed {type(exc).__name__}: {exc}")
            callbacks.console(f"\nProcess failed\n{time_elapsed()}\n")
            callbacks.error(exc)
            _release_inference_resources(self, park_weights=True)
        else:
            _release_inference_resources(self)


def _capture_separator_stem_arrays(seperator) -> dict:
    """Copy stem waveforms buffered by an ensemble member before release."""
    buffers = getattr(seperator, "_ensemble_stem_buffers", None) or {}
    if not buffers:
        return {}
    import numpy as np

    return {name: np.array(arr, copy=True) for name, arr in buffers.items()}


def _capture_separator_stem_paths(seperator) -> dict:
    """Copy deferred stem export paths buffered alongside stem arrays."""
    paths = getattr(seperator, "_ensemble_stem_paths", None) or {}
    return dict(paths)


def _extract_stems(audio_file_base: str, export_path: str) -> List[str]:
    """Tk-free copy of ``UVR.extract_stems``.

    Finds the stem tags (the ``(...)`` suffix) shared by more than one of the
    per-member output files, i.e. the stems that actually have something to
    ensemble for a 4-/multi-stem run.
    """
    if not os.path.isdir(export_path):
        return []
    filenames = [name for name in os.listdir(export_path) if name.startswith(audio_file_base)]
    pattern = r"\(([^()]+)\)(?=[^()]*\.wav)"
    stem_list = []
    for filename in filenames:
        match = re.search(pattern, filename)
        if match:
            stem_list.append(match.group(1))
    counter = Counter(stem_list)
    return list({item for item in stem_list if counter[item] > 1})


class Ensembler:
    """Tk-free port of ``UVR.py``'s ``Ensembler`` (output combination only).

    Reads its configuration from the :class:`SettingsModel` rather than the Tk
    root window, and lazily imports the heavy ``spec_utils`` / ``separate``
    helpers only when actually combining audio, keeping construction torch-free.
    """

    def __init__(self, settings: SettingsModel, is_manual_ensemble: bool = False):
        self.settings = settings
        self.is_save_all_outputs_ensemble = settings.get("is_save_all_outputs_ensemble")

        chosen = settings.get("chosen_ensemble", CHOOSE_ENSEMBLE_OPTION)
        if chosen and chosen != CHOOSE_ENSEMBLE_OPTION:
            chosen_ensemble_name = sanitize_filename_component(chosen) or "Ensembled"
        else:
            chosen_ensemble_name = "Ensembled"
        from core.ensemble_algorithms import parse_ensemble_type

        ensemble_type_value = settings.get("ensemble_type", MAX_MIN)
        primary_algorithm, secondary_algorithm = parse_ensemble_type(ensemble_type_value)
        ensemble_main_stem_pair = settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR).partition("/")
        time_stamp = round(time.time())

        self.main_export_path = settings.get("export_path")
        self.append_ensemble_label = (
            chosen_ensemble_name if settings.get("is_append_ensemble_name") else None
        )
        ensemble_folder_root = self.main_export_path if self.is_save_all_outputs_ensemble else paths.ENSEMBLE_TEMP_PATH
        folder_label = sanitize_filename_component(chosen_ensemble_name.replace(" ", "_")) or "Ensembled"
        self.ensemble_folder_name = os.path.join(ensemble_folder_root, f"{folder_label}_Outputs_{time_stamp}")
        # Dual-stem: Primary/Secondary pair. 4-stem uses the full token in ensemble_outputs.
        self.primary_algorithm = primary_algorithm
        self.secondary_algorithm = secondary_algorithm
        self.ensemble_primary_stem = ensemble_main_stem_pair[0]
        self.ensemble_secondary_stem = ensemble_main_stem_pair[2]
        self.is_normalization = settings.get("is_normalization")
        try:
            self.amplification_threshold = float(settings.get("amplification_threshold") or 0.0)
        except (TypeError, ValueError):
            self.amplification_threshold = 0.0
        self.is_wav_ensemble = settings.get("is_wav_ensemble")
        self.wav_type_set = resolve_wav_type_set(settings)
        self.mp3_bit_set = settings.get("mp3_bit_set")
        self.flac_bit_set = settings.get("flac_bit_set", "16-bit")
        self.save_format = settings.get("save_format")
        if not is_manual_ensemble:
            os.makedirs(self.ensemble_folder_name, exist_ok=True)

    def ensemble_outputs(
        self,
        audio_file_base,
        export_path,
        stem,
        is_4_stem=False,
        is_inst_mix=False,
        stem_arrays=None,
    ):
        """Combine the per-member outputs for ``stem`` with the chosen algorithm.

        Prefer in-memory member waveforms from ``stem_arrays`` when present
        (ensemble scratch path); otherwise fall back to disk ``.wav`` members.
        """
        debug("worker", f"ensemble_outputs stem={stem!r} is_4_stem={is_4_stem} is_inst_mix={is_inst_mix}")
        from ml import spec_utils
        from engines.separate import save_format as _save_format

        if is_4_stem:
            # Single-token algorithm (no slash); never use an empty secondary partition.
            raw_type = self.settings.get("ensemble_type", MAX_MIN)
            algorithm = raw_type.partition("/")[0].strip() or MAX_SPEC
            stem_tag = stem
        elif is_inst_mix:
            algorithm = self.secondary_algorithm
            stem_tag = f"{self.ensemble_secondary_stem} {INST_STEM}"
        else:
            algorithm = self.primary_algorithm if stem == PRIMARY_STEM else self.secondary_algorithm
            stem_tag = self.ensemble_primary_stem if stem == PRIMARY_STEM else self.ensemble_secondary_stem

        array_inputs = list((stem_arrays or {}).get(stem_tag, []))
        stem_suffix = f" ({sanitize_filename_component(stem_tag)}).wav"
        # Member files are ``{final_base} {model} ({stem}).wav``; match by track prefix.
        match_prefix = audio_file_base
        if self.append_ensemble_label and match_prefix.endswith(f" {self.append_ensemble_label}"):
            match_prefix = match_prefix[: -(len(self.append_ensemble_label) + 1)]
        stem_outputs = self.get_files_to_ensemble(
            folder=export_path, prefix=match_prefix, suffix=stem_suffix
        )
        audio_file_output = format_stem_basename(audio_file_base, stem_tag)
        stem_save_path = os.path.join(f"{self.main_export_path}", f"{audio_file_output}.wav")

        if len(array_inputs) > 1:
            spec_utils.ensemble_inputs(
                array_inputs,
                algorithm,
                self.is_normalization,
                self.wav_type_set,
                stem_save_path,
                is_wave=self.is_wav_ensemble,
                is_array=True,
                min_peak=self.amplification_threshold,
            )
            _save_format(stem_save_path, self.save_format, self.mp3_bit_set, self.flac_bit_set)
        elif len(stem_outputs) > 1:
            spec_utils.ensemble_inputs(
                stem_outputs,
                algorithm,
                self.is_normalization,
                self.wav_type_set,
                stem_save_path,
                is_wave=self.is_wav_ensemble,
                min_peak=self.amplification_threshold,
            )
            _save_format(stem_save_path, self.save_format, self.mp3_bit_set, self.flac_bit_set)

        if self.is_save_all_outputs_ensemble:
            for stem_output in stem_outputs:
                _save_format(stem_output, self.save_format, self.mp3_bit_set, self.flac_bit_set)
        else:
            for stem_output in stem_outputs:
                try:
                    os.remove(stem_output)
                except OSError:
                    pass

    def get_files_to_ensemble(self, folder="", prefix="", suffix=""):
        """Grab all the per-member output files to be ensembled for one stem."""
        if not os.path.isdir(folder):
            return []
        return [
            os.path.join(folder, name)
            for name in os.listdir(folder)
            if name.startswith(prefix) and name.endswith(suffix)
        ]
