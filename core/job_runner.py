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
import typing

import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Sequence

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    PRIMARY_STEM,
    PROCESS_STOPPED_BY_USER,
    SECONDARY_STEM,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

from . import paths
from .audio_io import resolve_wav_type_set
from .ensembler import (
    Ensembler,
    _ensemble_stem_bucket,
    _extract_stems,
    _filter_final_ensemble_stems,
)
from .export_naming import (
    OutputNamingContext,
    build_output_naming_context,
    rebase_output_naming,
)
from .model_config import ModelConfig, assemble_model
from .model_data import ModelRepository
from .process_data import ProcessData
from .sample_mode import prepare_input_paths
from .settings import Settings
from .stems import coerce_ensemble_pair, exclusive_flags_for_pair
from .run_control import ProcessStopped, check_stopped, pausable_callback
from .run_estimate import combine_progress_local_step, count_inference_passes_from_models
from .debug_log import debug, debug_elapsed, next_seq, preview_text, set_correlation_seq, verbose
from .error_context import snapshot_worker_file
from .model_display import display_name_for_model
from .separate_import import import_separate_engines
from .types import ProcessMethod
from .inference_cleanup import (
    clear_source_mapper,
    release_inference_memory as _release_inference_resources,
)
from .oom_choice import (
    OOM_CHOICE_AUTO,
    OOM_CHOICE_STOP,
    OomChoiceRequest,
)
from .separator_run import apply_segment_override, run_separator

if TYPE_CHECKING:
    from engines.model_weight_cache import FileIdentity
    from kthread import KThread
    from .job_plan import PlannedInput, ResolvedJob


def collect_run_model_paths(models: Sequence[ModelConfig]) -> set[str]:
    """Collect on-disk model paths for every model participating in this run."""
    found: set[str] = set()

    def add(model: Optional[ModelConfig]) -> None:
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


def _decoded_mix_for_process(audio_file: typing.Any):
    """Decode once per track so ensemble / secondary models reuse the same mix."""
    from engines.mix import prepare_mix

    return prepare_mix(audio_file)


_MODEL_KEY_BY_METHOD = {
    VR_ARCH_PM: "vr_model",
    MDX_ARCH_TYPE: "mdx_net_model",
    DEMUCS_ARCH_TYPE: "demucs_model",
}


def _model_output_label(model: ModelConfig) -> str:
    """Return the user-facing model label for export paths and test mode."""
    label = display_name_for_model(model.process_method, model.model_name, model.repo)
    return label or model.model_basename or ""


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
        label = _model_output_label(model)
        if model_count > 1:
            parts.append(f"Model {model_num}/{model_count}" + (f" · {label}" if label else ""))
        elif label:
            parts.append(label)
    return " · ".join(parts) if parts else None


@dataclass
class _ProgressSink:
    """Mutable last-fraction holder shared by a run's progress callback."""

    fraction: float = 0.0


def _bind_set_progress_bar(
    runner: "JobRunner",
    callbacks: "JobCallbacks",
    progress_ctx: dict[str, Any],
    *,
    total_files: int,
    total_chunk_units: int,
    sink: _ProgressSink,
) -> Callable[..., None]:
    """Map engine ``set_progress_bar(step, iterations)`` onto ``callbacks.progress``."""

    def set_progress_bar(
        step: typing.Any, inference_iterations: typing.Any = 0
    ) -> None:
        total_count = max(1, runner.true_model_count * total_chunk_units)
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


@dataclass(frozen=True)
class InputOutcome:
    """Per-input result from :meth:`JobRunner.start_resolved`."""

    path: str
    status: str  # "success" | "failed" | "skipped"
    outputs: tuple[str, ...] = ()
    error: str | None = None
    elapsed_s: float = 0.0
    stopped: bool = False


