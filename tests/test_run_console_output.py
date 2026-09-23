"""Readable console streams across separation, ensemble, and Audio Tools."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import numpy as np

from bundled.constants import (
    ALIGN_INPUTS,
    CHANGE_PITCH,
    DONE,
    LOADING_MODEL,
    MATCH_INPUTS,
    TIME_STRETCH,
)
from core.audio_tools import AudioToolRunner
from core.ensembler import Ensembler
from core.job_callbacks import JobCallbacks
from core.run_hooks import _EnsembleRunHooks, _SingleRunHooks
from core.run_loop import FileState, run_models_on_files, with_worker_lifecycle
from core.settings import Settings
from engines.base import SeperateAttributes
from tests.test_run_loop import _Hooks, _model, _runner


class SeparationConsoleTests(unittest.TestCase):
    def test_each_input_has_one_heading_and_phase_fragments_join(self):
        messages: list[str] = []
        runner = _runner()
        runner._build_separator = lambda model, pdata: pdata

        def run_separator(_runner: Any, pdata: Any, **kwargs: Any) -> dict:
            pdata.write_to_console(LOADING_MODEL)
            pdata.write_to_console(DONE, base_text="")
            return {}

        with tempfile.TemporaryDirectory() as directory:
            paths = [str(Path(directory, name)) for name in ("First song.wav", "Second song.flac")]
            for path in paths:
                Path(path).touch()
            with (
                patch("core.run_loop._decoded_mix_for_process", return_value=np.zeros((2, 8))),
                patch("core.run_loop.snapshot_worker_file"),
                patch("core.run_loop.run_separator", side_effect=run_separator),
            ):
                run_models_on_files(
                    runner,
                    paths,
                    JobCallbacks(on_console=messages.append),
                    [_model("model")],
                    hooks=_Hooks(),
                )
        text = "".join(messages)
        self.assertEqual(text.count("File 1/2"), 1)
        self.assertEqual(text.count("File 2/2"), 1)
        self.assertIn("File 1/2 — First song.wav\nLoading model... Done!\n", text)
        self.assertIn("File 2/2 — Second song.flac\nLoading model... Done!\n", text)

    def test_long_file_chunks_have_distinct_headings(self):
        messages: list[str] = []
        runner = _runner()
        runner.settings.process.long_file_chunk_seconds = 1
        runner._build_separator = lambda model, pdata: pdata

        def run_separator(_runner: Any, pdata: Any, **kwargs: Any) -> dict:
            pdata.write_to_console("Running inference...")
            pdata.write_to_console(DONE, base_text="")
            return {}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "Long song.wav")
            path.touch()
            with (
                patch("core.run_loop._estimated_chunk_count", return_value=2),
                patch("core.run_loop._decoded_mix_for_process", return_value=np.zeros((2, 88200))),
                patch("core.run_loop.snapshot_worker_file"),
                patch("core.run_loop.run_separator", side_effect=run_separator),
            ):
                run_models_on_files(
                    runner,
                    [str(path)],
                    JobCallbacks(on_console=messages.append),
                    [_model("model")],
                    hooks=_Hooks(),
                )
        text = "".join(messages)
        self.assertEqual(text.count("File 1/1"), 1)
        self.assertIn("Chunk 1/2\nRunning inference... Done!\n", text)
        self.assertIn("Chunk 2/2\nRunning inference... Done!\n", text)

    def test_auxiliary_model_heading_does_not_join_loading_line(self):
        for role, heading in (
            ("is_vocal_split_model", "Vocal splitter"),
            ("is_pre_proc_model", "Pre-process model"),
            ("is_secondary_model", "Secondary model"),
        ):
            with self.subTest(role=role):
                messages: list[str] = []
                sep = SimpleNamespace(
                    is_vocal_split_model=False,
                    is_pre_proc_model=False,
                    is_secondary_model=False,
                    process_method="MDX-Net",
                    model_display_label="BandSplit PolarFormer — Karaoke · Lambda001",
                    write_to_console=messages.append,
                )
                setattr(sep, role, True)
                SeperateAttributes.start_inference_console_write(cast(SeperateAttributes, sep))
                messages.extend((LOADING_MODEL, DONE))
                text = "".join(messages)
                self.assertIn(f"{heading}: BandSplit PolarFormer — Karaoke · Lambda001\n", text)
                self.assertTrue(text.endswith("\nLoading model... Done!\n"))

    def test_onnx_autocast_note_precedes_the_open_loading_line(self):
        from engines.mdx import SeperateMDX

        messages: list[str] = []
        state = SimpleNamespace(
            primary_model_name=None,
            model_cache_key="model",
            model_display_label="ONNX model",
            start_inference_console_write=lambda: None,
            write_to_console=lambda text, **kwargs: messages.append(text),
            is_mdx_ckpt=False,
            mdx_segment_size=256,
            dim_t=256,
            is_other_gpu=False,
            settings=Settings.defaults(),
            model_path="model.onnx",
            device="cpu",
        )
        # Stop at the weight-loading boundary; no real session/checkpoint is needed
        # to check the order of the user-visible note and loading message.
        with (
            patch("engines.amp_runtime.autocast_enabled", return_value=True),
            patch("engines.model_weight_cache.get_weight_cache"),
            patch(
                "engines.model_weight_cache.weight_cache_key",
                side_effect=RuntimeError("test boundary"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "test boundary"):
                SeperateMDX.seperate(cast(SeperateMDX, state))
        text = "".join(messages)
        self.assertTrue(text.startswith("Note: FP16 autocast"))
        self.assertTrue(text.endswith("\nLoading model..."))

    def test_model_headings_distinguish_ensemble_members(self):
        messages: list[str] = []
        naming = SimpleNamespace(track_base="song", export_directory="/tmp")
        runner = SimpleNamespace(
            _naming_for_file=lambda *a, **k: naming,
            _ensemble_member_naming_for_file=lambda *a, **k: naming,
        )
        state = SimpleNamespace(
            audio_file="song.wav",
            file_num=1,
            total_files=1,
            model_count=2,
            progress_ctx={"model_num": 1},
            scratch={},
            callbacks=JobCallbacks(on_console=messages.append),
        )
        ensemble = SimpleNamespace(ensemble_folder_name="/tmp")
        hooks = _EnsembleRunHooks(cast(Ensembler, ensemble), False)
        for index, name in enumerate(("Model A", "Model B"), start=1):
            state.progress_ctx["model_num"] = index
            hooks.export_and_base(
                runner, cast(FileState, state), SimpleNamespace(model_display_label=name)
            )
            messages.extend((LOADING_MODEL, DONE))
        self.assertEqual(
            "".join(messages),
            "\nModel 1/2 — Model A\nLoading model... Done!\n"
            "\nModel 2/2 — Model B\nLoading model... Done!\n",
        )
        messages.clear()
        _SingleRunHooks("/tmp", 0).export_and_base(
            runner, cast(FileState, state), SimpleNamespace(model_display_label="Model A")
        )
        self.assertEqual("".join(messages), "Model: Model A\n")

    def test_lifecycle_finishes_open_phase_with_separate_compact_result(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                messages: list[str] = []
                callbacks = JobCallbacks(on_console=messages.append)

                def body(callbacks: JobCallbacks = callbacks, fail: bool = fail):
                    callbacks.console("Running inference...")
                    if fail:
                        raise ValueError("inference failed")
                    callbacks.console(DONE)

                with (
                    patch("core.run_loop._release_inference_resources"),
                    patch("core.run_loop.time.perf_counter", side_effect=[100, 356]),
                ):
                    with_worker_lifecycle(
                        SimpleNamespace(_is_stopped=False), callbacks, "test", body
                    )
                text = "".join(messages)
                status = "failed" if fail else "complete"
                self.assertTrue(text.endswith(f"\nProcess {status} · Elapsed: 00:04:16\n"))


class AudioToolsConsoleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = [
            str(Path(self.directory.name, name)) for name in ("Target.wav", "Reference.wav")
        ]
        for path in self.paths:
            Path(path).touch()
        settings = Settings.defaults()
        settings.process.export_path = self.directory.name
        self.runner = AudioToolRunner(settings)
        self.messages: list[str] = []
        self.callbacks = JobCallbacks(on_console=self.messages.append)
        self.tool = Mock(main_export_path=self.directory.name)

    def test_pitch_time_and_restore_have_named_file_groups(self):
        for tool, operation in (
            (CHANGE_PITCH, "Changing pitch"),
            (TIME_STRETCH, "Stretching time"),
            ("restore", "Restoring audio"),
        ):
            with self.subTest(tool=tool), patch("core.audio_tools.snapshot_worker_file"):
                self.messages.clear()
                if tool == "restore":
                    self.runner._apollo_params = {"extracted_params": {"ready": True}, "config": {}}
                    self.runner._run_apollo(self.tool, self.paths, self.callbacks)
                else:
                    self.runner._run_pitch_time(self.tool, tool, self.paths, self.callbacks)
                text = "".join(self.messages)
                self.assertEqual(text.count("File 1/2"), 1)
                self.assertIn(f"File 1/2 — Target.wav\n{operation}... Done!\n", text)
                self.assertIn(f"File 2/2 — Reference.wav\n{operation}... Done!\n", text)

    def test_pairs_keep_roles_and_do_not_prefix_fragments(self):
        self.tool.match_inputs.side_effect = lambda pair, name, console: console(
            "Matching audio...\n"
        )
        self.tool.align_inputs.side_effect = lambda pair, name, second, console, progress: console(
            "Saving inverted track...\n"
        )
        for tool, roles in (
            (MATCH_INPUTS, ("Target", "Reference")),
            (ALIGN_INPUTS, ("File 1", "File 2")),
        ):
            with self.subTest(tool=tool), patch("core.audio_tools.snapshot_worker_file"):
                self.messages.clear()
                self.runner._run_dual(self.tool, tool, [self.paths], self.callbacks)
                text = "".join(self.messages)
                self.assertEqual(text.count("Pair 1/1"), 1)
                self.assertIn(
                    f"Pair 1/1\n{roles[0]}: Target.wav\n{roles[1]}: Reference.wav\n", text
                )
                self.assertTrue(text.endswith("\nDone!\n"))

    def test_manual_ensemble_lists_all_inputs_before_operation(self):
        with patch("core.audio_tools.snapshot_worker_file"):
            self.runner._run_manual_ensemble(self.tool, self.paths, self.callbacks)
        text = "".join(self.messages)
        self.assertIn("Manual ensemble — 2 inputs\n  1. Target.wav\n  2. Reference.wav\n", text)
        self.assertTrue(text.endswith("... Done!\n"))

    def test_audio_worker_uses_same_compact_result(self):
        with (
            patch("core.audio_tools.AudioTools", return_value=self.tool),
            patch("core.audio_tools.snapshot_worker_file"),
            patch("core.audio_tools._release_inference_resources"),
            patch("core.audio_tools.time.perf_counter", side_effect=[100, 356]),
        ):
            self.runner._run(CHANGE_PITCH, self.paths, [], self.callbacks)
        self.assertTrue("".join(self.messages).endswith("\nProcess complete · Elapsed: 00:04:16\n"))

    def test_invalid_inputs_keep_their_heading_and_do_not_claim_done(self):
        missing = str(Path(self.directory.name, "Missing.wav"))
        with patch("core.audio_tools.snapshot_worker_file"):
            self.runner._run_pitch_time(self.tool, CHANGE_PITCH, [missing], self.callbacks)
            self.runner._run_dual(
                self.tool, MATCH_INPUTS, [(missing, self.paths[1])], self.callbacks
            )
            self.runner._run_dual(
                self.tool, ALIGN_INPUTS, [(self.paths[0], self.paths[0])], self.callbacks
            )
        text = "".join(self.messages)
        self.assertIn("File 1/1 — Missing.wav\nInput file was not found", text)
        self.assertIn("Target: Missing.wav\nReference: Reference.wav\nOne or both files", text)
        self.assertIn("File 1: Target.wav\nFile 2: Target.wav\nFile 1 & File 2 are the same", text)
        self.assertNotIn("Done!", text)
