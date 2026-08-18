from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.export_naming import OutputNamingContext
from core.job_plan import PlannedInput
from core.job_runner import JobCallbacks, JobRunner
from core.settings import Settings


def _planned(path: str, track_base: str, export_directory: str = "/out") -> PlannedInput:
    track = track_base.split("-", 1)[-1].split()[0] if "-" in track_base else track_base
    return PlannedInput(
        path=path,
        naming=OutputNamingContext(
            input_path=path,
            track=track,
            track_base=track_base,
            export_directory=export_directory,
            extension="wav",
            file_index=1,
            file_total=1,
        ),
        outputs=(),
    )


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
        runner._run_path_map = {"/clip": "/in/a.wav"}
        runner._reset_run_state()
        self.assertIsNone(runner._run_models)
        self.assertIsNone(runner._run_planned)
        self.assertIsNone(runner._run_output_root)
        self.assertIsNone(runner._run_path_map)

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

    def test_naming_for_file_miss_raises_when_planned(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/stage"
        runner = JobRunner(settings)
        runner._run_planned = (_planned("/in/song.wav", "2-song Model"),)
        runner._run_output_root = "/out"
        with self.assertRaises(StopIteration):
            runner._naming_for_file("/in/other.wav", export_path="/stage")

    def test_naming_for_file_uses_sample_path_map(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/stage"
        runner = JobRunner(settings)
        runner._run_planned = (_planned("/in/song.wav", "2-song Model"),)
        runner._run_output_root = "/out"
        runner._run_path_map = {
            "/cache/song_30s_abc.wav": "/in/song.wav",
        }
        naming = runner._naming_for_file(
            "/cache/song_30s_abc.wav",
            export_path="/stage",
        )
        self.assertEqual(naming.track_base, "2-song Model")
        self.assertEqual(naming.export_directory, "/stage")

    def test_ensemble_member_naming_uses_original_sample_path(self) -> None:
        settings = Settings.defaults()
        runner = JobRunner(settings)
        runner._run_path_map = {
            "/cache/song_30s_abc.wav": "/in/01. Song.wav",
        }
        naming = runner._ensemble_member_naming_for_file(
            "/cache/song_30s_abc.wav",
            export_path="/stage",
            file_index=1,
            file_total=1,
            model_label="ModelX",
        )
        self.assertEqual(naming.track_base, "01. Song ModelX")

    def test_prepare_paths_builds_path_map_when_planned(self) -> None:
        settings = Settings.defaults()
        settings.process.sample_mode = False
        runner = JobRunner(settings)
        runner._run_planned = (_planned("/in/song.wav", "2-song Model"),)
        with patch(
            "core.job_runner.prepare_input_paths",
            return_value=["/cache/song_clip.wav"],
        ):
            prepared = runner._prepare_paths_for_run(["/in/song.wav"], JobCallbacks())
        self.assertEqual(prepared, ["/cache/song_clip.wav"])
        self.assertEqual(
            runner._run_path_map,
            {"/cache/song_clip.wav": "/in/song.wav"},
        )

    def test_run_reuses_models_without_resolve(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/tmp/out"
        runner = JobRunner(settings)
        runner._run_models = [Mock(name="assembled")]
        engines = (Mock(), Mock(), Mock(), Mock(), Mock())
        with patch("core.job_runner.import_separate_engines", return_value=engines):
            with patch.object(runner, "_prepare_paths_for_run", return_value=[]):
                with patch.object(runner, "resolve_models") as resolve:
                    with patch.object(runner, "_build_all_models"):
                        with patch.object(runner, "_set_run_protect_identities"):
                            with patch.object(runner, "_ensure_vram_for_job"):
                                with patch.object(
                                    runner, "_count_true_models", return_value=1
                                ):
                                    with patch(
                                        "core.job_runner._release_inference_resources"
                                    ):
                                        runner._run([], JobCallbacks())
        resolve.assert_not_called()

    def test_run_ensemble_reuses_models_without_assemble(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/tmp/out"
        runner = JobRunner(settings)
        runner._run_models = [Mock(name="m1"), Mock(name="m2")]
        engines = (Mock(), Mock(), Mock(), Mock(), Mock())
        fake_ensemble = Mock()
        fake_ensemble.ensemble_folder_name = "/tmp/ens"
        with patch("core.job_runner.import_separate_engines", return_value=engines):
            with patch.object(runner, "_prepare_paths_for_run", return_value=[]):
                with patch("core.job_runner.assemble_model") as assemble:
                    with patch("core.job_runner.Ensembler", return_value=fake_ensemble):
                        with patch.object(runner, "_build_all_models"):
                            with patch.object(runner, "_set_run_protect_identities"):
                                with patch.object(runner, "_ensure_vram_for_job"):
                                    with patch.object(
                                        runner, "_count_true_models", return_value=2
                                    ):
                                        with patch(
                                            "core.job_runner._release_inference_resources"
                                        ):
                                            runner._run_ensemble([], JobCallbacks())
        assemble.assert_not_called()


if __name__ == "__main__":
    unittest.main()