@dataclass
class JobCallbacks:
    """Callbacks invoked from the worker thread.

    ``on_progress`` receives a float in ``[0.0, 1.0]`` plus optional keyword
    metadata (``local_step``, ``pass_index``, ``pass_total``, ``detail``,
    ``combine_index``, ``combine_total``). ``on_console`` receives text chunks;
    ``on_complete`` fires once on success; ``on_error`` receives the raised
    exception. ``on_oom_choice`` receives an :class:`OomChoiceRequest` on the
    main loop; the worker blocks until ``request.respond`` is called. The GTK
    layer marshals each of these onto the main loop.
    """

    on_progress: Optional[Callable[..., None]] = None
    on_console: Optional[Callable[[str], None]] = None
    on_complete: Optional[Callable[[], None]] = None
    on_stopped: Optional[Callable[[], None]] = None
    on_error: Optional[Callable[[BaseException], None]] = None
    on_oom_choice: Optional[Callable[[OomChoiceRequest], None]] = None
    on_input_start: Optional[Callable[[tuple[str, ...]], None]] = None
    on_input_finished: Optional[
        Callable[[tuple[str, ...], tuple[str, ...], BaseException | None], None]
    ] = None

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

    def input_started(self, paths: typing.Sequence[str]) -> None:
        if self.on_input_start:
            self.on_input_start(tuple(paths))

    def input_finished(
        self, paths: typing.Sequence[str], generated: typing.Sequence[str] = (),
        error: BaseException | None = None,
    ) -> None:
        if self.on_input_finished:
            self.on_input_finished(tuple(paths), tuple(generated), error)

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

    def request_oom_choice(
        self,
        request: OomChoiceRequest,
        runner: "JobRunner",
    ) -> str:
        """Ask the UI for an OOM recovery choice, or return ``auto`` if unbound."""
        if not self.on_oom_choice:
            return OOM_CHOICE_AUTO

        done = threading.Event()
        box: dict[str, str] = {"choice": OOM_CHOICE_STOP}

        def reply(choice: str) -> None:
            box["choice"] = str(choice or OOM_CHOICE_STOP)
            done.set()

        request.reply = reply
        debug(
            "worker",
            "oom choice requested "
            f"kind={request.process_kind!r} export={request.can_export} "
            f"retry={request.can_retry}",
        )
        self.on_oom_choice(request)
        while not done.wait(timeout=0.05):
            check_stopped(runner)
        choice = box["choice"]
        debug("worker", f"oom choice={choice!r}")
        return choice


