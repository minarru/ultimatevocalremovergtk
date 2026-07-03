"""Framework-agnostic Audio Tools backend.

This is the Tk-free port of ``UVR.py``'s Audio Tools mode (the ``AudioTools``
and manual-``Ensembler`` classes plus the ``process_tool_start`` orchestration).
It exposes a small set of pure functions for each tool and an
:class:`AudioToolRunner` that drives them on a ``KThread`` worker, reporting
progress / console / completion through the same :class:`uvr_core.JobCallbacks`
contract the separation :class:`~uvr_core.JobRunner` uses. The GTK layer marshals
those callbacks onto the main loop (see :mod:`uvr_gtk.dispatch`).

Every heavy dependency (``librosa`` / ``soundfile`` / ``scipy`` via
``lib_v5.spec_utils``, ``matchering``, ``pyrubberband`` via ``lib_v5.pyrb``,
``pydub`` for non-WAV export, ``kthread``) is imported lazily inside the worker
so this module - and any view that imports it - stays importable on a bare
Python (no torch / ML stack) install. Options are read from a
:class:`~uvr_core.settings.SettingsModel` using the exact ``DEFAULT_DATA`` keys.
"""

import os
import time
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from data.constants import (
    ALIGN_INPUTS,
    APOLLO_RESTORE,
    CHANGE_PITCH,
    COMBINE_INPUTS,
    DEFAULT,
    INTRO_MAPPER,
    MANUAL_ENSEMBLE,
    MATCH_INPUTS,
    PHASE_SHIFTS_OPT,
    PITCH_TEXT,
    PROCESS_STOPPED_BY_USER,
    TIME_STRETCH,
    TIME_TEXT,
    TIME_WINDOW_MAPPER,
    VOLUME_MAPPER,
)

from .audio_io import resolve_wav_type_set, save_format
from .job_runner import JobCallbacks
from .run_control import ProcessStopped, check_stopped, pausable_callback
from .inference_cleanup import release_inference_memory as _release_inference_resources
from .settings import SettingsModel

#: Tools that operate on a flat list of single input files.
SINGLE_INPUT_TOOLS = (MANUAL_ENSEMBLE, TIME_STRETCH, CHANGE_PITCH, APOLLO_RESTORE)
#: Tools that operate on (file_a, file_b) input pairs.
DUAL_INPUT_TOOLS = (ALIGN_INPUTS, MATCH_INPUTS)


