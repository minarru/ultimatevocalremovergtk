"""Unit tests for F24 progress-tick helpers (no GTK, no weights)."""
from __future__ import annotations

import unittest
from unittest import mock

from core.progress_ticks import EXTRA_END, HOP_END, InferenceProgress
from vendor.demucs.utils import apply_model_v1, apply_model_v2


class ContinueCounterTests(unittest.TestCase):
    def test_hops_then_match_mix_are_monotonic_and_stay_under_save(self) -> None:
        progress = InferenceProgress()
        hops = [progress.hop(4) for _ in range(4)]
        extras = [progress.extra(3) for _ in range(3)]
        locals_ = hops + extras
        self.assertEqual(hops, sorted(hops))
        self.assertEqual(locals_, sorted(locals_))
        self.assertLessEqual(hops[-1], HOP_END)
        self.assertGreater(extras[0], hops[-1] - 1e-9)
        self.assertLess(extras[-1], 0.90)
        self.assertLessEqual(extras[-1], EXTRA_END)

    def test_denoise_after_hops_continues_extra_span(self) -> None:
        progress = InferenceProgress()
        for _ in range(4):
            progress.hop(4)
        first = progress.extra(2)
        second = progress.extra(2)
        self.assertLessEqual(first, second)
        self.assertGreaterEqual(first, HOP_END)
        self.assertLess(second, 0.90)


class DemucsUnsplitProgressTests(unittest.TestCase):
    def test_v1_non_split_emits_start_and_end(self) -> None:
        import torch

        ticks: list[float] = []

        class _Model:
            samplerate = 8

            def valid_length(self, length: int) -> int:
                return length

            def __call__(self, padded: torch.Tensor) -> torch.Tensor:
                return padded

        mix = torch.zeros(2, 16)
        apply_model_v1(
            _Model(),
            mix,
            shifts=None,
            split=False,
            set_progress_bar=lambda step, it=0: ticks.append(step + it),
        )
        self.assertGreaterEqual(len(ticks), 2)
        self.assertAlmostEqual(ticks[0], 0.1)
        self.assertAlmostEqual(ticks[-1], 0.9)

    def test_v2_non_split_emits_start_and_end(self) -> None:
        import torch

        ticks: list[float] = []

        class _Model:
            samplerate = 8
            sources = ("drums", "bass", "other", "vocals")
            segment_length = 8

            def valid_length(self, length: int) -> int:
                return length

            def __call__(self, padded: torch.Tensor) -> torch.Tensor:
                return padded

        mix = torch.zeros(2, 16)
        apply_model_v2(
            _Model(),
            mix,
            shifts=None,
            split=False,
            set_progress_bar=lambda step, it=0: ticks.append(step + it),
        )
        self.assertGreaterEqual(len(ticks), 2)
        self.assertAlmostEqual(ticks[0], 0.1)
        self.assertAlmostEqual(ticks[-1], 0.9)


class AudioToolProgressTests(unittest.TestCase):
    def test_pitch_time_ticks_file_start(self) -> None:
        from core.audio_tools import AudioToolRunner
        from core.job_runner import JobCallbacks

        seen: list[float] = []
        runner = AudioToolRunner.__new__(AudioToolRunner)
        runner.settings = mock.Mock()
        audio_tool = mock.Mock()
        callbacks = JobCallbacks(on_progress=lambda fraction, **_k: seen.append(fraction))
        with mock.patch("core.audio_tools.check_stopped"), mock.patch(
            "core.audio_tools.snapshot_worker_file"
        ), mock.patch("core.audio_tools.os.path.isfile", return_value=True):
            runner._run_pitch_time(
                audio_tool, "pitch", ["/tmp/a.wav", "/tmp/b.wav"], callbacks
            )
        self.assertIn(0.0, seen)
        self.assertIn(0.5, seen)
        self.assertIn(1.0, seen)
        self.assertLess(seen.index(0.0), seen.index(0.5))

    def test_matchering_ticks_pair_start(self) -> None:
        from bundled.constants import MATCH_INPUTS
        from core.audio_tools import AudioToolRunner
        from core.job_runner import JobCallbacks

        seen: list[float] = []
        runner = AudioToolRunner.__new__(AudioToolRunner)
        runner.settings = mock.Mock()
        audio_tool = mock.Mock()
        callbacks = JobCallbacks(on_progress=lambda fraction, **_k: seen.append(fraction))
        with mock.patch("core.audio_tools.check_stopped"), mock.patch(
            "core.audio_tools.snapshot_worker_file"
        ), mock.patch("core.audio_tools.os.path.isfile", return_value=True):
            runner._run_dual(
                audio_tool,
                MATCH_INPUTS,
                [("/tmp/t.wav", "/tmp/r.wav")],
                callbacks,
            )
        self.assertIn(0.0, seen)
        self.assertIn(1.0, seen)
        self.assertLess(seen.index(0.0), seen.index(1.0))

    def test_manual_ensemble_forwards_on_progress(self) -> None:
        from core.audio_tools import AudioToolRunner
        from core.job_runner import JobCallbacks
        from core.settings import Settings
        from core.types.settings_enums import ManualEnsembleOption

        seen: list[float] = []
        runner = AudioToolRunner.__new__(AudioToolRunner)
        settings = Settings.defaults()
        settings.audio_tools.choose_algorithm = ManualEnsembleOption.COMBINE_INPUTS
        runner.settings = settings
        audio_tool = mock.Mock()
        audio_tool.combine_audio.side_effect = (
            lambda _inputs, _base, on_progress=None: on_progress and on_progress(0.5)
        )
        callbacks = JobCallbacks(on_progress=lambda fraction, **_k: seen.append(fraction))
        with mock.patch("core.audio_tools.os.path.isfile", return_value=True), mock.patch(
            "core.audio_tools.snapshot_worker_file"
        ):
            runner._run_manual_ensemble(
                audio_tool, ["/tmp/a.wav", "/tmp/b.wav"], callbacks
            )
        self.assertIn(0.0, seen)
        self.assertIn(0.5, seen)
        self.assertIn(1.0, seen)


if __name__ == "__main__":
    unittest.main()