class JobRunner:
    """Runs separation on a ``KThread`` worker and reports through callbacks."""

    def __init__(self, settings: Settings, repo: Optional[ModelRepository] = None):
        self.settings = settings
        self.repo = repo or ModelRepository()
        self._thread: Optional[KThread] = None
        self._is_stopped = False
        self._is_paused = False
        self.iteration = 0
        self.true_model_count = 0
        # Per-run secondary-source caches consumed by the engines.
        self._vr_cache_source_mapper: dict[str, Any] = {}
        self._mdx_cache_source_mapper: dict[str, Any] = {}
        self._demucs_cache_source_mapper: dict[str, Any] = {}
        self.all_models: List[str] = []
        self._active_separator: Any = None
        self._run_protect_identities: set[FileIdentity] = set()
        self._last_backend_name: Optional[str] = None
        self._mdx_segment_override: Optional[int] = None
        self._ensemble_salvage_members: list[dict[str, Any]] = []
        self._last_oom_exported = False
        self._run_models: Sequence[Any] | None = None
        self._run_planned: Sequence[Any] | None = None
        self._run_output_root: str | None = None
        self._run_path_map: dict[str, str] | None = None
        self._resolved_command: str | None = None
        self.last_outcomes: tuple[InputOutcome, ...] = ()

    # -- Public control ---------------------------------------------------------

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _reset_run_state(self) -> None:
        self._is_stopped = False
        self._is_paused = False
        self._mdx_segment_override = None
        self._ensemble_salvage_members = []
        self._last_oom_exported = False
        self._run_models = None
        self._run_planned = None
        self._run_output_root = None
        self._run_path_map = None
        self._resolved_command = None
        self.last_outcomes = ()

    def start(
        self,
        input_paths: Sequence[str],
        callbacks: JobCallbacks,
        *,
        models: Sequence[Any] | None = None,
        planned: Sequence[Any] | None = None,
        planned_output_root: str | None = None,
    ) -> None:
        """Launch the worker thread. No-op if a run is already in flight.

        Routes to the ensemble worker when ``chosen_process_method`` is
        ``ENSEMBLE_MODE`` (mirroring ``process_start``'s branch), otherwise the
        single-method worker.

        When ``models`` is supplied, the worker reuses that assembly and does
        not call :meth:`resolve_models`. When ``planned`` is supplied, per-file
        basenames come from the matching :class:`~core.job_plan.PlannedInput`
        after rebasing onto the current export path.
        """
        if self.is_running():
            return
        if self.settings.process.method == ProcessMethod.ENSEMBLE:
            self.start_ensemble(
                input_paths,
                callbacks,
                models=models,
                planned=planned,
                planned_output_root=planned_output_root,
            )
            return
        from kthread import KThread

        self._reset_run_state()
        self._run_models = list(models) if models is not None else None
        self._run_planned = tuple(planned) if planned is not None else None
        self._run_output_root = planned_output_root
        paths = list(input_paths)
        self._thread = KThread(
            target=self._run,
            args=(paths, callbacks),
        )
        debug("worker", f"KThread start files={len(paths)}")
        self._thread.start()

    def start_ensemble(
        self,
        input_paths: Sequence[str],
        callbacks: JobCallbacks,
        *,
        models: Sequence[Any] | None = None,
        planned: Sequence[Any] | None = None,
        planned_output_root: str | None = None,
    ) -> None:
        """Launch the ensemble worker thread explicitly. No-op if already running."""
        if self.is_running():
            return
        from kthread import KThread

        self._reset_run_state()
        self._run_models = list(models) if models is not None else None
        self._run_planned = tuple(planned) if planned is not None else None
        self._run_output_root = planned_output_root
        paths = list(input_paths)
        self._thread = KThread(
            target=self._run_ensemble,
            args=(paths, callbacks),
        )
        debug("worker", f"KThread ensemble start files={len(paths)}")
        self._thread.start()

    def start_resolved(
        self,
        job: "ResolvedJob",
        callbacks: JobCallbacks,
        *,
        models: Sequence[Any] | None = None,
        fail_fast: bool = True,
        export_paths: Sequence[str] | None = None,
    ) -> None:
        """Assemble models once and walk every planned input on one worker.

        Does not promote outputs. Per-input results land in
        :attr:`last_outcomes`. ``on_complete`` fires when the batch finishes
        without an unexpected runner failure; per-input failures are recorded
        as outcomes and do not call ``on_error``.
        """
        if self.is_running():
            return
        from kthread import KThread

        self._reset_run_state()
        self._run_output_root = job.output
        self._resolved_command = job.command
        self._thread = KThread(
            target=self._run_resolved,
            args=(job, callbacks, models, fail_fast, export_paths),
        )
        debug("worker", f"KThread resolved start inputs={len(job.inputs)}")
        self._thread.start()

    def _run_resolved(
        self,
        job: "ResolvedJob",
        callbacks: JobCallbacks,
        models: Sequence[Any] | None,
        fail_fast: bool,
        export_paths: Sequence[str] | None,
    ) -> None:
        outcomes: list[InputOutcome] = []
        try:
            if models is not None:
                self._run_models = list(models)
            else:
                self._run_models = self.resolve_models()
            self._run_output_root = job.output
            self._resolved_command = job.command

            for index, planned in enumerate(job.inputs):
                previous_export: str | None = None
                if export_paths is not None:
                    previous_export = self.settings.process.export_path
                    self.settings.process.export_path = export_paths[index]
                try:
                    outcome = self._run_one_planned(planned, callbacks)
                finally:
                    if export_paths is not None and previous_export is not None:
                        self.settings.process.export_path = previous_export
                outcomes.append(outcome)
                self.last_outcomes = tuple(outcomes)
                if outcome.stopped:
                    break
                if outcome.status == "failed" and fail_fast:
                    break

            self.last_outcomes = tuple(outcomes)
            if any(item.stopped for item in outcomes):
                callbacks.stopped()
            else:
                callbacks.complete()
        except Exception as exc:  # noqa: BLE001 - surfaced through the callback
            self.last_outcomes = tuple(outcomes)
            if self._is_stopped:
                callbacks.stopped()
                return
            callbacks.error(exc)
            _release_inference_resources(self, park_weights=True)

    def _run_one_planned(
        self,
        planned: "PlannedInput",
        callbacks: JobCallbacks,
    ) -> InputOutcome:
        """Run a single planned input using the existing ``_run`` / ``_run_ensemble`` body."""
        started = time.perf_counter()
        box: dict[str, Any] = {
            "status": "success",
            "error": None,
            "stopped": False,
            "outputs": tuple(output.path for output in planned.outputs),
        }

        def on_stopped() -> None:
            box["stopped"] = True
            box["status"] = "skipped"

        def on_error(exc: BaseException) -> None:
            box["status"] = "failed"
            box["error"] = str(exc)
            box["outputs"] = ()

        item_callbacks = JobCallbacks(
            on_progress=callbacks.on_progress,
            on_console=callbacks.on_console,
            on_complete=None,
            on_stopped=on_stopped,
            on_error=on_error,
            on_oom_choice=callbacks.on_oom_choice,
            on_input_start=callbacks.on_input_start,
            on_input_finished=callbacks.on_input_finished,
        )

        self._run_planned = (planned,)
        use_ensemble = (
            self._resolved_command == "ensemble"
            or self.settings.process.method == ProcessMethod.ENSEMBLE
        )
        try:
            if use_ensemble:
                self._run_ensemble([planned.path], item_callbacks)
            else:
                self._run([planned.path], item_callbacks)
        except Exception as exc:  # noqa: BLE001 - convert to outcome
            return InputOutcome(
                path=planned.path,
                status="failed",
                error=str(exc),
                elapsed_s=time.perf_counter() - started,
            )

        return InputOutcome(
            path=planned.path,
            status=str(box["status"]),
            outputs=tuple(box["outputs"]) if box["status"] == "success" else (),
            error=box["error"],
            elapsed_s=time.perf_counter() - started,
            stopped=bool(box["stopped"]),
        )

    def _naming_for_file(
        self,
        audio_file: str,
        *,
        export_path: str,
        **build_kwargs: Any,
    ) -> OutputNamingContext:
        """Build or rebase per-file naming for the current run.

        ``PlannedInput.naming`` is the **final** export basename only. Ensemble
        member writes must use :meth:`_ensemble_member_naming_for_file` instead.

        When ``_run_planned`` is set, every input must resolve to a planned
        entry (after sample-mode path remapping). A miss fails closed.
        """
        if self._run_planned is not None:
            target = os.path.abspath(audio_file)
            if self._run_path_map is not None:
                target = self._run_path_map.get(target, target)
            item = next(
                entry
                for entry in self._run_planned
                if os.path.abspath(entry.path) == target
            )
            return rebase_output_naming(
                item.naming,
                self.settings.process.export_path,
                self._run_output_root or item.naming.export_directory,
            )
        return build_output_naming_context(
            self.settings, audio_file, export_path=export_path, **build_kwargs
        )

    def _ensemble_member_naming_for_file(
        self,
        audio_file: str,
        *,
        export_path: str,
        file_index: int,
        file_total: int,
        model_label: str,
    ) -> OutputNamingContext:
        """Per-member basename; never rebased from ``PlannedInput.naming``."""
        naming_input = os.path.abspath(audio_file)
        if self._run_path_map is not None:
            naming_input = self._run_path_map.get(naming_input, naming_input)
        return build_output_naming_context(
            self.settings,
            naming_input,
            export_path=export_path,
            file_index=file_index,
            file_total=file_total,
            model_label=model_label,
            force_model_label=True,
        )

    def _prepare_paths_for_run(
        self, input_paths: List[str], callbacks: JobCallbacks
    ) -> List[str]:
        """Build sample clips on the worker thread and report any fallbacks."""
        if self.settings.process.sample_mode:
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
        if self._run_planned is not None:
            # Sample mode (and any future rewrite) can replace paths; map the
            # prepared path back to the original so planned lookup still hits.
            self._run_path_map = {
                os.path.abspath(prep): os.path.abspath(orig)
                for orig, prep in zip(input_paths, prepared)
            }
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

    def _cached_source_callback(self, process_method: typing.Any, model_name: typing.Any=None):
        mapper = self._mapper_for(process_method)
        if model_name and model_name in mapper:
            return model_name, mapper[model_name]
        return None, None

    def _cached_model_source_holder(self, process_method: typing.Any, sources: typing.Any, model_name: typing.Any=None):
        mapper = self._mapper_for(process_method)
        mapper[model_name] = sources

    def _mapper_for(self, process_method: typing.Any) -> dict:
        if process_method == VR_ARCH_TYPE:
            return self._vr_cache_source_mapper
        if process_method == MDX_ARCH_TYPE:
            return self._mdx_cache_source_mapper
        return self._demucs_cache_source_mapper

    def _process_iteration(self) -> None:
        self.iteration += 1

    # -- Worker -----------------------------------------------------------------

    def resolve_models(self) -> List[ModelConfig]:
        """Build the ``ModelConfig`` list for the currently chosen method."""
        method = ProcessMethod(self.settings.process.method)
        if method is ProcessMethod.ENSEMBLE:
            return assemble_model(self.settings, self.repo, arch_type=ENSEMBLE_MODE)
        if method is ProcessMethod.VR:
            model_name = self.settings.vr.model
        elif method is ProcessMethod.MDX:
            model_name = self.settings.mdx.model
        elif method is ProcessMethod.DEMUCS:
            model_name = self.settings.demucs.model
        else:
            raise NotImplementedError(
                f"process method '{method.value}' is implemented in a later phase"
            )
        return assemble_model(self.settings, self.repo, model_name, method.value)

    def _count_true_models(self, models: Sequence[Any]) -> int:
        """Progress denominator: shared with the Save stems workload estimate."""
        return count_inference_passes_from_models(models)

    def _build_all_models(self, models: List[ModelConfig]) -> None:
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

    def _set_run_protect_identities(self, models: List[ModelConfig]) -> None:
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
            target = self.settings.process.device
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

    def _build_separator(
        self,
        current_model: ModelConfig,
        process_data: ProcessData,
        *,
        SeperateVR: Any,
        SeperateMDX: Any,
        SeperateMDXC: Any,
        SeperateDemucs: Any,
    ) -> Any:
        """Construct the engine instance for ``current_model``."""
        apply_segment_override(self, current_model)
        if current_model.process_method == VR_ARCH_TYPE:
            return SeperateVR(current_model, process_data)
        if current_model.process_method == MDX_ARCH_TYPE:
            if current_model.is_mdx_c:
                return SeperateMDXC(current_model, process_data)
            return SeperateMDX(current_model, process_data)
        if current_model.process_method == DEMUCS_ARCH_TYPE:
            return SeperateDemucs(current_model, process_data)
        raise NotImplementedError(
            f"engine for '{current_model.process_method}' not available"
        )

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
            export_path = self.settings.process.export_path
            if not export_path:
                raise ValueError("export_path is required")
            resolve_started = time.perf_counter()
            if self._run_models is not None:
                models = list(self._run_models)
            else:
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

            progress_sink = _ProgressSink()
            progress_ctx = {
                "file_num": 1,
                "model": None,
                "model_num": 0,
                "model_count": len(models),
                "chunk_num": 0,
                "chunk_total": 0,
            }

            try:
                amp_threshold = float(
                    self.settings.process.amplification_threshold or 0.0
                )
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

                set_progress_bar = pausable_callback(
                    self,
                    _bind_set_progress_bar(
                        self,
                        callbacks,
                        progress_ctx,
                        total_files=total_files,
                        total_chunk_units=total_chunk_units,
                        sink=progress_sink,
                    ),
                )

                for model_num, current_model in enumerate(models, start=1):
                    check_stopped(self)
                    progress_ctx["model"] = current_model
                    progress_ctx["model_num"] = model_num
                    write_to_console = pausable_callback(
                        self,
                        lambda text, base_text=base_text: callbacks.console(base_text + text),
                    )

                    model_label = _model_output_label(current_model)
                    naming = self._naming_for_file(
                        audio_file,
                        export_path=export_path,
                        file_index=file_num,
                        file_total=total_files,
                        model_label=model_label,
                    )
                    audio_file_base = naming.track_base
                    model_export_path = naming.export_directory
                    if model_export_path != export_path:
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

                        process_data = ProcessData(
                            export_path=model_export_path,
                            audio_file_base=audio_file_base,
                            audio_file=mix_slice if chunked else decoded_mix,
                            set_progress_bar=set_progress_bar,
                            write_to_console=write_to_console,
                            process_iteration=pausable_callback(self, self._process_iteration),
                            check_run_control=pausable_callback(self, lambda: check_stopped(self)),
                            cached_source_callback=self._cached_source_callback,
                            cached_model_source_holder=self._cached_model_source_holder,
                            list_all_models=self.all_models,
                            is_ensemble_master=False,
                            is_4_stem_ensemble=False,
                            capture_stems_only=chunked,
                        )

                        def _make_rebuild(
                            model: ModelConfig, pdata: ProcessData
                        ) -> Callable[[], Any]:
                            def _rebuild() -> Any:
                                return self._build_separator(
                                    model,
                                    pdata,
                                    SeperateVR=SeperateVR,
                                    SeperateMDX=SeperateMDX,
                                    SeperateMDXC=SeperateMDXC,
                                    SeperateDemucs=SeperateDemucs,
                                )

                            return _rebuild

                        rebuild_sep = _make_rebuild(current_model, process_data)
                        seperator = rebuild_sep()
                        engine = type(seperator).__name__
                        debug(
                            "worker",
                            f"separate start engine={engine} model={current_model.model_basename!r} "
                            f"chunk={chunk_num}/{n_chunks}",
                        )
                        member_stems = run_separator(
                            self,
                            seperator,
                            callbacks=callbacks,
                            model=current_model,
                            process_kind="separation",
                            rebuild=rebuild_sep,
                        ) or {}
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
                            is_normalization=bool(self.settings.process.normalization),
                            amplification_threshold=amp_threshold,
                            wav_type_set=resolve_wav_type_set(self.settings),
                            save_format_name=self.settings.process.save_format.value,
                            mp3_bit_set=self.settings.process.mp3_bitrate,
                            flac_bit_set=self.settings.process.flac_bit_depth,
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
            if self._run_models is not None:
                models = list(self._run_models)
            else:
                models = assemble_model(self.settings, self.repo, arch_type=ENSEMBLE_MODE)
            if len(models) <= 1:
                raise RuntimeError("Select at least two models to run an ensemble")

            ensemble = Ensembler(self.settings)
            export_path = ensemble.ensemble_folder_name
            is_4_stem = coerce_ensemble_pair(
                self.settings.ensemble.main_stem
            ).is_multi_or_four()

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

            progress_sink = _ProgressSink()
            progress_ctx = {
                "file_num": 1,
                "model": None,
                "model_num": 0,
                "model_count": len(models),
                "chunk_num": 0,
                "chunk_total": 0,
            }

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

                set_progress_bar = pausable_callback(
                    self,
                    _bind_set_progress_bar(
                        self,
                        callbacks,
                        progress_ctx,
                        total_files=total_files,
                        total_chunk_units=total_chunk_units,
                        sink=progress_sink,
                    ),
                )
                current_model = None
                # stem_tag -> list of member waveforms for in-memory combine
                ensemble_stem_arrays: dict = {}
                self._ensemble_salvage_members = []
                final_naming = self._naming_for_file(
                    audio_file,
                    export_path=export_path,
                    file_index=file_num,
                    file_total=total_files,
                    ensemble_label=ensemble.append_ensemble_label,
                    force_ensemble_label=True,
                )
                ensemble_final_base = final_naming.track_base

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
                    member_naming = self._ensemble_member_naming_for_file(
                        audio_file,
                        export_path=export_path,
                        file_index=file_num,
                        file_total=total_files,
                        model_label=model_label,
                    )
                    audio_file_base = member_naming.track_base

                    member_stem_parts: dict = {}
                    member_paths: dict = {}
                    last_member_stems: dict = {}
                    for chunk_num, (_start, _end, mix_slice) in enumerate(chunks, start=1):
                        check_stopped(self)
                        snapshot_worker_file(audio_file, current_model)
                        self._process_iteration()
                        progress_ctx["chunk_num"] = chunk_num
                        if chunked:
                            self._cached_sources_clear()

                        process_data = ProcessData(
                            export_path=export_path,
                            audio_file_base=audio_file_base,
                            audio_file=mix_slice if chunked else decoded_mix,
                            set_progress_bar=set_progress_bar,
                            write_to_console=write_to_console,
                            process_iteration=pausable_callback(self, self._process_iteration),
                            check_run_control=pausable_callback(self, lambda: check_stopped(self)),
                            cached_source_callback=self._cached_source_callback,
                            cached_model_source_holder=self._cached_model_source_holder,
                            list_all_models=self.all_models,
                            is_ensemble_master=True,
                            is_4_stem_ensemble=is_4_stem,
                            is_save_all_outputs_ensemble=bool(
                                self.settings.ensemble.save_all_outputs
                            ),
                            capture_stems_only=chunked,
                        )

                        def _make_rebuild(
                            model: ModelConfig, pdata: ProcessData
                        ) -> Callable[[], Any]:
                            def _rebuild() -> Any:
                                return self._build_separator(
                                    model,
                                    pdata,
                                    SeperateVR=SeperateVR,
                                    SeperateMDX=SeperateMDX,
                                    SeperateMDXC=SeperateMDXC,
                                    SeperateDemucs=SeperateDemucs,
                                )

                            return _rebuild

                        rebuild_ens = _make_rebuild(current_model, process_data)
                        seperator = rebuild_ens()
                        engine = type(seperator).__name__
                        debug(
                            "worker",
                            f"ensemble separate start engine={engine} model={current_model.model_basename!r} "
                            f"chunk={chunk_num}/{n_chunks}",
                        )
                        member_stems = run_separator(
                            self,
                            seperator,
                            callbacks=callbacks,
                            model=current_model,
                            process_kind="ensemble",
                            rebuild=rebuild_ens,
                        ) or {}
                        last_member_stems = member_stems
                        chunk_paths = getattr(self, "_last_captured_stem_paths", None) or {}
                        if chunked:
                            for stem_tag, arr in member_stems.items():
                                bucket = _ensemble_stem_bucket(stem_tag)
                                member_stem_parts.setdefault(bucket, []).append(arr)
                                if stem_tag in chunk_paths:
                                    member_paths[bucket] = chunk_paths[stem_tag]
                        else:
                            for stem_tag, arr in member_stems.items():
                                bucket = _ensemble_stem_bucket(stem_tag)
                                ensemble_stem_arrays.setdefault(bucket, []).append(arr)
                                if stem_tag in chunk_paths:
                                    member_paths[bucket] = chunk_paths[stem_tag]
                        debug("worker", f"ensemble separate done engine={engine}")

                    salvage_arrays: dict = {}
                    if chunked:
                        for stem_tag, parts in member_stem_parts.items():
                            concat = concat_stems(parts, overlap_samples=ov_samples)
                            ensemble_stem_arrays.setdefault(
                                _ensemble_stem_bucket(stem_tag), []
                            ).append(concat)
                            salvage_arrays[_ensemble_stem_bucket(stem_tag)] = concat
                    else:
                        for stem_tag, arr in last_member_stems.items():
                            salvage_arrays[_ensemble_stem_bucket(stem_tag)] = arr
                    self._ensemble_salvage_members.append(
                        {
                            "arrays": salvage_arrays,
                            "paths": member_paths,
                            "audio_file_base": audio_file_base,
                            "model_label": model_label,
                        }
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
                    stem_names = _filter_final_ensemble_stems(
                        stem_names, str(self.settings.process.stem_focus or "")
                    )
                    combine_steps = [
                        (output_stem, {"is_4_stem": True}) for output_stem in stem_names
                    ]
                else:
                    primary_only = self.settings.process.primary_stem_only
                    secondary_only = self.settings.process.secondary_stem_only
                    # ``process.stem_focus`` overrides the positional booleans,
                    # resolved against the chosen pair's buckets — never the
                    # already-remapped stem_halves labels with a fake count of 2.
                    focus_flags = exclusive_flags_for_pair(
                        str(self.settings.process.stem_focus or ""),
                        coerce_ensemble_pair(self.settings.ensemble.main_stem),
                    )
                    if focus_flags is not None:
                        primary_only, secondary_only = focus_flags
                    if not secondary_only:
                        combine_steps.append((PRIMARY_STEM, {}))
                    if not primary_only:
                        combine_steps.append((SECONDARY_STEM, {}))
                        combine_steps.append((SECONDARY_STEM, {"is_inst_mix": True}))

                combine_total = max(1, len(combine_steps))
                combine_start = progress_sink.fraction
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
                    progress_sink.fraction = fraction
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