class AudioTools:
    """Per-run configuration + tool implementations (port of ``UVR.AudioTools``).

    Reads every option from the shared :class:`SettingsModel` (instead of Tk
    variables) and exposes the same tool methods that ``process_tool_start``
    dispatches to.
    """

    def __init__(self, settings: SettingsModel):
        self.settings = settings
        time_stamp = round(time.time())
        self.main_export_path = Path(settings.get("export_path") or "")
        self.wav_type_set = resolve_wav_type_set(settings)
        self.is_normalization = bool(settings.get("is_normalization"))
        self.is_wav_ensemble = bool(settings.get("is_wav_ensemble"))
        self.is_testing_audio = f"{time_stamp}_" if settings.get("is_testing_audio") else ""
        self.save_format_sel = settings.get("save_format")
        self.mp3_bit_set = settings.get("mp3_bit_set")

        # Align-tool options (mapped through the same constants UVR uses).
        self.align_window = TIME_WINDOW_MAPPER[settings.get("time_window")]
        self.align_intro_val = INTRO_MAPPER[settings.get("intro_analysis")]
        self.db_analysis_val = VOLUME_MAPPER[settings.get("db_analysis")]
        self.is_save_align = bool(settings.get("is_save_align"))
        self.is_match_silence = bool(settings.get("is_match_silence"))
        self.is_spec_match = bool(settings.get("is_spec_match"))
        self.phase_option = settings.get("phase_option")
        self.phase_shifts = PHASE_SHIFTS_OPT[settings.get("phase_shifts")]

        # Apollo restore options. Device selection follows the local CUDA/CPU
        # convention used by separate.py / model_data.py (no DirectML).
        from uvr_core import paths

        self.apollo_model = settings.get("apollo_model")
        self.apollo_overlap_val = int(settings.get("apollo_overlap"))
        self.apollo_chunk_val = int(settings.get("apollo_chunk_size"))
        self.apollo_model_location = os.path.join(paths.APOLLO_MODELS_DIR, self.apollo_model or "")
        self.is_gpu_conversion = 0 if settings.get("is_gpu_conversion") else -1
        device_set = settings.get("device_set") or DEFAULT
        self.device_set = device_set.split(":")[-1].strip() if ":" in device_set else device_set

    # -- save_format helper bound to the current settings ----------------------

    def _save_format(self, save_path: str) -> None:
        save_format(save_path, self.save_format_sel, self.mp3_bit_set)

    # -- Manual ensemble (port of ``Ensembler.ensemble_manual_process``) -------

    def ensemble_manual(self, audio_inputs: Sequence[str], audio_file_base: str) -> None:
        from lib_v5 import spec_utils

        algorithm = self.settings.get("choose_algorithm")
        algorithm_text = f"_({algorithm})"
        stem_save_path = os.path.join(
            f"{self.main_export_path}",
            f"{self.is_testing_audio}{audio_file_base}{algorithm_text}.wav",
        )
        spec_utils.ensemble_inputs(
            list(audio_inputs),
            algorithm,
            self.is_normalization,
            self.wav_type_set,
            stem_save_path,
            is_wave=self.is_wav_ensemble,
        )
        self._save_format(stem_save_path)

    def combine_audio(self, audio_inputs: Sequence[str], audio_file_base: str) -> None:
        from lib_v5 import spec_utils

        spec_utils.combine_audio(
            list(audio_inputs),
            os.path.join(self.main_export_path, f"{self.is_testing_audio}{audio_file_base}"),
            self.wav_type_set,
            save_format=self._save_format,
        )

    # -- Time-stretch / pitch shift (port of ``pitch_or_time_shift``) ----------

    def pitch_or_time_shift(self, tool: str, audio_file: str, audio_file_base: str) -> None:
        from lib_v5 import spec_utils

        is_pitch = tool == CHANGE_PITCH
        if is_pitch:
            rate = float(self.settings.get("pitch_rate"))
            is_time_correction = bool(self.settings.get("is_time_correction"))
            file_text = PITCH_TEXT
        else:
            rate = float(self.settings.get("time_stretch_rate"))
            is_time_correction = True
            file_text = TIME_TEXT

        save_path = os.path.join(
            self.main_export_path, f"{self.is_testing_audio}{audio_file_base}{file_text}.wav"
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
        from lib_v5 import spec_utils

        audio_file_base = f"{self.is_testing_audio}{audio_file_base}"
        audio_file_2_base = f"{self.is_testing_audio}{audio_file_2_base}"

        aligned_path = os.path.join(f"{self.main_export_path}", f"{audio_file_2_base}_(Aligned).wav")
        inverted_path = os.path.join(f"{self.main_export_path}", f"{audio_file_base}_(Inverted).wav")

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
        )

    # -- Matchering (port of ``AudioTools.match_inputs``) ----------------------

    def match_inputs(
        self,
        audio_inputs: Tuple[str, str],
        audio_file_base: str,
        command_text: Callable[[str], None],
    ) -> None:
        import matchering as match

        target, reference = audio_inputs[0], audio_inputs[1]
        command_text("Processing... ")
        save_path = os.path.join(
            f"{self.main_export_path}",
            f"{self.is_testing_audio}{audio_file_base}_(Matched).wav",
        )
        match.process(
            target=target,
            reference=reference,
            results=[match.save_audiofile(save_path, wav_set=self.wav_type_set)],
        )
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
        import soundfile as sf

        # ``apollo_inference`` pulls in torch; import it lazily so ``uvr_core``
        # (and any view importing it) stays torch-free at import time.
        from lib_v5 import apollo_inference

        save_path = os.path.join(
            self.main_export_path, f"{self.is_testing_audio}{audio_file_base}_restored.wav"
        )

        restored_audio = apollo_inference.restore_process(
            audio_file,
            self.apollo_model_location,
            self.apollo_overlap_val,
            self.apollo_chunk_val,
            set_progress_bar,
            self.is_gpu_conversion,
            self.device_set,
            extracted_params,
            config,
        )

        sf.write(save_path, restored_audio.T, 44100, subtype=self.wav_type_set)
        self._save_format(save_path)


