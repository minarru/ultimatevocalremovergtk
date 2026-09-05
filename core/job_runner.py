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
import time
import typing
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Literal, Optional, Sequence

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

from . import job_callbacks, run_hooks
from .debug_log import (
    current_operation_id,
    debug,
    debug_elapsed,
    log_event,
    new_operation_id,
    set_operation_id,
)
from .ensembler import Ensembler
from .export_naming import (
    OutputNamingContext,
    build_output_naming_context,
    rebase_output_naming,
)
from .inference_cleanup import (
    clear_source_mapper,
)
from .inference_cleanup import (
    release_inference_memory as _release_inference_resources,
)
from .job_plan import PlannedInput, ResolvedJob
from .model_config import ModelConfig, assemble_model
from .model_repository import ModelRepository
from .process_data import ProcessData
from .run_estimate import count_inference_passes_from_models
from .run_loop import (
    run_models_on_files,
    with_worker_lifecycle,
)
from .sample_mode import prepare_input_paths
from .separate_import import import_separate_engines
from .separator_run import apply_segment_override
from .settings import Settings
from .stem_pairs import is_stem_mode, normalize_stem_pair_id
from .types import ProcessMethod

if TYPE_CHECKING:
    from kthread import KThread

    from engines.model_weight_cache import FileIdentity


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


_MODEL_KEY_BY_METHOD = {
    VR_ARCH_PM: "vr_model",
    MDX_ARCH_TYPE: "mdx_net_model",
    DEMUCS_ARCH_TYPE: "demucs_model",
}


@dataclass(frozen=True)
class InputOutcome:
    """Per-input result from :meth:`JobRunner.start_resolved`."""

    path: str
    status: str  # "success" | "failed" | "skipped"
    outputs: tuple[str, ...] = ()
    error: str | None = None
    elapsed_s: float = 0.0
    stopped: bool = False


