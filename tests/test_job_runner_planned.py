from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.job_runner import JobRunner
from core.settings import Settings


class JobRunnerPlannedTests(unittest.TestCase):
    def test_start_skips_assemble_when_models_supplied(self) -> None:
        runner = JobRunner(Settings.defaults())
        models = [Mock(name="already-assembled")]
        with patch.object(runner, "resolve_models") as resolve:
            with patch("kthread.KThread") as thread:
                runner.start(
                    ["/in/a.wav"],
                    Mock(),
                    models=models,
                    planned_output_root="/out",
                )
        resolve.assert_not_called()
        self.assertEqual(runner._run_models, models)
        self.assertEqual(runner._run_output_root, "/out")
        thread.assert_called_once()

    def test_reset_clears_run_models_and_planned(self) -> None:
        runner = JobRunner(Settings.defaults())
        runner._run_models = [Mock()]
        runner._run_planned = ()
        runner._run_output_root = "/out"
        runner._reset_run_state()
        self.assertIsNone(runner._run_models)
        self.assertIsNone(runner._run_planned)
        self.assertIsNone(runner._run_output_root)


if __name__ == "__main__":
    unittest.main()
