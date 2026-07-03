"""Framework-agnostic separation job runner.

``JobRunner`` reimplements the orchestration in ``MainWindow.process_start`` and
its ``KThread`` worker, but without any Tkinter coupling: progress, console and
completion are delivered through plain callbacks. The runner deliberately knows
nothing about GTK; the ``uvr_gtk`` layer wraps these callbacks with
``GLib.idle_add`` (see :mod:`uvr_gtk.dispatch`) so they run on the main loop.

Supports single-model separation, ensemble runs, sample mode, and secondary /
vocal-splitter / Demucs pre-process machinery. Audio tools live in
:mod:`uvr_core.audio_tools`.
"""

import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from data.constants import (
    CHOOSE_ENSEMBLE_OPTION,
    CHOOSE_STEM_PAIR,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    FOUR_STEM_ENSEMBLE,
    INST_STEM,
    MAX_MIN,
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
from .model_data import (
    ModelData,
    ModelRepository,
    assemble_model_data,
)
from .sample_mode import prepare_input_paths
from .settings import SettingsModel
from .run_control import ProcessStopped, check_stopped, pausable_callback
from .inference_cleanup import (
    clear_source_mapper,
    release_inference_memory as _release_inference_resources,
    release_separator,
)

_MODEL_KEY_BY_METHOD = {
    VR_ARCH_PM: "vr_model",
    MDX_ARCH_TYPE: "mdx_net_model",
    DEMUCS_ARCH_TYPE: "demucs_model",
}


@dataclass
class JobCallbacks:
    """Callbacks invoked from the worker thread.

    ``on_progress`` receives a float in ``[0.0, 1.0]``; ``on_console`` receives
    text chunks; ``on_complete`` fires once on success; ``on_error`` receives the
    raised exception. The GTK layer marshals each of these onto the main loop.
    """

    on_progress: Optional[Callable[[float], None]] = None
    on_console: Optional[Callable[[str], None]] = None
    on_complete: Optional[Callable[[], None]] = None
    on_stopped: Optional[Callable[[], None]] = None
    on_error: Optional[Callable[[BaseException], None]] = None

    def progress(self, fraction: float) -> None:
        if self.on_progress:
            self.on_progress(max(0.0, min(1.0, fraction)))

    def console(self, text: str) -> None:
        if self.on_console:
            self.on_console(text)

    def complete(self) -> None:
        if self.on_complete:
            self.on_complete()

    def stopped(self) -> None:
        if self.on_stopped:
            self.on_stopped()

    def error(self, exc: BaseException) -> None:
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
        self._thread = KThread(
            target=self._run,
            args=(prepare_input_paths(self.settings, input_paths), callbacks),
        )
        self._thread.start()

    def start_ensemble(self, input_paths: Sequence[str], callbacks: JobCallbacks) -> None:
        """Launch the ensemble worker thread explicitly. No-op if already running."""
        if self.is_running():
            return
        from kthread import KThread

        self._is_stopped = False
        self._is_paused = False
        self._thread = KThread(
            target=self._run_ensemble,
            args=(prepare_input_paths(self.settings, input_paths), callbacks),
        )
        self._thread.start()

    def pause(self) -> None:
        """Pause the worker between files/models (e.g. while a confirm dialog is open)."""
        self._is_paused = True

    def unpause(self) -> None:
        self._is_paused = False

    def stop(self, *, force: bool = False) -> None:
        """Request a cooperative stop; only kill the worker thread when ``force``."""
        self._is_paused = False
        self._is_stopped = True
        if force and self.is_running():
            thread = self._thread
            if thread is not None:
                try:
                    thread.terminate()
                except Exception:
                    pass

    def release_inference_memory(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
    ) -> None:
        """Drop cached stems and return GPU memory after a run or halt."""
        _release_inference_resources(
            self,
            wait_for_stop=wait_for_stop,
            force_if_alive=force_if_alive,
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
        model, sources = None, None
        for key, value in mapper.items():
            if model_name in key:
                model, sources = key, value
        return model, sources

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
        """Mirror ``process_start``'s ``true_model_count`` (UVR.py L6742-6744).

        Each activated secondary model adds a second inference pass; Demucs
        4-stem secondaries and the Demucs pre-process model add their own; the
        vocal splitter adds one when active.
        """
        true_model_4_stem_count = sum(
            m.demucs_4_stem_added_count if m.process_method == DEMUCS_ARCH_TYPE else 0 for m in models
        )
        true_model_pre_proc_model_count = sum(2 if m.pre_proc_model_activated else 0 for m in models)
        base = sum(2 if m.is_secondary_model_activated else 1 for m in models)
        return base + true_model_4_stem_count + true_model_pre_proc_model_count + self._determine_voc_split(models)

    def _determine_voc_split(self, models: List[ModelData]) -> int:
        """Approximate ``MainWindow.determine_voc_split``: +1 when an active
        vocal splitter applies to the run."""
        return 1 if any(getattr(m, "is_vocal_split_model_activated", False) for m in models) else 0

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

    def _run_seperator(self, seperator) -> None:
        self._active_separator = seperator
        try:
            seperator.seperate()
        finally:
            release_separator(seperator)
            if self._active_separator is seperator:
                self._active_separator = None

    def _run(self, input_paths: List[str], callbacks: JobCallbacks) -> None:
        from separate import SeperateDemucs, SeperateMDX, SeperateMDXC, SeperateVR, clear_gpu_cache

        stime = time.perf_counter()
        time_elapsed = lambda: f'Time Elapsed: {time.strftime("%H:%M:%S", time.gmtime(int(time.perf_counter() - stime)))}'

        try:
            export_path = self.settings.get("export_path")
            if not export_path:
                raise ValueError("export_path is required")
            models = self.resolve_models()
            self.iteration = 0
            self._build_all_models(models)
            self.true_model_count = self._count_true_models(models)

            total_files = len(input_paths)

            def make_progress(file_num):
                def set_progress_bar(step, inference_iterations=0):
                    total_count = max(1, self.true_model_count * total_files)
                    base = 1.0 / total_count
                    fraction = base * self.iteration - base + base * (step + inference_iterations)
                    callbacks.progress(fraction)
                return set_progress_bar

            for file_num, audio_file in enumerate(input_paths, start=1):
                check_stopped(self)
                self._cached_sources_clear()
                base_text = f"File {file_num}/{total_files} "

                if not os.path.isfile(audio_file):
                    callbacks.console(f'\n{base_text}"{os.path.basename(audio_file)}" was not found.\n')
                    self.iteration += self.true_model_count
                    continue

                set_progress_bar = pausable_callback(
                    self, make_progress(file_num)
                )

                for current_model in models:
                    check_stopped(self)
                    self._process_iteration()
                    write_to_console = pausable_callback(
                        self,
                        lambda text, base_text=base_text: callbacks.console(base_text + text),
                    )

                    audio_file_base = f"{file_num}_{os.path.splitext(os.path.basename(audio_file))[0]}"
                    if self.settings.get("is_add_model_name"):
                        audio_file_base = f"{audio_file_base}_{current_model.model_basename}"

                    model_export_path = export_path
                    if self.settings.get("is_create_model_folder"):
                        model_basename = current_model.model_basename
                        if model_basename:
                            model_export_path = os.path.join(
                                export_path,
                                model_basename,
                                os.path.splitext(os.path.basename(audio_file))[0],
                            )
                            os.makedirs(model_export_path, exist_ok=True)

                    process_data = {
                        "model_data": current_model,
                        "export_path": model_export_path,
                        "audio_file_base": audio_file_base,
                        "audio_file": audio_file,
                        "set_progress_bar": set_progress_bar,
                        "write_to_console": write_to_console,
                        "process_iteration": pausable_callback(self, self._process_iteration),
                        "check_run_control": pausable_callback(self, lambda: check_stopped(self)),
                        "cached_source_callback": self._cached_source_callback,
                        "cached_model_source_holder": self._cached_model_source_holder,
                        "list_all_models": self.all_models,
                        "is_ensemble_master": False,
                        "is_4_stem_ensemble": False,
                    }

                    if current_model.process_method == VR_ARCH_TYPE:
                        seperator = SeperateVR(current_model, process_data)
                    elif current_model.process_method == MDX_ARCH_TYPE:
                        seperator = SeperateMDXC(current_model, process_data) if current_model.is_mdx_c else SeperateMDX(current_model, process_data)
                    elif current_model.process_method == DEMUCS_ARCH_TYPE:
                        seperator = SeperateDemucs(current_model, process_data)
                    else:
                        raise NotImplementedError(f"engine for '{current_model.process_method}' not available")

                    self._run_seperator(seperator)

                clear_gpu_cache()

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

    # -- Ensemble worker --------------------------------------------------------

    def _run_ensemble(self, input_paths: List[str], callbacks: JobCallbacks) -> None:
        """Run every selected ensemble member then combine their outputs.

        Tk-free port of ``process_start``'s ``ENSEMBLE_MODE`` branch: each member
        model is run with ``is_ensemble_master`` so the engines write per-member
        stems into the ensemble temp folder, then :class:`Ensembler` combines
        those stems per the chosen algorithm into the final outputs.
        """
        import shutil

        from separate import SeperateDemucs, SeperateMDX, SeperateMDXC, SeperateVR, clear_gpu_cache

        stime = time.perf_counter()
        time_elapsed = lambda: f'Time Elapsed: {time.strftime("%H:%M:%S", time.gmtime(int(time.perf_counter() - stime)))}'

        try:
            models = assemble_model_data(self.settings, self.repo, arch_type=ENSEMBLE_MODE)
            if len(models) <= 1:
                raise RuntimeError("Select at least two models to run an ensemble")

            ensemble = Ensembler(self.settings)
            export_path = ensemble.ensemble_folder_name
            ensemble_main_stem = self.settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR)
            is_4_stem = ensemble_main_stem in (FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE)

            self.iteration = 0
            self._build_all_models(models)
            self.true_model_count = self._count_true_models(models)

            total_files = len(input_paths)

            def make_progress(file_num):
                def set_progress_bar(step, inference_iterations=0):
                    total_count = max(1, self.true_model_count * total_files)
                    base = 1.0 / total_count
                    fraction = base * self.iteration - base + base * (step + inference_iterations)
                    callbacks.progress(fraction)
                return set_progress_bar

            for file_num, audio_file in enumerate(input_paths, start=1):
                check_stopped(self)
                self._cached_sources_clear()
                base_text = f"File {file_num}/{total_files} "

                if not os.path.isfile(audio_file):
                    callbacks.console(f'\n{base_text}"{os.path.basename(audio_file)}" was not found.\n')
                    self.iteration += self.true_model_count
                    continue

                set_progress_bar = pausable_callback(
                    self, make_progress(file_num)
                )
                audio_file_base = ""
                current_model = None

                for current_model_num, current_model in enumerate(models, start=1):
                    check_stopped(self)
                    self._process_iteration()
                    callbacks.console(
                        f"Ensemble Mode - {current_model.model_basename} - "
                        f"Model {current_model_num}/{len(models)}\n"
                    )
                    write_to_console = pausable_callback(
                        self,
                        lambda text, base_text=base_text: callbacks.console(base_text + text),
                    )

                    audio_file_base = f"{file_num}_{os.path.splitext(os.path.basename(audio_file))[0]}"
                    audio_file_base = f"{audio_file_base}_{current_model.model_basename}"

                    process_data = {
                        "model_data": current_model,
                        "export_path": export_path,
                        "audio_file_base": audio_file_base,
                        "audio_file": audio_file,
                        "set_progress_bar": set_progress_bar,
                        "write_to_console": write_to_console,
                        "process_iteration": pausable_callback(self, self._process_iteration),
                        "check_run_control": pausable_callback(self, lambda: check_stopped(self)),
                        "cached_source_callback": self._cached_source_callback,
                        "cached_model_source_holder": self._cached_model_source_holder,
                        "list_all_models": self.all_models,
                        "is_ensemble_master": True,
                        "is_4_stem_ensemble": is_4_stem,
                    }

                    if current_model.process_method == VR_ARCH_TYPE:
                        seperator = SeperateVR(current_model, process_data)
                    elif current_model.process_method == MDX_ARCH_TYPE:
                        seperator = SeperateMDXC(current_model, process_data) if current_model.is_mdx_c else SeperateMDX(current_model, process_data)
                    elif current_model.process_method == DEMUCS_ARCH_TYPE:
                        seperator = SeperateDemucs(current_model, process_data)
                    else:
                        raise NotImplementedError(f"engine for '{current_model.process_method}' not available")

                    self._run_seperator(seperator)
                    callbacks.console("\n")

                # Combine each member's stems into the final ensemble outputs.
                if current_model is not None:
                    audio_file_base = audio_file_base.replace(f"_{current_model.model_basename}", "")
                callbacks.console(base_text + "Ensembling outputs...\n")

                if is_4_stem:
                    for output_stem in _extract_stems(audio_file_base, export_path):
                        ensemble.ensemble_outputs(audio_file_base, export_path, output_stem, is_4_stem=True)
                else:
                    if not self.settings.get("is_secondary_stem_only"):
                        ensemble.ensemble_outputs(audio_file_base, export_path, PRIMARY_STEM)
                    if not self.settings.get("is_primary_stem_only"):
                        ensemble.ensemble_outputs(audio_file_base, export_path, SECONDARY_STEM)
                        ensemble.ensemble_outputs(audio_file_base, export_path, SECONDARY_STEM, is_inst_mix=True)

                callbacks.console("Done\n")
                clear_gpu_cache()

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
        chosen_ensemble_name = chosen.replace(" ", "_") if chosen and chosen != CHOOSE_ENSEMBLE_OPTION else "Ensembled"
        ensemble_algorithm = settings.get("ensemble_type", MAX_MIN).partition("/")
        ensemble_main_stem_pair = settings.get("ensemble_main_stem", CHOOSE_STEM_PAIR).partition("/")
        time_stamp = round(time.time())

        self.main_export_path = settings.get("export_path")
        self.chosen_ensemble = f"_{chosen_ensemble_name}" if settings.get("is_append_ensemble_name") else ""
        ensemble_folder_root = self.main_export_path if self.is_save_all_outputs_ensemble else paths.ENSEMBLE_TEMP_PATH
        self.ensemble_folder_name = os.path.join(ensemble_folder_root, f"{chosen_ensemble_name}_Outputs_{time_stamp}")
        self.is_testing_audio = f"{time_stamp}_" if settings.get("is_testing_audio") else ""
        self.primary_algorithm = ensemble_algorithm[0]
        self.secondary_algorithm = ensemble_algorithm[2]
        self.ensemble_primary_stem = ensemble_main_stem_pair[0]
        self.ensemble_secondary_stem = ensemble_main_stem_pair[2]
        self.is_normalization = settings.get("is_normalization")
        self.is_wav_ensemble = settings.get("is_wav_ensemble")
        self.wav_type_set = resolve_wav_type_set(settings)
        self.mp3_bit_set = settings.get("mp3_bit_set")
        self.save_format = settings.get("save_format")
        if not is_manual_ensemble:
            os.makedirs(self.ensemble_folder_name, exist_ok=True)

    def ensemble_outputs(self, audio_file_base, export_path, stem, is_4_stem=False, is_inst_mix=False):
        """Combine the per-member outputs for ``stem`` with the chosen algorithm."""
        from lib_v5 import spec_utils
        from separate import save_format as _save_format

        if is_4_stem:
            algorithm = self.settings.get("ensemble_type", MAX_MIN)
            stem_tag = stem
        elif is_inst_mix:
            algorithm = self.secondary_algorithm
            stem_tag = f"{self.ensemble_secondary_stem} {INST_STEM}"
        else:
            algorithm = self.primary_algorithm if stem == PRIMARY_STEM else self.secondary_algorithm
            stem_tag = self.ensemble_primary_stem if stem == PRIMARY_STEM else self.ensemble_secondary_stem

        stem_outputs = self.get_files_to_ensemble(folder=export_path, prefix=audio_file_base, suffix=f"_({stem_tag}).wav")
        audio_file_output = f"{self.is_testing_audio}{audio_file_base}{self.chosen_ensemble}_({stem_tag})"
        stem_save_path = os.path.join(f"{self.main_export_path}", f"{audio_file_output}.wav")

        if len(stem_outputs) > 1:
            spec_utils.ensemble_inputs(
                stem_outputs,
                algorithm,
                self.is_normalization,
                self.wav_type_set,
                stem_save_path,
                is_wave=self.is_wav_ensemble,
            )
            _save_format(stem_save_path, self.save_format, self.mp3_bit_set)

        if self.is_save_all_outputs_ensemble:
            for stem_output in stem_outputs:
                _save_format(stem_output, self.save_format, self.mp3_bit_set)
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
