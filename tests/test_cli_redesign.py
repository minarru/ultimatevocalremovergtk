from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from typing import Any
from unittest.mock import Mock, patch

from types import SimpleNamespace

from cli.execution import (
    BatchOutcome, preflight_collisions, run_batch, run_runner_cli, run_separation_cli,
    write_manifest,
)
from core.export_naming import OutputNamingContext, format_stem_basename
from core.input_discovery import discover_inputs
from core.job_plan import PlannedInput, PlannedOutput
from cli.job import ResolvedJob, _device_override
from cli.profiles import LoadedProfile, load_profile, save_profile
from cli.replay import _flat_settings
from core.blocking_runner import RunResult
from core.job_runner import InputOutcome, JobCallbacks, JobRunner
from core.settings import Settings


def _planned_input(
    path: str,
    output: str,
    track_base: str,
    stems: tuple[str, ...] = ("Vocals",),
) -> PlannedInput:
    track = os.path.splitext(os.path.basename(path))[0]
    naming = OutputNamingContext(
        input_path=path,
        track=track,
        track_base=track_base,
        export_directory=output,
        extension="wav",
    )
    outputs = tuple(
        PlannedOutput(
            os.path.join(output, f"{format_stem_basename(track_base, stem)}.wav"),
            stem,
        )
        for stem in stems
    )
    return PlannedInput(path, naming, outputs)


class InputDiscoveryTests(unittest.TestCase):
    def test_directory_recursion_filters_sorts_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "nested"))
            for name in ("b.wav", "a.mp3", "ignore.txt"):
                open(os.path.join(root, name), "wb").close()
            open(os.path.join(root, "nested", "c.wav"), "wb").close()
            found = discover_inputs([root, os.path.join(root, "a.mp3")], recursive=True)
        self.assertEqual([os.path.basename(path) for path in found], ["a.mp3", "b.wav", "c.wav"])

    def test_empty_directory_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "no matching"):
                discover_inputs([root])


class ProfileTests(unittest.TestCase):
    def test_default_profile_does_not_load_gui(self) -> None:
        with patch("core.settings.Settings.load") as loader:
            settings, profile = load_profile(None)
        self.assertFalse(loader.called)
        self.assertEqual(profile.source, "built-in")
        self.assertEqual(settings, Settings.defaults())

    def test_sparse_profile_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as root, patch("cli.profiles.PROFILE_DIR", root):
            saved = LoadedProfile(
                "fast", "profile", model="mdx:a",
                settings={"process.normalization": True},
            )
            save_profile(saved)
            settings, loaded = load_profile("fast")
        self.assertEqual(loaded.model, "mdx:a")
        self.assertTrue(settings.process.normalization)
        self.assertFalse(settings.process.match_mix_level)

    def test_profile_preserves_list_settings_for_manifest_replay(self) -> None:
        with tempfile.TemporaryDirectory() as root, patch("cli.profiles.PROFILE_DIR", root):
            saved = LoadedProfile(
                "stems", "profile", settings={"mdx.stems_selected": ["Vocals", "Drums"]}
            )
            save_profile(saved)
            settings, _loaded = load_profile("stems")
        self.assertEqual(settings.mdx.stems_selected, ["Vocals", "Drums"])

    def test_manifest_flattening_retains_lists_but_not_internal_maps(self) -> None:
        values = _flat_settings({
            "mdx": {"stems_selected": ["Vocals"]},
            "process": {"model_hash_table": {"x": "y"}},
        })
        self.assertEqual(values["mdx.stems_selected"], ["Vocals"])
        self.assertNotIn("process.model_hash_table", values)

    def test_gui_profile_does_not_double_prefix_canonical_ids(self) -> None:
        settings = Settings.defaults()
        settings.process.method = settings.process.method  # keep
        from core.types import ProcessMethod
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:UVR-MDX-NET-Inst_HQ_4"
        with patch("cli.profiles.Settings.load", return_value=settings):
            _loaded, profile = load_profile("gui")
        self.assertEqual(profile.model, "mdx:UVR-MDX-NET-Inst_HQ_4")

    def test_gui_profile_prefixes_legacy_display_names(self) -> None:
        settings = Settings.defaults()
        from core.types import ProcessMethod
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "UVR-MDX-NET-Inst_HQ_4"
        with patch("cli.profiles.Settings.load", return_value=settings):
            _loaded, profile = load_profile("gui")
        self.assertEqual(profile.model, "mdx:UVR-MDX-NET-Inst_HQ_4")

    def test_flatten_keeps_list_settings(self) -> None:
        from cli.profiles import _flatten_settings
        settings = Settings.defaults()
        settings.mdx.stems_selected = ["Vocals", "Drums"]
        flat = _flatten_settings(settings)
        self.assertEqual(flat["mdx.stems_selected"], ["Vocals", "Drums"])

    def test_canonicalize_primary_resolves_with_family_exact(self) -> None:
        from cli.job import _canonicalize_model_references
        from core.model_identity import ModelRecord
        from core.types import ProcessMethod

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "Model A"
        record = ModelRecord("mdx:model_a", "mdx", "model_a", "Model A")
        with patch("cli.job.ModelIdentityService") as service_cls:
            service = service_cls.return_value
            service.resolve.return_value = record
            _canonicalize_model_references(settings, Mock())
        service.resolve.assert_any_call("Model A", family="mdx", fuzzy=False)

    def test_canonicalize_ignores_stale_unused_family_primary(self) -> None:
        """GUI profile may keep a stale VR primary while --model selects MDX."""
        from cli.job import _canonicalize_model_references
        from core.model_identity import ModelRecord
        from core.types import ProcessMethod

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:good"
        settings.vr.model = "vr:stale-missing"
        mdx_record = ModelRecord("mdx:good", "mdx", "good", "Good")

        def resolve(raw: str, **kwargs: Any) -> ModelRecord:
            if kwargs.get("family") == "vr" or "stale" in str(raw):
                raise ValueError("unknown or unregistered model")
            return mdx_record

        with patch("cli.job.ModelIdentityService") as service_cls:
            service = service_cls.return_value
            service.resolve.side_effect = resolve
            _canonicalize_model_references(settings, Mock())
        self.assertEqual(settings.mdx.model, "MDX-Net: Good")



