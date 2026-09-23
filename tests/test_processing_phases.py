"""Explicit operation phases survive progress updates and UI coalescing."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from core.job_callbacks import JobCallbacks
from ui.run_progress import RunProgressPresenter


class ProcessingPhaseTests(unittest.TestCase):
    def test_sample_phase_is_reported_before_clip_preparation(self):
        from types import SimpleNamespace
        from typing import cast

        from core.job_runner import JobRunner
        from core.processing_phase import ProcessingPhase
        from core.settings import Settings

        settings = Settings.defaults()
        settings.process.sample_mode = True
        runner = cast(JobRunner, SimpleNamespace(settings=settings, _run_planned=None))
        seen = []
        callbacks = JobCallbacks(on_progress=lambda fraction, **meta: seen.append(meta))

        def prepare(*args: Any, **kwargs: Any):
            self.assertEqual(seen[-1]["phase"], ProcessingPhase.PREPARING_SAMPLES)
            return ["clip.wav"]

        with patch("core.job_runner.prepare_input_paths", side_effect=prepare):
            self.assertEqual(
                JobRunner._prepare_paths_for_run(runner, ["song.wav"], callbacks), ["clip.wav"]
            )

    def test_phase_transition_preserves_fraction_and_metadata_on_later_ticks(self):
        from core.processing_phase import ProcessingPhase

        seen = []
        callbacks = JobCallbacks(on_progress=lambda fraction, **meta: seen.append((fraction, meta)))
        callbacks.progress(0.42, local_step=0.6, pass_index=2, pass_total=4, detail="File 1/2")
        callbacks.report_phase(ProcessingPhase.DEVERBING)
        self.assertEqual(seen[-1][0], 0.42)
        self.assertEqual(seen[-1][1]["pass_index"], 2)
        self.assertEqual(seen[-1][1]["detail"], "File 1/2")
        self.assertEqual(seen[-1][1]["phase"], "deverbing")
        callbacks.progress(0.45, local_step=0.94)
        self.assertEqual(seen[-1][1]["phase"], "deverbing")

    def test_labels_follow_operation_instead_of_percentage(self):
        from core.processing_phase import ProcessingPhase

        for phase, title in (
            (ProcessingPhase.CHANGING_PITCH, "Changing pitch"),
            (ProcessingPhase.MATCHING, "Matching audio"),
            (ProcessingPhase.SPLITTING_VOCALS, "Splitting vocals"),
            (ProcessingPhase.DEVERBING, "Removing reverb"),
            (ProcessingPhase.BUFFERING, "Collecting outputs"),
            (ProcessingPhase.COMBINING, "Combining outputs"),
            (ProcessingPhase.LOADING_MODEL, "Loading model"),
        ):
            with self.subTest(phase=phase):
                presenter = RunProgressPresenter()
                for index, fraction in enumerate((0.0, 0.95, 1.0)):
                    result = presenter.update(fraction, index + 1, phase=phase)
                    assert result is not None
                    self.assertEqual(result.title, title)
                    self.assertNotIn("Saving stems", result.text)
                presenter.reset(0)
                result = presenter.update(0.0, 4)
                assert result is not None
                self.assertEqual(result.title, "Loading model")

    def test_same_category_phase_change_bypasses_throttle(self):
        from core.processing_phase import ProcessingPhase

        presenter = RunProgressPresenter()
        presenter.update(0.5, 1, phase=ProcessingPhase.SEPARATING)
        result = presenter.update(0.5, 1.001, phase=ProcessingPhase.SPLITTING_VOCALS)
        assert result is not None
        self.assertEqual(result.title, "Splitting vocals")

    @patch("ui.dispatch.GLib.idle_add")
    def test_pending_fraction_does_not_erase_new_phase(self, idle_add: Any):
        from core.processing_phase import ProcessingPhase
        from ui.dispatch import gtk_job_callbacks

        pending = []
        idle_add.side_effect = lambda callback: pending.append(callback) or len(pending)
        presenter = RunProgressPresenter()
        seen = []

        def on_progress(fraction: float, **meta: Any):
            seen.append(presenter.update(fraction, 1, **meta))

        callbacks = gtk_job_callbacks(on_progress=on_progress)
        callbacks.report_phase(ProcessingPhase.RESTORING)
        callbacks.progress(0.96)
        self.assertEqual(len(pending), 1)
        pending.pop()()
        self.assertEqual(seen[-1].title, "Restoring audio")

    def test_inference_to_saving_keeps_the_same_overall_percentage(self):
        from core.processing_phase import ProcessingPhase

        presenter = RunProgressPresenter()
        seen = []

        def receive(fraction: float, **meta: Any):
            seen.append(presenter.update(fraction, len(seen) + 1, **meta))

        callbacks = JobCallbacks(on_progress=receive)
        callbacks.report_phase(ProcessingPhase.SEPARATING)
        callbacks.progress(0.8, local_step=0.8, pass_index=1, pass_total=1)
        callbacks.progress(0.9, local_step=0.9, pass_index=1, pass_total=1)
        callbacks.report_phase(ProcessingPhase.SAVING)
        self.assertEqual([item.fraction for item in seen[1:]], [0.8, 0.9, 0.9])
        self.assertIn("90%", seen[-2].text)
        self.assertNotIn("100%", seen[-2].text)
        self.assertNotIn("~0:00 left", seen[-2].text)

    def test_explicit_combining_keeps_the_existing_time_estimate(self):
        from core.processing_phase import ProcessingPhase
        from core.run_estimate import ProgressEtaTracker

        tracker = ProgressEtaTracker()
        tracker.update(
            0.95,
            90,
            local_step=0.98,
            combine_index=1,
            combine_total=3,
            phase=ProcessingPhase.COMBINING,
        )
        tracker.update(
            0.97,
            105,
            local_step=0.985,
            combine_index=2,
            combine_total=3,
            phase=ProcessingPhase.COMBINING,
        )
        text = tracker.format_text(0.97, 105, now=105)
        self.assertIn("Combining outputs (2/3)", text)
        self.assertIn("~0:30 left", text)
