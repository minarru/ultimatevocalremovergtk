"""Framework-agnostic Audio Tools backend.

This is the Tk-free port of ``UVR.py``'s Audio Tools mode (the ``AudioTools``
class plus the ``process_tool_start`` orchestration).
It exposes a small set of pure functions for each tool and an
:class:`AudioToolRunner` that drives them on a ``KThread`` worker, reporting
progress / console / completion through the same :class:`core.JobCallbacks`
contract the separation :class:`~core.JobRunner` uses. The GTK layer marshals
those callbacks onto the main loop (see :mod:`ui.dispatch`).

Every heavy dependency (``librosa`` / ``soundfile`` / ``scipy`` via
``ml.spec_utils``, ``matchering``, ``pyrubberband`` via ``ml.pyrb``,
``pydub`` for non-WAV export, ``kthread``) is imported lazily inside the worker
so this module - and any view that imports it - stays importable on a bare
Python (no torch / ML stack) install. Options are read from a
:class:`~core.settings.Settings` through its flat compatibility accessors.
"""
import os
import time
import typing
from pathlib import Path
from typing import Callable, List, Literal, Optional, Sequence, Tuple

from bundled.constants import (
    ALIGN_INPUTS,
    APOLLO_RESTORE,
    CHANGE_PITCH,
    COMBINE_INPUTS,
    DEFAULT,
    INTRO_MAPPER,
    MANUAL_ENSEMBLE,
    MATCH_INPUTS,
    PHASE_SHIFTS_OPT,
    PROCESS_STOPPED_BY_USER,
    TIME_STRETCH,
    TIME_WINDOW_MAPPER,
    VOLUME_MAPPER,
)

from .audio_io import resolve_wav_type_set, save_format
from .console_text import file_heading, run_summary
from .error_context import snapshot_worker_file
from .export_naming import sanitize_filename_component
from .inference_cleanup import release_inference_memory as _release_inference_resources
from .job_callbacks import JobCallbacks
from .processing_phase import ProcessingPhase
from .run_control import ProcessStopped, check_stopped, pausable_callback
from .settings import Settings
from .settings.coerce import enum_value

#: Tools that operate on a flat list of single input files.
SINGLE_INPUT_TOOLS = (MANUAL_ENSEMBLE, TIME_STRETCH, CHANGE_PITCH, APOLLO_RESTORE)
#: Tools that operate on (file_a, file_b) input pairs.
DUAL_INPUT_TOOLS = (ALIGN_INPUTS, MATCH_INPUTS)


