"""Batch file labels through the real runner and shared separation loop."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from core.export_naming import OutputNamingContext
from core.job_callbacks import JobCallbacks
from core.job_plan import PlannedInput
from core.job_runner import JobRunner
from core.settings import Settings


class RunFilePositionTests(unittest.TestCase):
    def test_labels_preserve_batch_position_and_regular_single_file_heading(self) -> None:
        for mode in ("single", "ensemble"):
            for position in (None, (1, 1), (2, 12)):
                for sample in (False, True):
                    with (
                        self.subTest(mode=mode, position=position, sample=sample),
                        tempfile.TemporaryDirectory() as tmp,
                    ):
                        original = str(Path(tmp) / "song.wav")
                        audio = str(Path(tmp) / "sample.wav") if sample else original
                        Path(audio).touch()
                        settings = Settings.defaults()
                        settings.process.export_path = tmp
                        runner = JobRunner(settings)
                        if position is not None:
                            naming = OutputNamingContext(
                                original,
                                "song",
                                "song",
                                tmp,
                                "wav",
                                file_index=position[0],
                                file_total=position[1],
                            )
                            runner._run_planned = (PlannedInput(original, naming, ()),)
                        if sample:
                            runner._run_path_map = {audio: original}
                        model = SimpleNamespace(model_basename="model")
                        runner._run_models = [model] * (2 if mode == "ensemble" else 1)
                        hooks = Mock(process_kind=mode)
                        hooks.export_and_base.return_value = ("song", tmp)
                        hooks.extra_process_data.return_value = {}
                        hooks.after_file.side_effect = lambda _runner, state: (
                            state.set_progress_bar(1)
                        )
                        console: list[str] = []
                        progress = Mock()
                        errors = Mock()
                        with ExitStack() as stack:
                            patches = (
                                patch("core.job_runner.import_separate_engines"),
                                patch.object(
                                    runner, "_prepare_paths_for_run", return_value=[audio]
                                ),
                                patch.object(runner, "_build_all_models"),
                                patch.object(runner, "_set_run_protect_identities"),
                                patch.object(runner, "_ensure_vram_for_job"),
                                patch.object(
                                    runner,
                                    "_count_true_models",
                                    return_value=len(runner._run_models),
                                ),
                                patch.object(runner, "_build_separator"),
                                patch(
                                    "core.job_runner.run_hooks._SingleRunHooks", return_value=hooks
                                ),
                                patch(
                                    "core.job_runner.run_hooks._EnsembleRunHooks",
                                    return_value=hooks,
                                ),
                                patch(
                                    "core.job_runner.Ensembler",
                                    return_value=SimpleNamespace(ensemble_folder_name=tmp),
                                ),
                                patch(
                                    "core.run_loop._decoded_mix_for_process",
                                    return_value=np.zeros((2, 8), dtype=np.float32),
                                ),
                                patch("core.run_loop.display_name_for_model", return_value="model"),
                                patch("core.run_loop.snapshot_worker_file"),
                                patch("core.run_loop.run_separator", return_value={}),
                                patch("core.run_loop._release_inference_resources"),
                                patch("engines.gpu_cache.clear_gpu_cache"),
                            )
                            for patcher in patches:
                                stack.enter_context(patcher)
                            model.process_method = "MDX-Net"
                            model.model_name = "model"
                            model.repo = None
                            runner._run_separation(
                                [original],
                                JobCallbacks(
                                    on_console=console.append,
                                    on_progress=progress,
                                    on_error=errors,
                                ),
                                mode,
                            )
                        errors.assert_not_called()
                        index, total = position or (1, 1)
                        self.assertIn(f"\nFile {index}/{total} — {Path(audio).name}\n", console)
                        ticks = [
                            call
                            for call in progress.call_args_list
                            if call.kwargs.get("local_step") == 1
                        ]
                        self.assertTrue(ticks)
                        self.assertEqual(ticks[-1].args[0], 1.0)
                        self.assertEqual(ticks[-1].kwargs["pass_total"], len(runner._run_models))
                        if total > 1:
                            self.assertIn(f"File {index}/{total}", ticks[-1].kwargs["detail"])
                        state = hooks.after_file.call_args.args[1]
                        self.assertEqual((state.file_num, state.total_files), (1, 1))
