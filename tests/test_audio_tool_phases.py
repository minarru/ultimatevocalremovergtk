"""Audio Tools announce real work before its blocking operation begins."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import numpy as np

from bundled.constants import ALIGN_INPUTS, CHANGE_PITCH, MATCH_INPUTS, TIME_STRETCH
from core.audio_tools import AudioToolRunner, AudioTools
from core.job_callbacks import JobCallbacks
from core.processing_phase import ProcessingPhase
from core.settings import Settings


class AudioToolPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.paths = [str(Path(self.directory.name, name)) for name in ('a.wav', 'b.wav')]
        for path in self.paths:
            Path(path).touch()
        self.settings = Settings.defaults()
        self.settings.process.export_path = self.directory.name
        self.phases: list[ProcessingPhase | None] = []
        self.callbacks = JobCallbacks(on_progress=self._progress)

    def _progress(self, fraction: float, **metadata: Any) -> None:
        self.phases.append(metadata.get('phase'))

    def test_runner_announces_operation_before_tool_blocks(self) -> None:
        runner = AudioToolRunner(self.settings)
        tool = Mock(main_export_path=self.directory.name)
        for operation, expected in (
            (CHANGE_PITCH, ProcessingPhase.CHANGING_PITCH),
            (TIME_STRETCH, ProcessingPhase.STRETCHING_TIME),
            (ALIGN_INPUTS, ProcessingPhase.ALIGNING),
            (MATCH_INPUTS, ProcessingPhase.MATCHING),
        ):
            with self.subTest(operation=operation), patch('core.audio_tools.snapshot_worker_file'):
                self.phases.clear()

                def blocking_operation(
                    *args: Any, expected: ProcessingPhase = expected, **kwargs: Any
                ) -> None:
                    self.assertTrue(self.phases)
                    self.assertEqual(self.phases[-1], expected)

                tool.pitch_or_time_shift.side_effect = blocking_operation
                tool.align_inputs.side_effect = blocking_operation
                tool.match_inputs.side_effect = blocking_operation
                if operation in (CHANGE_PITCH, TIME_STRETCH):
                    runner._run_pitch_time(tool, operation, self.paths[:1], self.callbacks)
                else:
                    runner._run_dual(tool, operation, [tuple(self.paths)], self.callbacks)

    def test_worker_announces_finishing_after_tool_and_before_completion(self) -> None:
        runner = AudioToolRunner(self.settings)
        tool = Mock(main_export_path=self.directory.name)
        complete_phases = []
        self.callbacks.on_complete = lambda: complete_phases.append(self.phases[-1])
        with (
            patch('core.audio_tools.AudioTools', return_value=tool),
            patch('core.audio_tools.snapshot_worker_file'),
            patch('core.audio_tools._release_inference_resources'),
        ):
            runner._run(CHANGE_PITCH, self.paths[:1], [], self.callbacks)
        self.assertEqual(complete_phases, [ProcessingPhase.FINISHING])

    def test_pitch_time_phases_cover_decode_dsp_and_actual_write(self) -> None:
        from ml import spec_utils

        for operation, expected, dsp in (
            (CHANGE_PITCH, ProcessingPhase.CHANGING_PITCH, 'pitch_shift'),
            (TIME_STRETCH, ProcessingPhase.STRETCHING_TIME, 'time_stretch'),
        ):
            with self.subTest(operation=operation):
                self.phases.clear()
                tool = AudioTools(self.settings, on_phase=self.phases.append)
                self.observed: list[tuple[str, ProcessingPhase | None]] = []

                def read(*args: Any, **kwargs: Any) -> tuple[np.ndarray, int]:
                    self.observed.append(('read', self.phases[-1]))
                    return np.ones((2, 32)), 44100

                def process(wave: np.ndarray, *args: Any, **kwargs: Any) -> np.ndarray:
                    self.observed.append(('process', self.phases[-1]))
                    return wave

                def write(*args: Any, **kwargs: Any) -> None:
                    self.observed.append(('write', self.phases[-1]))

                with (
                    patch.object(spec_utils.librosa, 'load', side_effect=read),
                    patch.object(spec_utils.pyrb, dsp, side_effect=process),
                    patch.object(spec_utils.sf, 'write', side_effect=write),
                    patch.object(tool, '_save_format'),
                ):
                    tool.pitch_or_time_shift(operation, self.paths[0], 'a')
                self.assertEqual(
                    self.observed,
                    [
                        ('read', ProcessingPhase.READING_AUDIO),
                        ('process', expected),
                        ('process', expected),
                        ('write', ProcessingPhase.SAVING),
                    ],
                )

    def test_manual_and_combine_announce_saving_before_file_write(self) -> None:
        from ml import spec_utils

        for method in ('ensemble_manual', 'combine_audio'):
            with self.subTest(method=method):
                self.phases.clear()
                tool = AudioTools(self.settings, on_phase=self.phases.append)
                self.at_write: list[ProcessingPhase | None] = []
                with (
                    patch.object(
                        spec_utils,
                        'combine_ensemble_waveforms',
                        return_value=(np.zeros((2, 32)), 44100),
                    ),
                    patch.object(spec_utils, 'load_audio', return_value=np.zeros((2, 32))),
                    patch.object(
                        spec_utils.sf,
                        'write',
                        side_effect=lambda *a, **k: self.at_write.append(self.phases[-1]),
                    ),
                    patch.object(tool, '_save_format'),
                ):
                    getattr(tool, method)(self.paths, 'a')
                self.assertIn(ProcessingPhase.COMBINING, self.phases)
                self.assertEqual(self.at_write, [ProcessingPhase.SAVING])

    def test_apollo_reports_loading_decode_restoration_and_save(self) -> None:
        from engines import apollo

        phases: list[ProcessingPhase] = []
        tool = AudioTools(self.settings, apollo_backend_name='test.ckpt', on_phase=phases.append)
        boundaries = []

        def boundary(name: str, value: Any):
            def operation(*args: Any, **kwargs: Any) -> Any:
                boundaries.append((name, phases[-1]))
                return value

            return operation

        with (
            patch(
                'core.gpu_backend.resolve_inference_backend',
                return_value=SimpleNamespace(torch_device='cpu', backend_name='cpu'),
            ),
            patch('core.gpu_backend.clear_torch_cache'),
            patch.object(apollo, 'acquire_apollo_model', side_effect=boundary('model', Mock())),
            patch.object(
                apollo, 'load_audio', side_effect=boundary('read', (np.zeros((2, 32)), 44100))
            ),
            patch.object(
                apollo, 'restore_audio', side_effect=boundary('restore', np.zeros((2, 32)))
            ),
            patch('soundfile.write', side_effect=boundary('write', None)),
            patch.object(tool, '_save_format'),
        ):
            tool.apollo_process(self.paths[0], 'a', {}, {}, Mock())
        self.assertEqual(
            boundaries,
            [
                ('model', ProcessingPhase.LOADING_MODEL),
                ('read', ProcessingPhase.READING_AUDIO),
                ('restore', ProcessingPhase.RESTORING),
                ('write', ProcessingPhase.SAVING),
            ],
        )

    def test_alignment_reports_reading_processing_and_both_writes(self) -> None:
        from ml import spec_utils

        tool = AudioTools(self.settings, on_phase=self.phases.append)
        tool.is_save_align = True
        tool.align_window = []
        tool.align_intro_val = [1]
        tool.db_analysis_val = (0.0, [0.0])
        tool.phase_option = spec_utils.POSITIVE_PHASE
        observed = []

        def read(*args: Any, **kwargs: Any) -> tuple[np.ndarray, int]:
            observed.append(("read", self.phases[-1]))
            return np.ones(32), 8

        def combine(waves: Any) -> np.ndarray:
            observed.append(("align", self.phases[-1]))
            return waves[0]

        with (
            patch.object(spec_utils.librosa, "load", side_effect=read),
            patch.object(spec_utils, "ensemble_wav", side_effect=combine),
            patch.object(
                spec_utils.sf,
                "write",
                side_effect=lambda *a, **k: observed.append(("write", self.phases[-1])),
            ),
            patch.object(tool, "_save_format"),
        ):
            tool.align_inputs((self.paths[0], self.paths[1]), "a", "b", Mock(), Mock())
        self.assertEqual(
            observed,
            [
                ("read", ProcessingPhase.READING_AUDIO),
                ("read", ProcessingPhase.READING_AUDIO),
                ("align", ProcessingPhase.ALIGNING),
                ("write", ProcessingPhase.SAVING),
                ("write", ProcessingPhase.SAVING),
            ],
        )

    def test_matchering_and_format_conversion_have_explicit_phases(self) -> None:
        tool = AudioTools(self.settings, on_phase=self.phases.append)
        observed = []
        match = SimpleNamespace(
            process=lambda **kwargs: observed.append(("match", self.phases[-1])),
            save_audiofile=lambda *args, **kwargs: None,
        )
        with (
            patch.dict("sys.modules", {"matchering": match}),
            patch.object(
                tool,
                "_save_format",
                side_effect=lambda *a: observed.append(("save", self.phases[-1])),
            ),
        ):
            tool.match_inputs((self.paths[0], self.paths[1]), "a", Mock())
        self.assertEqual(
            observed,
            [
                ("match", ProcessingPhase.MATCHING),
                ("save", ProcessingPhase.SAVING),
            ],
        )

    def test_phase_boundary_honors_stop_before_save(self) -> None:
        from ml import spec_utils

        runner = AudioToolRunner(self.settings)
        stopped = []
        completed = []
        self.callbacks.on_stopped = lambda: stopped.append(True)
        self.callbacks.on_complete = lambda: completed.append(True)

        def process(wave: np.ndarray, *args: Any, **kwargs: Any) -> np.ndarray:
            runner.stop()
            return wave

        with (
            patch("core.audio_tools.snapshot_worker_file"),
            patch("core.audio_tools._release_inference_resources"),
            patch.object(spec_utils.librosa, "load", return_value=(np.ones((2, 32)), 44100)),
            patch.object(spec_utils.pyrb, "pitch_shift", side_effect=process),
            patch.object(spec_utils.sf, "write") as write,
        ):
            runner._run(CHANGE_PITCH, self.paths[:1], [], self.callbacks)
        self.assertEqual(stopped, [True])
        self.assertEqual(completed, [])
        write.assert_not_called()
        self.assertNotIn(ProcessingPhase.FINISHING, self.phases)
