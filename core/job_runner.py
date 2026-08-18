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
    SECONDARY_STEM,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

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
from .run_control import check_stopped
from .run_estimate import combine_progress_local_step, count_inference_passes_from_models
from .debug_log import debug, debug_elapsed, next_seq, preview_text, set_correlation_seq, verbose
from .model_display import display_name_for_model
from .run_loop import (
    FileState,
    _write_captured_stems,
    run_models_on_files,
    with_worker_lifecycle,
)
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
from .separator_run import apply_segment_override

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


_MODEL_KEY_BY_METHOD = {
    VR_ARCH_PM: "vr_model",
    MDX_ARCH_TYPE: "mdx_net_model",
    DEMUCS_ARCH_TYPE: "demucs_model",
}


def _model_output_label(model: ModelConfig) -> str:
    """Return the user-facing model label for export paths and test mode."""
    label = display_name_for_model(model.process_method, model.model_name, model.repo)
    return label or model.model_basename or ""


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


class _SingleRunHooks:
    """Single-method naming, stem concat, and export for :func:`run_models_on_files`."""

    process_kind = "separation"

    def __init__(self, export_path: str, amp_threshold: float) -> None:
        self.export_path = export_path
        self.amp_threshold = amp_threshold

    def before_file(self, runner: Any, state: FileState) -> None:
        return

    def export_and_base(
        self, runner: Any, state: FileState, model: Any
    ) -> tuple[str, str]:
        model_label = _model_output_label(model)
        naming = runner._naming_for_file(
            state.audio_file,
            export_path=self.export_path,
            file_index=state.file_num,
            file_total=state.total_files,
            model_label=model_label,
        )
        if naming.export_directory != self.export_path:
            os.makedirs(naming.export_directory, exist_ok=True)
        state.scratch["stem_parts"] = {}
        state.scratch["stem_paths"] = {}
        return naming.track_base, naming.export_directory

    def extra_process_data(
        self, runner: Any, state: FileState, model: Any
    ) -> dict:
        return {"is_ensemble_master": False, "is_4_stem_ensemble": False}

    def after_chunk(
        self,
        runner: Any,
        state: FileState,
        model: Any,
        stems: dict,
        paths: dict,
        chunked: bool,
    ) -> None:
        if not chunked:
            return
        parts = state.scratch["stem_parts"]
        stored_paths = state.scratch["stem_paths"]
        for stem_tag, arr in stems.items():
            parts.setdefault(stem_tag, []).append(arr)
            if stem_tag in paths:
                stored_paths[stem_tag] = paths[stem_tag]

    def after_model(self, runner: Any, state: FileState, model: Any) -> None:
        from core.audio_chunking import concat_stems

        parts = state.scratch.get("stem_parts") or {}
        if not (state.chunked and parts):
            return
        final_stems = {
            stem: concat_stems(chunk_parts, overlap_samples=state.ov_samples)
            for stem, chunk_parts in parts.items()
        }
        _write_captured_stems(
            final_stems,
            state.scratch["stem_paths"],
            is_normalization=bool(runner.settings.process.normalization),
            amplification_threshold=self.amp_threshold,
            wav_type_set=resolve_wav_type_set(runner.settings),
            save_format_name=runner.settings.process.save_format.value,
            mp3_bit_set=runner.settings.process.mp3_bitrate,
            flac_bit_set=runner.settings.process.flac_bit_depth,
        )

    def after_file(self, runner: Any, state: FileState) -> None:
        return