class DeviceResolutionTests(unittest.TestCase):
    def test_directml_sets_the_backend_flag(self) -> None:
        self.assertIn(("process.use_directml", True), _device_override("directml:1"))

    def test_cpu_clears_a_profile_directml_flag(self) -> None:
        pairs = _device_override("cpu")
        self.assertIn(("process.use_gpu", False), pairs)
        self.assertIn(("process.use_directml", False), pairs)


def _args(**values: Any) -> argparse.Namespace:
    defaults = dict(
        on_exists="fail", fail_fast=False, report="human", quiet=True,
        manifest=False, manifest_out=None, job_id="job-test",
    )
    defaults.update(values)
    return argparse.Namespace(**defaults)


class BatchExecutionTests(unittest.TestCase):
    def test_signal_handler_stops_cooperatively_then_forces(self) -> None:
        handlers: dict[int, Any] = {}
        runner = Mock()

        def install(signum: int, handler: Any) -> None:
            handlers[signum] = handler

        def blocking(*_args: Any, **_kwargs: Any) -> RunResult:
            import signal

            handlers[signal.SIGINT](signal.SIGINT, None)
            handlers[signal.SIGINT](signal.SIGINT, None)
            return RunResult(0.1, stopped=True)

        with patch("cli.execution.signal.getsignal", return_value=object()), patch(
            "cli.execution.signal.signal", side_effect=install
        ), patch("cli.execution.run_blocking", side_effect=blocking):
            result = run_runner_cli(runner, lambda _callbacks: None, print_console=False)
        self.assertTrue(result.interrupted)
        self.assertEqual(
            [call.kwargs["force"] for call in runner.stop.call_args_list],
            [False, True],
        )

    def test_engine_console_uses_stderr_without_touching_machine_stdout(self) -> None:
        out, err = io.StringIO(), io.StringIO()

        def blocking(*_args: Any, **kwargs: Any) -> RunResult:
            kwargs["on_console"]("engine line")
            return RunResult(0.1, completed=True)

        with patch("cli.execution.signal.getsignal", return_value=object()), patch(
            "cli.execution.signal.signal"
        ), patch(
            "cli.execution.run_blocking", side_effect=blocking
        ), redirect_stdout(out), redirect_stderr(err):
            result = run_runner_cli(
                Mock(), lambda _callbacks: None, print_console=True
            )
        self.assertTrue(result.ok)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "engine line\n")

    def test_reused_runner_receives_each_inputs_staging_settings(self) -> None:
        class Runner:
            def __init__(self) -> None:
                self.settings = Settings.defaults()
                self._thread = None

            def is_running(self) -> bool:
                return False

            def start(self, _paths: list[str], callbacks: JobCallbacks, **_kwargs: Any) -> None:
                callbacks.complete()

            def stop(self, *, force: bool = False) -> None:
                pass

        settings = Settings.defaults()
        settings.process.export_path = "/tmp/stage-2"
        runner = Runner()
        result = run_separation_cli(
            settings, ["/tmp/input.wav"], print_console=False, runner=runner
        )
        self.assertTrue(result.ok)
        self.assertIs(runner.settings, settings)

    def make_job(self, root: str, inputs: list[str]) -> ResolvedJob:
        settings = Settings.defaults()
        settings.process.export_path = root
        planned = tuple(
            _planned_input(path, root, os.path.splitext(os.path.basename(path))[0])
            for path in inputs
        )
        return ResolvedJob(
            command="separate", settings=settings,
            profile=LoadedProfile("defaults", "built-in"),
            inputs=inputs, output=root,
            plan={"identity": {"id": "mdx:a", "hash": "h"}},
            resolved=SimpleNamespace(inputs=planned),
        )

    def test_continue_on_error_promotes_success_and_returns_partial(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            inputs = [os.path.join(root, "a.wav"), os.path.join(root, "b.wav")]
            for path in inputs:
                open(path, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, inputs)

            def one(self: JobRunner, planned: PlannedInput, _callbacks: JobCallbacks) -> InputOutcome:
                if planned.path.endswith("b.wav"):
                    return InputOutcome(planned.path, "failed", error="bad", elapsed_s=0.1)
                name = f"{format_stem_basename(planned.naming.track_base, 'Vocals')}.wav"
                path = os.path.join(self.settings.process.export_path, name)
                os.makedirs(self.settings.process.export_path, exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(b"ok")
                return InputOutcome(planned.path, "success", outputs=(path,), elapsed_s=0.1)

            with patch.object(JobRunner, "resolve_models", return_value=[]), patch.object(
                JobRunner, "_run_one_planned", one
            ):
                outcome = run_batch(_args(), job)
            self.assertEqual(outcome.exit_code, 3)
            self.assertTrue(os.path.isfile(os.path.join(output, "a (Vocals).wav")))
            self.assertFalse(os.path.exists(os.path.join(output, ".uvr-tmp")))

    def test_fail_collision_stops_before_processing(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            output = os.path.join(root, "out")
            os.makedirs(output)
            open(os.path.join(output, "song (Vocals).wav"), "wb").close()
            with self.assertRaises(FileExistsError):
                # Promotion-time race enforcement.
                from cli.execution import _promote
                stage = os.path.join(root, "stage")
                os.makedirs(stage)
                open(os.path.join(stage, "song (Vocals).wav"), "wb").close()
                _promote(
                    stage, output, "fail",
                    destinations=[os.path.join(output, "song (Vocals).wav")],
                )
            with self.assertRaises(ValueError):
                preflight_collisions(self.make_job(output, [source]), "fail")

    def test_manifest_contains_settings_and_job_spec(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "manifest.json")
            job = self.make_job(root, ["/a.wav"])
            result = write_manifest(
                _args(manifest_out=path), job,
                BatchOutcome("success", 1.0, [{"input": "/a.wav", "status": "success", "outputs": []}]),
            )
            self.assertEqual(result, path)
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("settings", payload)
            self.assertEqual(payload["job_spec"]["inputs"], ["/a.wav"])

    def test_same_basename_inputs_receive_deterministic_names(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            first = os.path.join(root, "one", "song.wav")
            second = os.path.join(root, "two", "song.wav")
            os.makedirs(os.path.dirname(first))
            os.makedirs(os.path.dirname(second))
            open(first, "wb").close()
            open(second, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, [first, second])
            job.resolved = SimpleNamespace(inputs=(
                _planned_input(first, output, "1-song"),
                _planned_input(second, output, "2-song"),
            ))

            def one(self: JobRunner, planned: PlannedInput, _callbacks: JobCallbacks) -> InputOutcome:
                name = f"{format_stem_basename(planned.naming.track_base, 'Vocals')}.wav"
                path = os.path.join(self.settings.process.export_path, name)
                os.makedirs(self.settings.process.export_path, exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(b"ok")
                return InputOutcome(planned.path, "success", outputs=(path,), elapsed_s=0.1)

            with patch.object(JobRunner, "resolve_models", return_value=[]), patch.object(
                JobRunner, "_run_one_planned", one
            ):
                outcome = run_batch(_args(), job)
            self.assertEqual(outcome.exit_code, 0)
            self.assertTrue(os.path.isfile(os.path.join(output, "1-song (Vocals).wav")))
            self.assertTrue(os.path.isfile(os.path.join(output, "2-song (Vocals).wav")))

    def test_run_batch_passes_final_planned_for_runner_rebase(self) -> None:
        """planned stays under job.output; JobRunner rebases once onto the stage."""
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, [source])
            captured: dict[str, Any] = {}

            def one(self: JobRunner, planned: PlannedInput, _callbacks: JobCallbacks) -> InputOutcome:
                captured["planned"] = planned
                captured["planned_output_root"] = self._run_output_root
                captured["stage"] = self.settings.process.export_path
                naming = self._naming_for_file(
                    planned.path, export_path=self.settings.process.export_path,
                )
                captured["rebased"] = naming
                name = f"{format_stem_basename(naming.track_base, 'Vocals')}.wav"
                os.makedirs(naming.export_directory, exist_ok=True)
                path = os.path.join(naming.export_directory, name)
                with open(path, "wb") as handle:
                    handle.write(b"ok")
                return InputOutcome(planned.path, "success", outputs=(path,), elapsed_s=0.1)

            with patch.object(JobRunner, "resolve_models", return_value=[]), patch.object(
                JobRunner, "_run_one_planned", one
            ):
                outcome = run_batch(_args(), job)
            self.assertEqual(outcome.exit_code, 0)
            planned = captured["planned"]
            self.assertEqual(
                os.path.abspath(planned.naming.export_directory),
                os.path.abspath(output),
            )
            self.assertEqual(
                os.path.abspath(captured["planned_output_root"]),
                os.path.abspath(output),
            )
            self.assertEqual(
                os.path.abspath(captured["rebased"].export_directory),
                os.path.abspath(captured["stage"]),
            )
            self.assertTrue(
                os.path.isfile(os.path.join(output, "song (Vocals).wav"))
            )

    def test_run_batch_uses_start_resolved_with_stage_export_paths(self) -> None:
        captured: dict[str, Any] = {}

        def fake_start_resolved(
            _self: JobRunner, job: Any, callbacks: JobCallbacks, **kwargs: Any
        ) -> None:
            captured["job_output"] = job.output
            captured["export_paths"] = kwargs.get("export_paths")
            captured["planned_dir"] = job.inputs[0].naming.export_directory
            if callbacks.on_complete:
                callbacks.on_complete()

        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, [source])
            with patch("core.job_runner.JobRunner.start_resolved", fake_start_resolved):
                run_batch(_args(), job)
        paths = captured["export_paths"]
        self.assertTrue(paths)
        self.assertTrue(str(paths[0]).startswith(str(captured["job_output"])))
        self.assertIn(".uvr-tmp", str(paths[0]))
        self.assertEqual(captured["planned_dir"], captured["job_output"])

    def test_run_batch_interrupt_does_not_relabel_promoted_success(self) -> None:
        """Force-stop after one success must not duplicate that path as interrupted."""
        with tempfile.TemporaryDirectory() as root:
            inputs = [os.path.join(root, "a.wav"), os.path.join(root, "b.wav")]
            for path in inputs:
                open(path, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, inputs)

            def fake_start_resolved(
                self: JobRunner, batch_job: Any, callbacks: JobCallbacks, **kwargs: Any
            ) -> None:
                planned = batch_job.inputs[0]
                stage = kwargs["export_paths"][0]
                name = f"{format_stem_basename(planned.naming.track_base, 'Vocals')}.wav"
                path = os.path.join(stage, name)
                with open(path, "wb") as handle:
                    handle.write(b"ok")
                self.last_outcomes = (
                    InputOutcome(planned.path, "success", outputs=(path,), elapsed_s=0.1),
                )
                if callbacks.on_stopped:
                    callbacks.on_stopped()

            with patch.object(JobRunner, "resolve_models", return_value=[]), patch(
                "core.job_runner.JobRunner.start_resolved", fake_start_resolved
            ):
                outcome = run_batch(_args(), job)

            paths = [item["input"] for item in outcome.inputs]
            self.assertEqual(paths.count(inputs[0]), 1)
            self.assertEqual(outcome.inputs[0]["status"], "success")
            self.assertEqual(outcome.inputs[1]["status"], "failed")
            self.assertEqual(outcome.inputs[1]["error"], "interrupted")
            self.assertEqual(outcome.inputs[1]["input"], inputs[1])
            self.assertTrue(outcome.interrupted)
            self.assertEqual(outcome.exit_code, 130)
            self.assertTrue(os.path.isfile(os.path.join(output, "a (Vocals).wav")))

    def test_run_batch_interrupt_with_empty_outcomes_emits_interrupted_row(self) -> None:
        """Interrupt before any InputOutcome must not report status success."""
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, [source])

            def fake_start_resolved(
                self: JobRunner, _job: Any, callbacks: JobCallbacks, **_kwargs: Any
            ) -> None:
                self.last_outcomes = ()
                if callbacks.on_stopped:
                    callbacks.on_stopped()

            with patch.object(JobRunner, "resolve_models", return_value=[]), patch(
                "core.job_runner.JobRunner.start_resolved", fake_start_resolved
            ):
                outcome = run_batch(_args(), job)

            self.assertTrue(outcome.interrupted)
            self.assertEqual(outcome.exit_code, 130)
            self.assertNotEqual(outcome.status, "success")
            self.assertEqual(len(outcome.inputs), 1)
            self.assertEqual(outcome.inputs[0]["status"], "failed")
            self.assertEqual(outcome.inputs[0]["error"], "interrupted")
            self.assertEqual(outcome.inputs[0]["input"], source)

    def test_run_batch_ensemble_calls_resolve_models(self) -> None:
        """Ensemble jobs share models via resolve_models (ENSEMBLE_MODE assemble)."""
        from bundled.constants import ENSEMBLE_MODE
        from core.types import ProcessMethod

        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "a.wav")
            open(source, "wb").close()
            output = os.path.join(root, "out")
            settings = Settings.defaults()
            settings.process.method = ProcessMethod.ENSEMBLE
            settings.process.export_path = output
            planned = (_planned_input(source, output, "a"),)
            job = ResolvedJob(
                command="ensemble",
                settings=settings,
                profile=LoadedProfile("defaults", "built-in"),
                inputs=[source],
                output=output,
                plan={"identity": {"id": "ensemble", "hash": "h"}},
                resolved=SimpleNamespace(inputs=planned),
            )
            fake_models = [object(), object()]
            captured: dict[str, Any] = {}

            def one(self: JobRunner, planned: PlannedInput, _callbacks: JobCallbacks) -> InputOutcome:
                captured["models"] = self._run_models
                captured["shared_runner"] = self
                name = f"{format_stem_basename('a', 'Vocals')}.wav"
                path = os.path.join(self.settings.process.export_path, name)
                os.makedirs(self.settings.process.export_path, exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(b"ok")
                return InputOutcome(planned.path, "success", outputs=(path,), elapsed_s=0.1)

            with patch(
                "core.job_runner.assemble_model", return_value=fake_models
            ) as assemble, patch.object(JobRunner, "_run_one_planned", one):
                outcome = run_batch(_args(), job)

            self.assertEqual(outcome.exit_code, 0)
            assemble.assert_called_once()
            self.assertEqual(
                assemble.call_args.kwargs.get("arch_type"), ENSEMBLE_MODE
            )
            self.assertEqual(captured["models"], fake_models)
            self.assertIsInstance(captured["shared_runner"], JobRunner)


class SettingPathsTests(unittest.TestCase):
    def test_setting_paths_include_audio_and_ui(self) -> None:
        from cli.discovery import _setting_paths

        paths = _setting_paths()
        self.assertIn("audio_tools.apollo_model", paths)
        self.assertIn("ui.confirm_processing_plan", paths)


if __name__ == "__main__":
    unittest.main()