class JobRunner:
    """Runs separation on a ``KThread`` worker and reports through callbacks."""

    def __init__(self, settings: Settings, repo: Optional[ModelRepository] = None):
        self.settings = settings
        if repo is None:
            self.repo = ModelRepository()
            self.repo.bind_model_hash_table(lambda: self.settings.process.model_hash_table)
        else:
            self.repo = repo
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
        self._run_model_dependencies: typing.Mapping[str, Any] | None = None
        self._run_planned: Sequence[PlannedInput] | None = None
        self._run_output_root: str | None = None
        self._run_path_map: dict[str, str] | None = None
        self._resolved_command: str | None = None
        self._operation_id: str | None = None
        self.last_outcomes: tuple[InputOutcome, ...] = ()

    # -- Public control ---------------------------------------------------------

    @property
    def last_oom_exported(self) -> bool:
        return bool(self._last_oom_exported)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _reset_run_state(self) -> None:
        self._is_stopped = False
        self._is_paused = False
        self._mdx_segment_override = None
        self._ensemble_salvage_members = []
        self._last_oom_exported = False
        self._run_models = None
        self._run_model_dependencies = None
        self._run_planned = None
        self._run_output_root = None
        self._run_path_map = None
        self._resolved_command = None
        self._operation_id = None
        self.last_outcomes = ()

    def start(
        self,
        input_paths: Sequence[str],
        callbacks: job_callbacks.JobCallbacks,
        *,
        models: Sequence[Any] | None = None,
        planned: Sequence[PlannedInput] | None = None,
        planned_output_root: str | None = None,
        model_dependencies: typing.Mapping[str, Any] | None = None,
        operation_id: str | None = None,
    ) -> None:
        """Launch the worker thread. No-op if a run is already in flight.

        Infers ensemble vs single from ``settings.process.method`` (set
        ``ProcessMethod.ENSEMBLE`` before calling). When ``models`` is
        supplied, the worker reuses that assembly and does not call
        :meth:`resolve_models`. When ``planned`` is supplied, per-file
        basenames come from the matching :class:`~core.job_plan.PlannedInput`
        after rebasing onto the current export path. ``planned_output_root``
        is required in that case so model-folder rebasing cannot flatten.
        ``model_dependencies`` carries the accepted plan's exact nested model
        records into legacy GUI worker assembly.
        """
        if self.is_running():
            return
        mode: Literal["single", "ensemble"] = (
            "ensemble" if self.settings.process.method == ProcessMethod.ENSEMBLE else "single"
        )
        self._start_worker(
            input_paths,
            callbacks,
            mode=mode,
            models=models,
            planned=planned,
            planned_output_root=planned_output_root,
            model_dependencies=model_dependencies,
            operation_id=operation_id,
        )

    def _start_worker(
        self,
        input_paths: Sequence[str],
        callbacks: job_callbacks.JobCallbacks,
        *,
        mode: Literal["single", "ensemble"],
        models: Sequence[Any] | None = None,
        planned: Sequence[PlannedInput] | None = None,
        planned_output_root: str | None = None,
        model_dependencies: typing.Mapping[str, Any] | None = None,
        operation_id: str | None = None,
    ) -> None:
        """Shared KThread launch for single-method and ensemble workers."""
        if self.is_running():
            return
        if planned is not None and not planned_output_root:
            raise ValueError("planned_output_root is required when planned inputs are supplied")
        from kthread import KThread

        self._reset_run_state()
        self._run_models = list(models) if models is not None else None
        self._run_model_dependencies = model_dependencies
        self._run_planned = tuple(planned) if planned is not None else None
        self._run_output_root = planned_output_root
        self._operation_id = operation_id or current_operation_id() or new_operation_id("run")
        paths = [item.path for item in planned] if planned is not None else list(input_paths)
        self._thread = KThread(
            target=self._run_separation,
            args=(paths, callbacks, mode),
        )
        kind = "ensemble" if mode == "ensemble" else "single"
        log_event(
            "worker",
            "worker_started",
            operation_id=self._operation_id,
            kind=kind,
            input_count=len(paths),
        )
        debug("worker", f"KThread {kind} start files={len(paths)}")
        self._thread.start()

    def start_resolved(
        self,
        job: "ResolvedJob",
        callbacks: job_callbacks.JobCallbacks,
        *,
        models: Sequence[Any] | None = None,
        fail_fast: bool = True,
        export_paths: Sequence[str] | None = None,
        operation_id: str | None = None,
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
        self._operation_id = operation_id or current_operation_id() or new_operation_id("job")
        self._thread = KThread(
            target=self._run_resolved,
            args=(
                job,
                callbacks,
                models,
                fail_fast,
                export_paths,
                self._operation_id,
            ),
        )
        log_event(
            "worker",
            "worker_started",
            operation_id=self._operation_id,
            kind=job.command,
            input_count=len(job.inputs),
        )
        debug("worker", f"KThread resolved start inputs={len(job.inputs)}")
        self._thread.start()

    def _run_resolved(
        self,
        job: "ResolvedJob",
        callbacks: job_callbacks.JobCallbacks,
        models: Sequence[Any] | None,
        fail_fast: bool,
        export_paths: Sequence[str] | None,
        operation_id: str | None,
    ) -> None:
        set_operation_id(operation_id)
        outcomes: list[InputOutcome] = []
        try:
            if models is not None:
                self._run_models = list(models)
            else:
                self._run_models = self.resolve_models(job.model_dependencies)
            self._run_output_root = job.output
            self._resolved_command = job.command

            for index, planned in enumerate(job.inputs):
                log_event(
                    "worker",
                    "input_started",
                    operation_id=operation_id,
                    input_index=index + 1,
                    input_count=len(job.inputs),
                    input_path=planned.path,
                )
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
                log_event(
                    "worker",
                    "input_completed",
                    operation_id=operation_id,
                    input_index=index + 1,
                    status=outcome.status,
                    output_count=len(outcome.outputs),
                    elapsed_s=round(outcome.elapsed_s, 6),
                    error=outcome.error,
                )
                self.last_outcomes = tuple(outcomes)
                if outcome.stopped:
                    break
                if outcome.status == "failed" and fail_fast:
                    break

            self.last_outcomes = tuple(outcomes)
            if any(item.stopped for item in outcomes):
                log_event(
                    "worker",
                    "worker_stopped",
                    operation_id=operation_id,
                    completed_inputs=len(outcomes),
                )
                callbacks.stopped()
            else:
                log_event(
                    "worker",
                    "worker_completed",
                    operation_id=operation_id,
                    completed_inputs=len(outcomes),
                    failed_inputs=sum(item.status == "failed" for item in outcomes),
                )
                callbacks.complete()
        except Exception as exc:  # surfaced through the callback
            self.last_outcomes = tuple(outcomes)
            if self._is_stopped:
                log_event(
                    "worker",
                    "worker_stopped",
                    operation_id=operation_id,
                    completed_inputs=len(outcomes),
                )
                callbacks.stopped()
                return
            log_event(
                "worker",
                "worker_failed",
                level="error",
                operation_id=operation_id,
                error_type=type(exc).__name__,
                error=str(exc),
                completed_inputs=len(outcomes),
            )
            callbacks.error(exc)
            _release_inference_resources(self, park_weights=True)

    def _run_one_planned(
        self,
        planned: "PlannedInput",
        callbacks: job_callbacks.JobCallbacks,
    ) -> InputOutcome:
        """Run a single planned input using :meth:`_run_separation`."""
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

        item_callbacks = job_callbacks.JobCallbacks(
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
            mode: Literal["single", "ensemble"] = "ensemble" if use_ensemble else "single"
            self._run_separation([planned.path], item_callbacks, mode)
        except Exception as exc:  # convert to outcome
            return InputOutcome(
                path=planned.path,
                status="failed",
                error=str(exc),
                elapsed_s=time.perf_counter() - started,
            )

        if box["status"] == "success":
            missing_required = tuple(
                output.path
                for output in planned.outputs
                if not output.conditional and not os.path.isfile(output.path)
            )
            if missing_required:
                return InputOutcome(
                    path=planned.path,
                    status="failed",
                    error=f"Missing required output after processing: {missing_required!r}",
                    elapsed_s=time.perf_counter() - started,
                )
            box["outputs"] = tuple(
                output.path for output in planned.outputs if os.path.isfile(output.path)
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
                entry for entry in self._run_planned if os.path.abspath(entry.path) == target
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
        self, input_paths: List[str], callbacks: job_callbacks.JobCallbacks
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
            except Exception:  # logging must not abort the run
                debug("model", f"sample clip fallback log failed: {exc}")

        prep_started = time.perf_counter()
        prepared = prepare_input_paths(self.settings, input_paths, on_fallback=on_fallback)
        debug_elapsed("worker", "prepare_input_paths", prep_started, files=len(prepared))
        if self._run_planned is not None:
            # Sample mode (and any future rewrite) can replace paths; map the
            # prepared path back to the original so planned lookup still hits.
            self._run_path_map = {
                os.path.abspath(prep): os.path.abspath(orig)
                for orig, prep in zip(input_paths, prepared, strict=False)
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

    def _cached_source_callback(self, process_method: typing.Any, model_name: typing.Any = None):
        mapper = self._mapper_for(process_method)
        if model_name and model_name in mapper:
            return model_name, mapper[model_name]
        return None, None

    def _cached_model_source_holder(
        self, process_method: typing.Any, sources: typing.Any, model_name: typing.Any = None
    ):
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

    def resolve_models(
        self,
        model_dependencies: typing.Mapping[str, typing.Any] | None = None,
    ) -> List[ModelConfig]:
        """Build the ``ModelConfig`` list for the currently chosen method."""
        method = ProcessMethod(self.settings.process.method)
        if method is ProcessMethod.ENSEMBLE:
            return assemble_model(
                self.settings,
                self.repo,
                arch_type=ENSEMBLE_MODE,
                model_dependencies=model_dependencies,
            )
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
        return assemble_model(
            self.settings,
            self.repo,
            model_name,
            method.value,
            model_dependencies=model_dependencies,
        )

    def _count_true_models(self, models: Sequence[Any]) -> int:
        """Progress denominator: shared with the Save stems workload estimate."""
        return count_inference_passes_from_models(models)

    def _build_all_models(self, models: List[ModelConfig]) -> None:
        """Port of ``cached_source_model_list_check``'s ``all_models`` list.

        The engines use ``list_all_models`` to decide whether a referenced
        primary/secondary model participates in the current run.
        """
        primary = [
            getattr(m, "backend_name", None) or m.model_basename
            for m in models
            if getattr(m, "backend_name", None) or m.model_basename
        ]
        secondary = []
        for m in models:
            if not m.is_secondary_model_activated or m.secondary_model is None:
                continue
            name = (
                getattr(m.secondary_model, "backend_name", None) or m.secondary_model.model_basename
            )
            if name:
                secondary.append(name)
        pre_proc: List[str] = []
        for m in models:
            proc = getattr(m, "pre_proc_model", None)
            if proc is not None:
                name = getattr(proc, "backend_name", None) or proc.model_basename
                if name:
                    pre_proc.append(name)
        demucs_4_stem: List[str] = []
        for m in models:
            if m.process_method == DEMUCS_ARCH_TYPE and getattr(
                m, "is_demucs_4_stem_secondaries", False
            ):
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
        callbacks: job_callbacks.JobCallbacks,
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
            callbacks.console("Low GPU memory — freed unused cached models for this run\n")
        elif action in {"parked_all", "cleared_all"}:
            callbacks.console("Low GPU memory — freed all cached models for this run\n")

    def _build_separator(
        self,
        current_model: ModelConfig,
        process_data: ProcessData,
    ) -> Any:
        """Construct the engine instance for ``current_model``.

        Dispatch lives in :func:`engines.separator_factory.build_seperator`.
        Segment backoff stays on the job path only.
        """
        from engines.separator_factory import build_seperator

        apply_segment_override(self, current_model)
        return build_seperator(current_model, process_data)

    def _run_separation(
        self,
        input_paths: List[str],
        callbacks: job_callbacks.JobCallbacks,
        mode: Literal["single", "ensemble"],
    ) -> None:
        """Run single-method separation or an ensemble (member passes + combine).

        Tk-free port of ``process_start``'s separation branches. Ensemble mode
        runs each member with ``is_ensemble_master`` so engines write per-member
        stems into the ensemble temp folder, then :class:`Ensembler` combines
        those stems per the chosen algorithm into the final outputs.
        """
        import shutil

        set_operation_id(self._operation_id)

        lifecycle_label = "_run_ensemble" if mode == "ensemble" else "_run"
        debug("worker", f"{lifecycle_label} entered")
        import_started = time.perf_counter()
        import_separate_engines()
        debug_elapsed("worker", "separate engines ready", import_started)

        def body() -> None:
            paths = self._prepare_paths_for_run(input_paths, callbacks)
            single_export_path: str | None = None
            if mode == "single":
                single_export_path = self.settings.process.export_path
                if not single_export_path:
                    raise ValueError("export_path is required")

            resolve_started = time.perf_counter()
            if self._run_models is not None:
                models = list(self._run_models)
            elif mode == "ensemble":
                models = assemble_model(
                    self.settings,
                    self.repo,
                    arch_type=ENSEMBLE_MODE,
                    model_dependencies=self._run_model_dependencies,
                )
            else:
                models = self.resolve_models(self._run_model_dependencies)
            debug_elapsed("worker", "resolve_models", resolve_started, count=len(models))

            ensemble_export_path: str | None = None
            if mode == "ensemble":
                if len(models) <= 1:
                    raise RuntimeError("Select at least two models to run an ensemble")
                ensemble = Ensembler(self.settings)
                ensemble_export_path = ensemble.ensemble_folder_name
                is_multi_stem = is_stem_mode(
                    normalize_stem_pair_id(self.settings.ensemble.main_stem)
                )
                hooks: Any = run_hooks._EnsembleRunHooks(ensemble, is_multi_stem)
            else:
                assert single_export_path is not None
                try:
                    amp_threshold = float(self.settings.process.amplification_threshold or 0.0)
                except (TypeError, ValueError):
                    amp_threshold = 0.0
                hooks = run_hooks._SingleRunHooks(single_export_path, amp_threshold)

            self.iteration = 0
            self._build_all_models(models)
            self._set_run_protect_identities(models)
            self._ensure_vram_for_job(callbacks)
            self.true_model_count = self._count_true_models(models)
            run_models_on_files(
                self,
                paths,
                callbacks,
                models,
                hooks=hooks,
            )
            if mode == "ensemble" and ensemble_export_path is not None:
                try:
                    if (
                        os.path.isdir(ensemble_export_path)
                        and len(os.listdir(ensemble_export_path)) == 0
                    ):
                        shutil.rmtree(ensemble_export_path)
                except OSError:
                    pass

        with_worker_lifecycle(self, callbacks, lifecycle_label, body)
