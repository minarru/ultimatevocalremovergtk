from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.export_naming import OutputNamingContext
from core.job_plan import PlannedInput
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

    def test_ensemble_member_naming_ignores_planned(self) -> None:
        """PlannedInput.naming is final-only; members keep force_model_label."""
        settings = Settings.defaults()
        settings.process.export_path = "/stage"
        settings.process.add_model_name = False
        runner = JobRunner(settings)
        planned = PlannedInput(
            path="/in/song.wav",
            naming=OutputNamingContext(
                input_path="/in/song.wav",
                track="song",
                track_base="1-song Curated",
                export_directory="/out",
                extension="wav",
                file_index=1,
                file_total=2,
                ensemble_label="Curated",
            ),
            outputs=(),
        )
        runner._run_planned = (planned,)
        runner._run_output_root = "/out"

        final = runner._naming_for_file(
            "/in/song.wav",
            export_path="/tmp/ensemble",
            file_index=1,
            file_total=2,
            ensemble_label="Curated",
            force_ensemble_label=True,
        )
        self.assertEqual(final.track_base, "1-song Curated")

        with patch.object(runner, "_naming_for_file") as naming_for_file:
            member = runner._ensemble_member_naming_for_file(
                "/in/song.wav",
                export_path="/tmp/ensemble",
                file_index=1,
                file_total=2,
                model_label="ModelX",
            )
        naming_for_file.assert_not_called()
        self.assertIn("ModelX", member.track_base)
        self.assertNotEqual(member.track_base, planned.naming.track_base)


if __name__ == "__main__":
    unittest.main()