class _EnsembleRunHooks:
    """Ensemble member naming, salvage, and combine for :func:`run_models_on_files`."""

    process_kind = "ensemble"

    def __init__(self, ensemble: Ensembler, is_4_stem: bool) -> None:
        self.ensemble = ensemble
        self.export_path = ensemble.ensemble_folder_name
        self.is_4_stem = is_4_stem

    def before_file(self, runner: Any, state: FileState) -> None:
        state.scratch["ensemble_stem_arrays"] = {}
        runner._ensemble_salvage_members = []
        final_naming = runner._naming_for_file(
            state.audio_file,
            export_path=self.export_path,
            file_index=state.file_num,
            file_total=state.total_files,
            ensemble_label=self.ensemble.append_ensemble_label,
            force_ensemble_label=True,
        )
        state.scratch["ensemble_final_base"] = final_naming.track_base

    def export_and_base(
        self, runner: Any, state: FileState, model: Any
    ) -> tuple[str, str]:
        model_label = _model_output_label(model)
        state.callbacks.console(
            f"Ensemble Mode - {model_label} - "
            f"Model {state.progress_ctx['model_num']}/{state.model_count}\n"
        )
        member_naming = runner._ensemble_member_naming_for_file(
            state.audio_file,
            export_path=self.export_path,
            file_index=state.file_num,
            file_total=state.total_files,
            model_label=model_label,
        )
        state.scratch["member_stem_parts"] = {}
        state.scratch["member_paths"] = {}
        state.scratch["last_member_stems"] = {}
        state.scratch["audio_file_base"] = member_naming.track_base
        state.scratch["model_label"] = model_label
        return member_naming.track_base, self.export_path

    def extra_process_data(
        self, runner: Any, state: FileState, model: Any
    ) -> dict:
        return {
            "is_ensemble_master": True,
            "is_4_stem_ensemble": self.is_4_stem,
            "is_save_all_outputs_ensemble": bool(
                runner.settings.ensemble.save_all_outputs
            ),
        }

    def after_chunk(
        self,
        runner: Any,
        state: FileState,
        model: Any,
        stems: dict,
        paths: dict,
        chunked: bool,
    ) -> None:
        scratch = state.scratch
        scratch["last_member_stems"] = stems
        if chunked:
            for stem_tag, arr in stems.items():
                bucket = _ensemble_stem_bucket(stem_tag)
                scratch["member_stem_parts"].setdefault(bucket, []).append(arr)
                if stem_tag in paths:
                    scratch["member_paths"][bucket] = paths[stem_tag]
            return
        for stem_tag, arr in stems.items():
            bucket = _ensemble_stem_bucket(stem_tag)
            scratch["ensemble_stem_arrays"].setdefault(bucket, []).append(arr)
            if stem_tag in paths:
                scratch["member_paths"][bucket] = paths[stem_tag]

    def after_model(self, runner: Any, state: FileState, model: Any) -> None:
        from core.audio_chunking import concat_stems

        scratch = state.scratch
        salvage_arrays: dict = {}
        if state.chunked:
            for stem_tag, parts in scratch["member_stem_parts"].items():
                concat = concat_stems(parts, overlap_samples=state.ov_samples)
                scratch["ensemble_stem_arrays"].setdefault(
                    _ensemble_stem_bucket(stem_tag), []
                ).append(concat)
                salvage_arrays[_ensemble_stem_bucket(stem_tag)] = concat
        else:
            for stem_tag, arr in scratch["last_member_stems"].items():
                salvage_arrays[_ensemble_stem_bucket(stem_tag)] = arr
        runner._ensemble_salvage_members.append(
            {
                "arrays": salvage_arrays,
                "paths": scratch["member_paths"],
                "audio_file_base": scratch["audio_file_base"],
                "model_label": scratch["model_label"],
            }
        )
        state.callbacks.console("\n")

    def after_file(self, runner: Any, state: FileState) -> None:
        callbacks = state.callbacks
        callbacks.console(state.base_text + "Ensembling outputs...\n")
        combine_started = time.perf_counter()
        ensemble_stem_arrays = state.scratch["ensemble_stem_arrays"]
        ensemble_final_base = state.scratch["ensemble_final_base"]
        export_path = self.export_path
        combine_steps: List[tuple] = []
        if self.is_4_stem:
            stem_names = [
                name
                for name, arrs in ensemble_stem_arrays.items()
                if len(arrs) > 1
            ]
            if not stem_names:
                stem_names = _extract_stems(ensemble_final_base, export_path)
            stem_names = _filter_final_ensemble_stems(
                stem_names, str(runner.settings.process.stem_focus or "")
            )
            combine_steps = [
                (output_stem, {"is_4_stem": True}) for output_stem in stem_names
            ]
        else:
            primary_only = runner.settings.process.primary_stem_only
            secondary_only = runner.settings.process.secondary_stem_only
            # ``process.stem_focus`` overrides the positional booleans,
            # resolved against the chosen pair's buckets — never the
            # already-remapped stem_halves labels with a fake count of 2.
            focus_flags = exclusive_flags_for_pair(
                str(runner.settings.process.stem_focus or ""),
                coerce_ensemble_pair(runner.settings.ensemble.main_stem),
            )
            if focus_flags is not None:
                primary_only, secondary_only = focus_flags
            if not secondary_only:
                combine_steps.append((PRIMARY_STEM, {}))
            if not primary_only:
                combine_steps.append((SECONDARY_STEM, {}))
                combine_steps.append((SECONDARY_STEM, {"is_inst_mix": True}))

        combine_total = max(1, len(combine_steps))
        combine_start = state.progress_sink.fraction
        combine_end = state.file_num / max(1, state.total_files)
        for combine_idx, (stem_name, kwargs) in enumerate(combine_steps):
            self.ensemble.ensemble_outputs(
                ensemble_final_base,
                export_path,
                stem_name,
                stem_arrays=ensemble_stem_arrays,
                **kwargs,
            )
            span = max(combine_end - combine_start, 0.0)
            fraction = combine_start + span * ((combine_idx + 1) / combine_total)
            local_step = combine_progress_local_step(combine_idx, combine_total)
            state.progress_sink.fraction = fraction
            total_count = max(1, runner.true_model_count * state.total_files)
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
        engines = import_separate_engines()
        debug_elapsed("worker", "separate engines ready", import_started)

        def body() -> None:
            paths = self._prepare_paths_for_run(input_paths, callbacks)
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
            try:
                amp_threshold = float(
                    self.settings.process.amplification_threshold or 0.0
                )
            except (TypeError, ValueError):
                amp_threshold = 0.0
            run_models_on_files(
                self,
                paths,
                callbacks,
                models,
                engines=engines,
                hooks=_SingleRunHooks(export_path, amp_threshold),
            )

        with_worker_lifecycle(self, callbacks, "_run", body)

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
        engines = import_separate_engines()
        debug_elapsed("worker", "separate engines ready", import_started)

        def body() -> None:
            paths = self._prepare_paths_for_run(input_paths, callbacks)
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
            run_models_on_files(
                self,
                paths,
                callbacks,
                models,
                engines=engines,
                hooks=_EnsembleRunHooks(ensemble, is_4_stem),
            )
            try:
                if os.path.isdir(export_path) and len(os.listdir(export_path)) == 0:
                    shutil.rmtree(export_path)
            except OSError:
                pass

        with_worker_lifecycle(self, callbacks, "_run_ensemble", body)
