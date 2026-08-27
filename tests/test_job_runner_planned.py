from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import Mock, patch

from core.export_naming import OutputNamingContext
from core.job_callbacks import JobCallbacks
from core.job_plan import PlannedInput, PlannedOutput
from core.job_runner import JobRunner
from core.settings import Settings
from core.types import ProcessMethod


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
    def test_required_planned_output_must_exist_before_success(self) -> None:
        runner = JobRunner(Settings.defaults())
        planned = PlannedInput(
            path="/in/song.wav",
            naming=OutputNamingContext(
                input_path="/in/song.wav",
                track="song",
                track_base="song",
                export_directory="/out",
                extension="wav",
            ),
            outputs=(PlannedOutput("/out/song (Vocals).wav", "Vocals"),),
        )

        with patch.object(runner, "_run_separation"):
            outcome = runner._run_one_planned(planned, JobCallbacks())

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.outputs, ())
        self.assertIn("required output", outcome.error or "")

    def test_missing_conditional_planned_output_does_not_fail_success(self) -> None:
        runner = JobRunner(Settings.defaults())
        planned = PlannedInput(
            path="/in/song.wav",
            naming=OutputNamingContext(
                input_path="/in/song.wav",
                track="song",
                track_base="song",
                export_directory="/out",
                extension="wav",
            ),
            outputs=(
                PlannedOutput(
                    "/out/song (Optional).wav",
                    "Optional",
                    conditional=True,
                ),
            ),
        )

        with patch.object(runner, "_run_separation"):
            outcome = runner._run_one_planned(planned, JobCallbacks())

        self.assertEqual(outcome.status, "success")
        self.assertEqual(outcome.outputs, ())

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
        self.assertEqual(thread.call_args.kwargs["target"], runner._run_separation)
        self.assertEqual(thread.call_args.kwargs["args"][2], "single")

    def test_start_infers_ensemble_mode_from_settings(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        runner = JobRunner(settings)
        with patch("kthread.KThread") as thread:
            runner.start(["/in/a.wav"], Mock())
        self.assertEqual(thread.call_args.kwargs["target"], runner._run_separation)
        self.assertEqual(thread.call_args.kwargs["args"][2], "ensemble")

    def test_start_planned_requires_output_root(self) -> None:
        runner = JobRunner(Settings.defaults())
        with patch("kthread.KThread") as thread:
            with self.assertRaises(ValueError) as raised:
                runner.start(
                    ["/in/a.wav"],
                    Mock(),
                    planned=(_planned("/in/a.wav", "a"),),
                )
        self.assertIn("planned_output_root", str(raised.exception))
        thread.assert_not_called()
        self.assertIsNone(runner._run_planned)

    def test_start_uses_planned_input_paths(self) -> None:
        runner = JobRunner(Settings.defaults())
        planned = (_planned("/in/song.wav", "1-song Model"),)
        with patch("kthread.KThread") as thread:
            runner.start(
                ["/widget/changed.wav"],
                Mock(),
                planned=planned,
                planned_output_root="/out",
            )
        self.assertEqual(thread.call_args.kwargs["args"][0], ["/in/song.wav"])
        self.assertEqual(runner._run_planned, planned)
        self.assertEqual(runner._run_output_root, "/out")

    def test_legacy_single_runtime_assembles_with_planned_dependencies(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/out"
        runner = JobRunner(settings)
        dependencies = {"mdx.model": Mock(id="mdx:primary")}
        runner._run_model_dependencies = dependencies
        sentinel = RuntimeError("assembly observed")
        with (
            patch("core.job_runner.import_separate_engines"),
            patch.object(runner, "_prepare_paths_for_run", return_value=[]),
            patch.object(runner, "resolve_models", side_effect=sentinel) as resolve,
            patch(
                "core.job_runner.with_worker_lifecycle",
                side_effect=lambda _runner, _callbacks, _label, body: body(),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "assembly observed"):
                runner._run_separation([], Mock(), "single")
        resolve.assert_called_once_with(dependencies)

    def test_legacy_ensemble_runtime_assembles_with_planned_dependencies(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        runner = JobRunner(settings)
        dependencies = {"ensemble.selected_models[0]": Mock(id="mdx:a")}
        runner._run_model_dependencies = dependencies
        sentinel = RuntimeError("assembly observed")
        with (
            patch("core.job_runner.import_separate_engines"),
            patch.object(runner, "_prepare_paths_for_run", return_value=[]),
            patch("core.job_runner.assemble_model", side_effect=sentinel) as assemble,
            patch(
                "core.job_runner.with_worker_lifecycle",
                side_effect=lambda _runner, _callbacks, _label, body: body(),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "assembly observed"):
                runner._run_separation([], Mock(), "ensemble")
        assemble.assert_called_once_with(
            settings,
            runner.repo,
            arch_type="Ensemble Mode",
            model_dependencies=dependencies,
        )

    def test_naming_keeps_model_folder_when_root_is_plan_output(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/out"
        runner = JobRunner(settings)
        planned = PlannedInput(
            path="/in/song.wav",
            naming=OutputNamingContext(
                input_path="/in/song.wav",
                track="song",
                track_base="song Model",
                export_directory="/out/ModelName/song",
                extension="wav",
                file_index=1,
                file_total=1,
            ),
            outputs=(),
        )
        runner._run_planned = (planned,)
        runner._run_output_root = "/out"
        naming = runner._naming_for_file("/in/song.wav", export_path="/out")
        self.assertEqual(naming.track_base, "song Model")
        self.assertEqual(naming.export_directory, "/out/ModelName/song")

    def test_job_runner_has_no_start_ensemble(self) -> None:
        self.assertFalse(hasattr(JobRunner, "start_ensemble"))

    def test_reset_clears_run_models_and_planned(self) -> None:
        runner = JobRunner(Settings.defaults())
        runner._run_models = [Mock()]
        runner._run_model_dependencies = {"mdx.model": Mock()}
        runner._run_planned = ()
        runner._run_output_root = "/out"
        runner._run_path_map = {"/clip": "/in/a.wav"}
        runner._reset_run_state()
        self.assertIsNone(runner._run_models)
        self.assertIsNone(runner._run_model_dependencies)
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

    def test_run_separation_single_reuses_models_without_resolve(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/tmp/out"
        runner = JobRunner(settings)
        runner._run_models = [Mock(name="assembled")]
        with patch("core.job_runner.import_separate_engines"):
            with patch.object(runner, "_prepare_paths_for_run", return_value=[]):
                with patch.object(runner, "resolve_models") as resolve:
                    with patch.object(runner, "_build_all_models"):
                        with patch.object(runner, "_set_run_protect_identities"):
                            with patch.object(runner, "_ensure_vram_for_job"):
                                with patch.object(runner, "_count_true_models", return_value=1):
                                    with patch("core.run_loop._release_inference_resources"):
                                        runner._run_separation([], JobCallbacks(), "single")
        resolve.assert_not_called()

    def test_single_missing_export_path_fails_before_model_resolution(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = ""
        runner = JobRunner(settings)
        errors: list[BaseException] = []

        with (
            patch("core.job_runner.import_separate_engines"),
            patch.object(
                runner,
                "resolve_models",
                side_effect=AssertionError("model resolution must not run"),
            ),
            patch("core.run_loop._release_inference_resources"),
        ):
            runner._run_separation([], JobCallbacks(on_error=errors.append), "single")

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        self.assertEqual(str(errors[0]), "export_path is required")

    def test_run_separation_ensemble_reuses_models_without_assemble(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/tmp/out"
        runner = JobRunner(settings)
        runner._run_models = [Mock(name="m1"), Mock(name="m2")]
        fake_ensemble = Mock()
        fake_ensemble.ensemble_folder_name = "/tmp/ens"
        with patch("core.job_runner.import_separate_engines"):
            with patch.object(runner, "_prepare_paths_for_run", return_value=[]):
                with patch("core.job_runner.assemble_model") as assemble:
                    with patch("core.job_runner.Ensembler", return_value=fake_ensemble):
                        with patch.object(runner, "_build_all_models"):
                            with patch.object(runner, "_set_run_protect_identities"):
                                with patch.object(runner, "_ensure_vram_for_job"):
                                    with patch.object(runner, "_count_true_models", return_value=2):
                                        with patch("core.run_loop._release_inference_resources"):
                                            runner._run_separation([], JobCallbacks(), "ensemble")
        assemble.assert_not_called()

    def test_run_separation_modes_pass_distinct_hooks(self) -> None:
        settings = Settings.defaults()
        settings.process.export_path = "/tmp/out"
        runner = JobRunner(settings)
        runner._run_models = [Mock(name="m1"), Mock(name="m2")]
        captured: list[str] = []
        received_engines: list[bool] = []

        def capture_run(*_args: object, **kwargs: Any) -> None:
            received_engines.append("engines" in kwargs)
            captured.append(kwargs["hooks"].process_kind)

        fake_ensemble = Mock()
        fake_ensemble.ensemble_folder_name = "/tmp/ens"
        with patch("core.job_runner.import_separate_engines"):
            with patch.object(runner, "_prepare_paths_for_run", return_value=[]):
                with patch.object(runner, "_build_all_models"):
                    with patch.object(runner, "_set_run_protect_identities"):
                        with patch.object(runner, "_ensure_vram_for_job"):
                            with patch.object(runner, "_count_true_models", return_value=2):
                                with patch(
                                    "core.job_runner.run_models_on_files",
                                    side_effect=capture_run,
                                ):
                                    with patch("core.run_loop._release_inference_resources"):
                                        runner._run_separation([], JobCallbacks(), "single")
                                        with patch(
                                            "core.job_runner.Ensembler",
                                            return_value=fake_ensemble,
                                        ):
                                            runner._run_separation([], JobCallbacks(), "ensemble")
        self.assertEqual(captured, ["separation", "ensemble"])
        self.assertEqual(received_engines, [False, False])


if __name__ == "__main__":
    unittest.main()