class AudioTools:
    """Per-run configuration + tool implementations (port of ``UVR.AudioTools``).

    Reads every option from the shared :class:`Settings` (instead of Tk
    variables) and exposes the same tool methods that ``process_tool_start``
    dispatches to.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        apollo_backend_name: str | None = None,
        on_phase: Callable[[ProcessingPhase], None] | None = None,
    ):
        self._on_phase = on_phase
        self.settings = settings
        time_stamp = round(time.time())
        process = settings.process
        mdx = settings.mdx
        audio_tools = settings.audio_tools
        self.main_export_path = Path(process.export_path or "")
        self.wav_type_set = resolve_wav_type_set(settings)
        self.is_normalization = bool(process.normalization)
        try:
            self.amplification_threshold = float(
                process.amplification_threshold or 0.0
            )
        except (TypeError, ValueError):
            self.amplification_threshold = 0.0
        self.is_wav_ensemble = bool(settings.ensemble.wav_ensemble)
        self.is_testing_audio = f"{time_stamp} " if process.testing_audio else ""
        self.save_format_sel = process.save_format.value
        self.mp3_bit_set = enum_value(process.mp3_bitrate)
        self.flac_bit_set = enum_value(process.flac_bit_depth)
        self.opus_bit_set = enum_value(process.opus_bitrate)

        # Align-tool options (mapped through the same constants UVR uses).
        self.align_window = TIME_WINDOW_MAPPER[enum_value(audio_tools.time_window)]
        self.align_intro_val = INTRO_MAPPER[enum_value(audio_tools.intro_analysis)]
        self.db_analysis_val = VOLUME_MAPPER[enum_value(audio_tools.db_analysis)]
        self.is_save_align = bool(mdx.is_save_align)
        self.is_match_silence = bool(mdx.is_match_silence)
        self.is_spec_match = bool(mdx.is_spec_match)
        self.phase_option = str(enum_value(mdx.phase_option))
        self.phase_shifts = PHASE_SHIFTS_OPT[enum_value(mdx.phase_shifts)]

        # Apollo restore options. Device selection follows the local CUDA/CPU
        # convention used by separate.py / model_data.py.
        from core import paths

        self.apollo_model = apollo_backend_name
        self.apollo_overlap_val = int(audio_tools.apollo_overlap)
        self.apollo_chunk_val = int(audio_tools.apollo_chunk_size)
        self.apollo_model_location = (
            os.path.join(paths.APOLLO_MODELS_DIR, self.apollo_model)
            if self.apollo_model else ""
        )
        self.use_gpu = bool(process.use_gpu)
        self.is_gpu_conversion = self.use_gpu  # back-compat alias
        self.is_use_directml = bool(process.use_directml)
        from bundled.constants import is_macos

        self.is_macos = is_macos
        device_set = process.device or DEFAULT
        self.device_set = device_set.split(":")[-1].strip() if ":" in device_set else device_set

    def _report_phase(self, phase: ProcessingPhase) -> None:
        if self._on_phase is not None:
            self._on_phase(phase)

    def _operation_phases(
        self, processing: ProcessingPhase,
    ) -> Callable[[Literal["reading", "processing", "saving"]], None]:
        """Translate scientific operation boundaries into presentation identities."""
        phases = {
            "reading": ProcessingPhase.READING_AUDIO,
            "processing": processing,
            "saving": ProcessingPhase.SAVING,
        }

        def report(stage: Literal["reading", "processing", "saving"]) -> None:
            self._report_phase(phases[stage])

        return report

    # -- save_format helper bound to the current settings ----------------------

    def _save_format(self, save_path: str) -> None:
        save_format(
            save_path,
            self.save_format_sel,
            self.mp3_bit_set,
            self.flac_bit_set,
            self.opus_bit_set,
        )

    # -- Manual ensemble -------------------------------------------------------

    def ensemble_manual(
        self,
        audio_inputs: Sequence[str],
        audio_file_base: str,
        on_progress: Callable[[float], None] | None = None,
    ) -> None:
        from ml import spec_utils

        algorithm = self.settings.audio_tools.choose_algorithm
        track = sanitize_filename_component(audio_file_base) or "audio"
        # ``.value``, not ``str()``: the latter yields ``ManualEnsembleOption.MAX_SPEC``.
        algorithm_part = sanitize_filename_component(str(enum_value(algorithm) or ""))
        name = f"{self.is_testing_audio}{track}"
        if algorithm_part:
            name = f"{name} ({algorithm_part})"
        stem_save_path = os.path.join(f"{self.main_export_path}", f"{name}.wav")
        spec_utils.ensemble_inputs(
            list(audio_inputs),
            algorithm,
            self.is_normalization,
            self.wav_type_set,
            stem_save_path,
            is_wave=self.is_wav_ensemble,
            min_peak=self.amplification_threshold,
            on_progress=on_progress,
            on_phase=self._operation_phases(ProcessingPhase.COMBINING),
        )
        self._save_format(stem_save_path)

    def combine_audio(
        self,
        audio_inputs: Sequence[str],
        audio_file_base: str,
        on_progress: Callable[[float], None] | None = None,
    ) -> None:
        from ml import spec_utils

        track = sanitize_filename_component(audio_file_base) or "audio"
        spec_utils.combine_audio(
            list(audio_inputs),
            os.path.join(self.main_export_path, f"{self.is_testing_audio}{track}"),
            self.wav_type_set,
            save_format=self._save_format,
            on_progress=on_progress,
            on_phase=self._operation_phases(ProcessingPhase.COMBINING),
        )

    # -- Time-stretch / pitch shift (port of ``pitch_or_time_shift``) ----------

    def pitch_or_time_shift(self, tool: str, audio_file: str, audio_file_base: str) -> None:
        from ml import spec_utils

        is_pitch = tool == CHANGE_PITCH
        if is_pitch:
            rate = float(self.settings.audio_tools.pitch_rate)
            is_time_correction = bool(
                self.settings.audio_tools.is_time_correction
            )
            file_text = " pitch shifted"
        else:
            rate = float(self.settings.audio_tools.time_stretch_rate)
            is_time_correction = True
            file_text = " time stretched"

        track = sanitize_filename_component(audio_file_base) or "audio"
        save_path = os.path.join(
            self.main_export_path, f"{self.is_testing_audio}{track}{file_text}.wav"
        )
        spec_utils.augment_audio(
            save_path,
            audio_file,
            rate,
            self.is_normalization,
            self.wav_type_set,
            self._save_format,
            is_pitch=is_pitch,
            is_time_correction=is_time_correction,
            min_peak=self.amplification_threshold,
            on_phase=self._operation_phases(
                ProcessingPhase.CHANGING_PITCH if is_pitch else ProcessingPhase.STRETCHING_TIME
            ),
        )

    # -- Align (port of ``AudioTools.align_inputs``) ---------------------------

    def align_inputs(
        self,
        audio_inputs: Tuple[str, str],
        audio_file_base: str,
        audio_file_2_base: str,
        command_text: Callable[[str], None],
        set_progress_bar: Callable[[float, float], None],
    ) -> None:
        from ml import spec_utils

        audio_file_base = f"{self.is_testing_audio}{sanitize_filename_component(audio_file_base) or 'audio'}"
        audio_file_2_base = f"{self.is_testing_audio}{sanitize_filename_component(audio_file_2_base) or 'audio'}"

        aligned_path = os.path.join(f"{self.main_export_path}", f"{audio_file_2_base} (Aligned).wav")
        inverted_path = os.path.join(f"{self.main_export_path}", f"{audio_file_base} (Inverted).wav")

        spec_utils.align_audio(
            audio_inputs[0],
            audio_inputs[1],
            aligned_path,
            inverted_path,
            self.wav_type_set,
            self.is_save_align,
            command_text,
            self._save_format,
            align_window=self.align_window,
            align_intro_val=self.align_intro_val,
            db_analysis=self.db_analysis_val,
            set_progress_bar=set_progress_bar,
            phase_option=self.phase_option,
            phase_shifts=self.phase_shifts,
            is_match_silence=self.is_match_silence,
            is_spec_match=self.is_spec_match,
            on_phase=self._operation_phases(ProcessingPhase.ALIGNING),
        )

    # -- Matchering (port of ``AudioTools.match_inputs``) ----------------------

    def match_inputs(
        self,
        audio_inputs: Tuple[str, str],
        audio_file_base: str,
        command_text: Callable[[str], None],
    ) -> None:
        self._report_phase(ProcessingPhase.MATCHING)
        import matchering as match

        target, reference = audio_inputs[0], audio_inputs[1]
        command_text("Matching audio...\n")
        track = sanitize_filename_component(audio_file_base) or "audio"
        save_path = os.path.join(
            f"{self.main_export_path}",
            f"{self.is_testing_audio}{track} (Matched).wav",
        )
        match.process(
            target=target,
            reference=reference,
            results=[match.save_audiofile(save_path, wav_set=self.wav_type_set)],
        )
        self._report_phase(ProcessingPhase.SAVING)
        self._save_format(save_path)

    # -- Apollo restore (port of ``AudioTools.apollo_process``) ----------------

    def apollo_process(
        self,
        audio_file: str,
        audio_file_base: str,
        extracted_params: dict,
        config: Optional[dict],
        set_progress_bar: Callable[[float, float], None],
    ) -> None:
        if not self.apollo_model_location:
            raise ValueError(
                "A resolved Apollo backend checkpoint is required for inference."
            )
        self._report_phase(ProcessingPhase.LOADING_MODEL)
        import soundfile as sf

        from core.gpu_backend import clear_torch_cache, resolve_inference_backend

        # ``engines.apollo`` pulls in torch; import it lazily so ``core``
        # (and any view importing it) stays torch-free at import time.
        from engines import apollo

        track = sanitize_filename_component(audio_file_base) or "audio"
        save_path = os.path.join(
            self.main_export_path, f"{self.is_testing_audio}{track} restored.wav"
        )

        backend = resolve_inference_backend(
            use_gpu=self.use_gpu,
            device_set=self.device_set or DEFAULT,
            is_use_directml=self.is_use_directml,
            is_macos=self.is_macos,
        )

        restored_audio = apollo.restore_process(
            audio_file,
            self.apollo_model_location,
            self.apollo_overlap_val,
            self.apollo_chunk_val,
            set_progress_bar,
            device=backend.torch_device,
            extracted_params=extracted_params,
            config=config,
            settings=self.settings,
            on_phase=self._report_phase,
        )

        clear_torch_cache(is_macos=self.is_macos, backend_name=backend.backend_name)

        self._report_phase(ProcessingPhase.SAVING)
        sf.write(save_path, restored_audio.T, 44100, subtype=self.wav_type_set)
        self._save_format(save_path)


def _basename_no_ext(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _output_files(path: typing.Any) -> set[str]:
    root = str(path)
    if not os.path.isdir(root):
        return set()
    return {
        os.path.join(folder, name)
        for folder, _dirs, files in os.walk(root)
        for name in files
    }


class AudioToolRunner:
    """Runs an audio tool on a ``KThread`` worker, reporting via callbacks.

    Mirrors ``MainWindow.process_tool_start``: validates inputs, iterates over
    the file list (or dual pairs), writes progress/console updates and a final
    completion. The runner is framework-agnostic; the GTK layer wraps the
    callbacks so they execute on the main loop.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        apollo_backend_name: str | None = None,
    ):
        self.settings = settings
        self.apollo_backend_name = apollo_backend_name
        self._thread = None
        self._is_stopped = False
        self._is_paused = False
        self._active_unit: tuple[str, ...] | None = None
        self._active_before: set[str] = set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        tool: str,
        single_inputs: Sequence[str],
        dual_pairs: Sequence[Tuple[str, str]],
        callbacks: JobCallbacks,
        apollo_params: Optional[dict] = None,
        output_name: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        if self.is_running():
            return
        if tool == APOLLO_RESTORE and not self.apollo_backend_name:
            raise ValueError(
                "A resolved Apollo backend checkpoint is required before start."
            )
        from kthread import KThread

        from .debug_log import current_operation_id, log_event

        worker_operation_id = operation_id or current_operation_id()
        log_event(
            "audio",
            "audio_worker_started",
            operation_id=worker_operation_id,
            tool=tool,
            single_count=len(single_inputs),
            pair_count=len(dual_pairs),
        )
        self._is_stopped = False
        self._is_paused = False
        self._active_unit = None
        self._active_before = set()
        self._apollo_params = apollo_params or {}
        self._output_name = output_name
        self._thread = KThread(
            target=self._run,
            args=(
                tool,
                list(single_inputs),
                [tuple(p) for p in dual_pairs],
                callbacks,
                worker_operation_id,
            ),
        )
        self._thread.start()

    def pause(self) -> None:
        self._is_paused = True

    def unpause(self) -> None:
        self._is_paused = False

    def stop(self, *, force: bool = False) -> None:
        from .debug_log import debug

        debug("audio", f"stop force={force} alive={self.is_running()}")
        self._is_paused = False
        self._is_stopped = True
        if force and self.is_running():
            thread = self._thread
            if thread is not None:
                try:
                    thread.terminate()
                    thread.join(timeout=0.25)
                except Exception:  # best-effort, like UVR's stop
                    pass

    def release_inference_memory(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
        clear_weight_cache: bool = False,
        park_weights: bool = False,
    ) -> None:
        _release_inference_resources(
            self,
            wait_for_stop=wait_for_stop,
            force_if_alive=force_if_alive,
            clear_weight_cache=clear_weight_cache,
            park_weights=park_weights,
        )

    # -- Worker ----------------------------------------------------------------

    def _run(
        self,
        tool: str,
        single_inputs: List[str],
        dual_pairs: List[Tuple[str, str]],
        callbacks: JobCallbacks,
        operation_id: str | None = None,
    ) -> None:
        from .debug_log import log_event, set_operation_id

        set_operation_id(operation_id)
        log_event("audio", "audio_worker_entered", tool=tool)
        stime = time.perf_counter()

        try:
            export_path = self.settings.process.export_path
            if not export_path or not os.path.isdir(export_path):
                raise ValueError("A valid output folder is required.")

            audio_tool = AudioTools(
                self.settings,
                apollo_backend_name=self.apollo_backend_name,
                on_phase=pausable_callback(self, callbacks.report_phase),
            )

            if tool == MANUAL_ENSEMBLE:
                self._run_manual_ensemble(audio_tool, single_inputs, callbacks)
            elif tool in (TIME_STRETCH, CHANGE_PITCH):
                self._run_pitch_time(audio_tool, tool, single_inputs, callbacks)
            elif tool == APOLLO_RESTORE:
                self._run_apollo(audio_tool, single_inputs, callbacks)
            elif tool in (ALIGN_INPUTS, MATCH_INPUTS):
                self._run_dual(audio_tool, tool, dual_pairs, callbacks)
            else:
                raise NotImplementedError(f"audio tool '{tool}' is not implemented")

            callbacks.report_phase(ProcessingPhase.FINISHING)
            callbacks.progress(1.0)
            callbacks.console(run_summary("complete", time.perf_counter() - stime))
            callbacks.complete()
            log_event("audio", "audio_worker_completed", tool=tool)
        except ProcessStopped:
            log_event("audio", "audio_worker_stopped", tool=tool)
            callbacks.console(PROCESS_STOPPED_BY_USER)
            self._finish_active_unit(callbacks, ProcessStopped())
            callbacks.stopped()
            _release_inference_resources(self)
        except Exception as exc:  # surfaced through the callback
            if self._is_stopped:
                log_event("audio", "audio_worker_stopped", tool=tool, stage="error")
                callbacks.console(PROCESS_STOPPED_BY_USER)
                callbacks.stopped()
                _release_inference_resources(self)
                return
            log_event(
                "audio",
                "audio_worker_failed",
                level="error",
                tool=tool,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            self._finish_active_unit(callbacks, exc)
            callbacks.console(run_summary("failed", time.perf_counter() - stime))
            callbacks.error(exc)
            _release_inference_resources(self, park_weights=True)
        else:
            _release_inference_resources(self)
        finally:
            set_operation_id(None)

    def _start_unit(
        self, callbacks: JobCallbacks, paths: typing.Sequence[str], output: typing.Any
    ) -> None:
        self._active_unit = tuple(paths)
        self._active_before = _output_files(output)
        callbacks.input_started(paths)

    def _finish_active_unit(
        self, callbacks: JobCallbacks, error: BaseException | None = None,
        output: typing.Any = None,
    ) -> None:
        if self._active_unit is None:
            return
        generated = (
            sorted(_output_files(output) - self._active_before)
            if output is not None else []
        )
        callbacks.input_finished(self._active_unit, generated, error)
        self._active_unit = None
        self._active_before = set()

    def _run_manual_ensemble(self, audio_tool: typing.Any, inputs: typing.Any, callbacks: typing.Any) -> None:
        if inputs:
            self._start_unit(callbacks, inputs, audio_tool.main_export_path)
        if len(inputs) <= 1:
            raise ValueError("Manual Ensemble needs at least two input files.")
        missing = [p for p in inputs if not os.path.isfile(p)]
        if missing:
            raise ValueError(f'File not found: "{os.path.basename(missing[0])}"')

        audio_file_base = getattr(self, "_output_name", None) or _basename_no_ext(inputs[0])
        snapshot_worker_file(inputs[0])
        callbacks.console(f"\nManual ensemble — {len(inputs)} inputs\n")
        for num, path in enumerate(inputs, start=1):
            callbacks.console(f"  {num}. {os.path.basename(path)}\n")
        callbacks.progress(0.0)

        def on_progress(fraction: float) -> None:
            check_stopped(self)
            callbacks.progress(max(0.0, min(1.0, float(fraction))))

        callbacks.report_phase(ProcessingPhase.COMBINING)
        algorithm = self.settings.audio_tools.choose_algorithm
        if algorithm == COMBINE_INPUTS:
            callbacks.console("Combining inputs...")
            audio_tool.combine_audio(inputs, audio_file_base, on_progress=on_progress)
        else:
            callbacks.console(f"Ensembling inputs ({enum_value(algorithm)})...")
            audio_tool.ensemble_manual(inputs, audio_file_base, on_progress=on_progress)
        callbacks.progress(1.0)
        callbacks.console(" Done!\n")
        self._finish_active_unit(callbacks, output=audio_tool.main_export_path)

    def _run_pitch_time(self, audio_tool: typing.Any, tool: typing.Any, inputs: typing.Any, callbacks: typing.Any) -> None:
        if not inputs:
            raise ValueError("Select at least one input file.")
        total = len(inputs)
        for file_num, audio_file in enumerate(inputs, start=1):
            check_stopped(self)
            snapshot_worker_file(audio_file)
            callbacks.console(file_heading(audio_file, file_num, total))
            if not os.path.isfile(audio_file):
                error = FileNotFoundError(audio_file)
                callbacks.input_started((audio_file,))
                callbacks.input_finished((audio_file,), (), error)
                callbacks.console("Input file was not found; skipping.\n")
                continue
            self._start_unit(callbacks, (audio_file,), audio_tool.main_export_path)
            operation = "Changing pitch" if tool == CHANGE_PITCH else "Stretching time"
            callbacks.console(f"{operation}...")
            callbacks.progress((file_num - 1) / total)
            audio_file_base = _basename_no_ext(audio_file)
            callbacks.report_phase(
                ProcessingPhase.CHANGING_PITCH if tool == CHANGE_PITCH else ProcessingPhase.STRETCHING_TIME
            )
            audio_tool.pitch_or_time_shift(tool, audio_file, audio_file_base)
            callbacks.progress(file_num / total)
            callbacks.console(" Done!\n")
            self._finish_active_unit(callbacks, output=audio_tool.main_export_path)

    def _run_apollo(self, audio_tool: typing.Any, inputs: typing.Any, callbacks: typing.Any) -> None:
        if not inputs:
            raise ValueError("Select at least one input file.")

        extracted_params = self._apollo_params.get("extracted_params")
        config = self._apollo_params.get("config")
        if not extracted_params:
            from bundled.constants import APOLLO_MODEL_FAIL_TEXT

            raise ValueError(APOLLO_MODEL_FAIL_TEXT.strip())

        total = len(inputs)
        for file_num, audio_file in enumerate(inputs, start=1):
            check_stopped(self)
            snapshot_worker_file(audio_file)
            callbacks.console(file_heading(audio_file, file_num, total))
            if not os.path.isfile(audio_file):
                error = FileNotFoundError(audio_file)
                callbacks.input_started((audio_file,))
                callbacks.input_finished((audio_file,), (), error)
                callbacks.console("Input file was not found; skipping.\n")
                continue
            self._start_unit(callbacks, (audio_file,), audio_tool.main_export_path)
            callbacks.console("Restoring audio...")
            audio_file_base = _basename_no_ext(audio_file)

            def set_progress_bar(step: typing.Any, inference_iterations: typing.Any=0, _file_num: typing.Any=file_num):
                fraction = (_file_num - 1 + min(1.0, step + inference_iterations)) / total
                callbacks.progress(fraction)

            callbacks.progress((file_num - 1) / total)
            callbacks.report_phase(ProcessingPhase.LOADING_MODEL)
            audio_tool.apollo_process(
                audio_file,
                audio_file_base,
                extracted_params,
                config,
                pausable_callback(self, set_progress_bar),
            )
            callbacks.progress(file_num / total)
            callbacks.console(" Done!\n")
            self._finish_active_unit(callbacks, output=audio_tool.main_export_path)

    def _run_dual(self, audio_tool: typing.Any, tool: typing.Any, dual_pairs: typing.Any, callbacks: typing.Any) -> None:
        if not dual_pairs:
            raise ValueError("Provide at least one input pair.")
        total = len(dual_pairs)
        text_labels = ("File 1", "File 2") if tool == ALIGN_INPUTS else ("Target", "Reference")

        for file_num, pair in enumerate(dual_pairs, start=1):
            check_stopped(self)
            file_one, file_two = pair[0], pair[1]
            snapshot_worker_file(file_one)
            callbacks.console(
                f"\nPair {file_num}/{total}\n"
                f"{text_labels[0]}: {os.path.basename(file_one)}\n"
                f"{text_labels[1]}: {os.path.basename(file_two)}\n"
            )

            if not os.path.isfile(file_one) or not os.path.isfile(file_two):
                error = FileNotFoundError(file_one if not os.path.isfile(file_one) else file_two)
                callbacks.input_started((file_one, file_two))
                callbacks.input_finished((file_one, file_two), (), error)
                callbacks.console("One or both files were not found; skipping.\n")
                continue
            if file_one == file_two:
                error = ValueError("input pair uses the same file twice")
                callbacks.input_started((file_one, file_two))
                callbacks.input_finished((file_one, file_two), (), error)
                callbacks.console(f"{text_labels[0]} & {text_labels[1]} are the same; skipping.\n")
                continue

            self._start_unit(
                callbacks, (file_one, file_two), audio_tool.main_export_path
            )

            command_text = pausable_callback(self, callbacks.console)

            def set_progress_bar(step: typing.Any, inference_iterations: typing.Any=0, _file_num: typing.Any=file_num):
                fraction = (_file_num - 1 + min(1.0, step + inference_iterations)) / total
                callbacks.progress(fraction)

            audio_file_base = _basename_no_ext(file_one)
            audio_file_2_base = _basename_no_ext(file_two)

            callbacks.progress((file_num - 1) / total)
            callbacks.report_phase(
                ProcessingPhase.MATCHING if tool == MATCH_INPUTS else ProcessingPhase.ALIGNING
            )
            if tool == MATCH_INPUTS:
                audio_tool.match_inputs(pair, audio_file_base, command_text)
            else:
                command_text("Aligning audio...\n")
                audio_tool.align_inputs(
                    pair,
                    audio_file_base,
                    audio_file_2_base,
                    command_text,
                    pausable_callback(self, set_progress_bar),
                )
            callbacks.progress(file_num / total)
            callbacks.console("Done!\n")
            self._finish_active_unit(callbacks, output=audio_tool.main_export_path)