def _basename_no_ext(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


class AudioToolRunner:
    """Runs an audio tool on a ``KThread`` worker, reporting via callbacks.

    Mirrors ``MainWindow.process_tool_start``: validates inputs, iterates over
    the file list (or dual pairs), writes progress/console updates and a final
    completion. The runner is framework-agnostic; the GTK layer wraps the
    callbacks so they execute on the main loop.
    """

    def __init__(self, settings: SettingsModel):
        self.settings = settings
        self._thread = None
        self._is_stopped = False
        self._is_paused = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        tool: str,
        single_inputs: Sequence[str],
        dual_pairs: Sequence[Tuple[str, str]],
        callbacks: JobCallbacks,
        apollo_params: Optional[dict] = None,
    ) -> None:
        if self.is_running():
            return
        from kthread import KThread

        self._is_stopped = False
        self._is_paused = False
        self._apollo_params = apollo_params or {}
        self._thread = KThread(
            target=self._run,
            args=(tool, list(single_inputs), [tuple(p) for p in dual_pairs], callbacks),
        )
        self._thread.start()

    def pause(self) -> None:
        self._is_paused = True

    def unpause(self) -> None:
        self._is_paused = False

    def stop(self, *, force: bool = False) -> None:
        self._is_paused = False
        self._is_stopped = True
        if force and self.is_running():
            thread = self._thread
            if thread is not None:
                try:
                    thread.terminate()
                except Exception:  # noqa: BLE001 - best-effort, like UVR's stop
                    pass

    def release_inference_memory(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
    ) -> None:
        _release_inference_resources(
            self,
            wait_for_stop=wait_for_stop,
            force_if_alive=force_if_alive,
        )

    # -- Worker ----------------------------------------------------------------

    def _run(
        self,
        tool: str,
        single_inputs: List[str],
        dual_pairs: List[Tuple[str, str]],
        callbacks: JobCallbacks,
    ) -> None:
        stime = time.perf_counter()
        time_elapsed = lambda: f'Time Elapsed: {time.strftime("%H:%M:%S", time.gmtime(int(time.perf_counter() - stime)))}'

        try:
            export_path = self.settings.get("export_path")
            if not export_path or not os.path.isdir(export_path):
                raise ValueError("A valid output folder is required.")

            audio_tool = AudioTools(self.settings)

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

            callbacks.progress(1.0)
            callbacks.console(f"\nProcess complete\n{time_elapsed()}\n")
            callbacks.complete()
        except ProcessStopped:
            callbacks.console(PROCESS_STOPPED_BY_USER)
            callbacks.stopped()
        except Exception as exc:  # noqa: BLE001 - surfaced through the callback
            if self._is_stopped:
                callbacks.console(PROCESS_STOPPED_BY_USER)
                callbacks.stopped()
                return
            callbacks.console(f"\nProcess failed\n{time_elapsed()}\n")
            callbacks.error(exc)
        finally:
            _release_inference_resources(self)

    def _run_manual_ensemble(self, audio_tool, inputs, callbacks) -> None:
        if len(inputs) <= 1:
            raise ValueError("Manual Ensemble needs at least two input files.")
        missing = [p for p in inputs if not os.path.isfile(p)]
        if missing:
            raise ValueError(f'File not found: "{os.path.basename(missing[0])}"')

        audio_file_base = _basename_no_ext(inputs[0])
        for num, path in enumerate(inputs, start=1):
            callbacks.console(f'File {num} "{os.path.basename(path)}"\n')
        callbacks.console("\nProcessing...\n")
        callbacks.progress(0.5)

        algorithm = self.settings.get("choose_algorithm")
        if algorithm == COMBINE_INPUTS:
            audio_tool.combine_audio(inputs, audio_file_base)
        else:
            audio_tool.ensemble_manual(inputs, audio_file_base)
        callbacks.progress(1.0)
        callbacks.console("Done\n")

    def _run_pitch_time(self, audio_tool, tool, inputs, callbacks) -> None:
        if not inputs:
            raise ValueError("Select at least one input file.")
        total = len(inputs)
        for file_num, audio_file in enumerate(inputs, start=1):
            check_stopped(self)
            base_text = f"File {file_num}/{total} "
            if not os.path.isfile(audio_file):
                callbacks.console(f'\n{base_text}"{os.path.basename(audio_file)}" was not found.\n')
                continue
            callbacks.console(f'\n{base_text}"{os.path.basename(audio_file)}".\n')
            callbacks.console(f"{base_text}Processing...\n")
            audio_file_base = _basename_no_ext(audio_file)
            audio_tool.pitch_or_time_shift(tool, audio_file, audio_file_base)
            callbacks.progress(file_num / total)
            callbacks.console(f"{base_text}Done\n")

    def _run_apollo(self, audio_tool, inputs, callbacks) -> None:
        if not inputs:
            raise ValueError("Select at least one input file.")

        extracted_params = self._apollo_params.get("extracted_params")
        config = self._apollo_params.get("config")
        if not extracted_params:
            from data.constants import APOLLO_MODEL_FAIL_TEXT

            raise ValueError(APOLLO_MODEL_FAIL_TEXT.strip())

        total = len(inputs)
        for file_num, audio_file in enumerate(inputs, start=1):
            check_stopped(self)
            base_text = f"File {file_num}/{total} "
            if not os.path.isfile(audio_file):
                callbacks.console(f'\n{base_text}"{os.path.basename(audio_file)}" was not found.\n')
                continue
            callbacks.console(f'\n{base_text}"{os.path.basename(audio_file)}".\n')
            callbacks.console(f"{base_text}Restoring...\n")
            audio_file_base = _basename_no_ext(audio_file)

            def set_progress_bar(step, inference_iterations=0, _file_num=file_num):
                fraction = (_file_num - 1 + min(1.0, step + inference_iterations)) / total
                callbacks.progress(fraction)

            audio_tool.apollo_process(
                audio_file,
                audio_file_base,
                extracted_params,
                config,
                pausable_callback(self, set_progress_bar),
            )
            callbacks.progress(file_num / total)
            callbacks.console(f"{base_text}Done\n")

    def _run_dual(self, audio_tool, tool, dual_pairs, callbacks) -> None:
        if not dual_pairs:
            raise ValueError("Provide at least one input pair.")
        total = len(dual_pairs)
        text_labels = ("File 1", "File 2") if tool == ALIGN_INPUTS else ("Target", "Reference")

        for file_num, pair in enumerate(dual_pairs, start=1):
            check_stopped(self)
            file_one, file_two = pair[0], pair[1]
            base_text = f"Pair {file_num}/{total} "

            if not os.path.isfile(file_one) or not os.path.isfile(file_two):
                callbacks.console(f"\n{base_text}One or both files were not found.\n")
                continue
            if file_one == file_two:
                callbacks.console(f"\n{base_text}{text_labels[0]} & {text_labels[1]} are the same; skipping.\n")
                continue

            callbacks.console(f'\n{base_text}{text_labels[0]}:  "{os.path.basename(file_one)}"\n')
            callbacks.console(f'{base_text}{text_labels[1]}:  "{os.path.basename(file_two)}"\n')

            command_text = pausable_callback(
                self, lambda text, base=base_text: callbacks.console(base + text)
            )

            def set_progress_bar(step, inference_iterations=0, _file_num=file_num):
                fraction = (_file_num - 1 + min(1.0, step + inference_iterations)) / total
                callbacks.progress(fraction)

            audio_file_base = _basename_no_ext(file_one)
            audio_file_2_base = _basename_no_ext(file_two)

            if tool == MATCH_INPUTS:
                audio_tool.match_inputs(pair, audio_file_base, command_text)
            else:
                command_text("Starting...\n")
                audio_tool.align_inputs(
                    pair,
                    audio_file_base,
                    audio_file_2_base,
                    command_text,
                    pausable_callback(self, set_progress_bar),
                )
            callbacks.progress(file_num / total)
            callbacks.console(f"{base_text}Done\n")
