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

from cli.execution import (
    BatchOutcome, preflight_collisions, run_batch, run_runner_cli, write_manifest,
)
from core.export_naming import OutputNamingContext, format_stem_basename
from core.input_discovery import discover_inputs
from core.job_plan import (
    PlannedInput, PlannedOutput, ResolvedJob as CoreResolvedJob, ValidationLevel,
)
from cli.job import ResolvedJob, _device_override
from cli.profiles import LoadedProfile, load_profile, save_profile
from cli.replay import _flat_settings
from core.blocking_runner import RunResult
from core.job_callbacks import JobCallbacks
from core.job_runner import InputOutcome, JobRunner
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


def _core_job(
    command: str,
    settings: Settings,
    planned: tuple[PlannedInput, ...],
    output: str,
) -> CoreResolvedJob:
    """A real ``core`` ResolvedJob: ``run_batch`` slices it with dataclasses.replace."""
    return CoreResolvedJob(
        command, settings, planned, (), {}, (),
        ValidationLevel.MODEL, 0, "fingerprint", "cpu", output,
    )


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


class PlannedSettingsReturnTests(unittest.TestCase):
    """CLI ResolvedJob.settings must be the JobResolver copy, not the pre-copy."""

    def _planned_effective(self, settings: Settings) -> Mock:
        effective = Mock()
        effective.settings = settings
        effective.diagnostics = ()
        effective.to_dict.return_value = {}
        return effective

    def test_separate_job_returns_resolver_settings(self) -> None:
        from cli.job import resolve_separate_job
        from core.model_identity import ModelRecord

        pre_settings = Settings.defaults()
        pre_settings.mdx.model = "MDX-Net: Display"
        planned = Settings.defaults()
        planned.mdx.model = "mdx:planned-id"
        record = ModelRecord("mdx:planned-id", "mdx", "planned-id", "Display")
        profile = LoadedProfile("defaults", "built-in")
        args = argparse.Namespace(
            model="mdx:planned-id",
            stems=None,
            long_chunk_seconds=None,
            long_chunk_overlap=None,
            vocal_split=None,
            device=None,
            on_exists="fail",
        )
        with patch("cli.job._base_resolve", return_value=(pre_settings, profile, ["/a.wav"], "/out")), patch(
            "cli.job.resolve_model_id", return_value=record
        ), patch("cli.job.ModelRepository"), patch(
            "cli.job._canonicalize_model_references", return_value={}
        ), patch("cli.job._device_pairs", return_value=([], False)), patch(
            "cli.job.SettingsResolver"
        ) as resolver_cls, patch("core.job_plan.JobResolver") as job_resolver_cls:
            resolver_cls.return_value.resolve.return_value = (pre_settings, {})
            job_resolver_cls.return_value.resolve.return_value = self._planned_effective(planned)
            job = resolve_separate_job(args)
        self.assertIs(job.settings, planned)
        self.assertEqual(job.settings.mdx.model, "mdx:planned-id")

    def test_ensemble_job_returns_resolver_settings(self) -> None:
        from cli.job import resolve_ensemble_job
        from core.model_identity import ModelRecord
        from core.stems import EnsemblePair

        pre_settings = Settings.defaults()
        pre_settings.ensemble.selected_models = ["MDX-Net: A", "MDX-Net: B"]
        planned = Settings.defaults()
        planned.ensemble.selected_models = ["mdx:a", "mdx:b"]
        records = [
            ModelRecord("mdx:a", "mdx", "a", "A"),
            ModelRecord("mdx:b", "mdx", "b", "B"),
        ]
        profile = LoadedProfile("defaults", "built-in")
        args = argparse.Namespace(
            ensemble=None,
            models=["mdx:a", "mdx:b"],
            main_stem=EnsemblePair.VOCALS_INSTRUMENTAL.value,
            stems=None,
            long_chunk_seconds=None,
            long_chunk_overlap=None,
            algorithm=None,
            wav_ensemble=None,
            save_all_outputs=None,
            device=None,
            on_exists="fail",
        )
        with patch("cli.job._base_resolve", return_value=(pre_settings, profile, ["/a.wav"], "/out")), patch(
            "cli.job.resolve_model_id", side_effect=records
        ), patch("cli.job.ModelRepository"), patch(
            "cli.job._canonicalize_model_references", return_value={}
        ), patch("cli.job._device_pairs", return_value=([], False)), patch(
            "cli.job.SettingsResolver"
        ) as resolver_cls, patch("core.job_plan.JobResolver") as job_resolver_cls:
            resolver_cls.return_value.resolve.return_value = (pre_settings, {})
            job_resolver_cls.return_value.resolve.return_value = self._planned_effective(planned)
            job = resolve_ensemble_job(args)
        self.assertIs(job.settings, planned)
        self.assertEqual(job.settings.ensemble.selected_models, ["mdx:a", "mdx:b"])


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
            resolved=_core_job("separate", settings, planned, root),
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
            job.resolved = _core_job(
                "separate",
                job.settings,
                (
                    _planned_input(first, output, "1-song"),
                    _planned_input(second, output, "2-song"),
                ),
                output,
            )

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

    def test_run_batch_promotes_each_input_before_the_next_one_runs(self) -> None:
        """A mid-batch death must not take completed inputs down with it."""
        with tempfile.TemporaryDirectory() as root:
            inputs = [os.path.join(root, "a.wav"), os.path.join(root, "b.wav")]
            for path in inputs:
                open(path, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, inputs)
            seen: list[list[str]] = []

            def one(self: JobRunner, planned: PlannedInput, _callbacks: JobCallbacks) -> InputOutcome:
                seen.append(sorted(
                    name for name in os.listdir(output) if name != ".uvr-tmp"
                ))
                name = f"{format_stem_basename(planned.naming.track_base, 'Vocals')}.wav"
                os.makedirs(self.settings.process.export_path, exist_ok=True)
                path = os.path.join(self.settings.process.export_path, name)
                with open(path, "wb") as handle:
                    handle.write(b"ok")
                return InputOutcome(planned.path, "success", outputs=(path,), elapsed_s=0.1)

            with patch.object(JobRunner, "resolve_models", return_value=[]), patch.object(
                JobRunner, "_run_one_planned", one
            ):
                outcome = run_batch(_args(), job)

            self.assertEqual(outcome.exit_code, 0)
            self.assertEqual(seen[0], [])
            self.assertEqual(seen[1], ["a (Vocals).wav"])

    def test_run_batch_slices_one_planned_input_per_run(self) -> None:
        batches: list[tuple[str, ...]] = []
        stages: list[tuple[str, ...]] = []

        def fake_start_resolved(
            self: JobRunner, batch_job: Any, callbacks: JobCallbacks, **kwargs: Any
        ) -> None:
            batches.append(tuple(item.path for item in batch_job.inputs))
            stages.append(tuple(kwargs["export_paths"]))
            self.last_outcomes = tuple(
                InputOutcome(item.path, "skipped", elapsed_s=0.0)
                for item in batch_job.inputs
            )
            if callbacks.on_complete:
                callbacks.on_complete()

        with tempfile.TemporaryDirectory() as root:
            inputs = [os.path.join(root, "a.wav"), os.path.join(root, "b.wav")]
            for path in inputs:
                open(path, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, inputs)
            with patch.object(JobRunner, "resolve_models", return_value=[]), patch(
                "core.job_runner.JobRunner.start_resolved", fake_start_resolved
            ):
                run_batch(_args(), job)

        self.assertEqual(batches, [(inputs[0],), (inputs[1],)])
        self.assertEqual([len(item) for item in stages], [1, 1])
        self.assertNotEqual(stages[0][0], stages[1][0])

    def test_run_batch_jsonl_events_interleave_per_input(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            inputs = [os.path.join(root, "a.wav"), os.path.join(root, "b.wav")]
            for path in inputs:
                open(path, "wb").close()
            output = os.path.join(root, "out")
            job = self.make_job(output, inputs)

            def one(self: JobRunner, planned: PlannedInput, _callbacks: JobCallbacks) -> InputOutcome:
                name = f"{format_stem_basename(planned.naming.track_base, 'Vocals')}.wav"
                os.makedirs(self.settings.process.export_path, exist_ok=True)
                path = os.path.join(self.settings.process.export_path, name)
                with open(path, "wb") as handle:
                    handle.write(b"ok")
                return InputOutcome(planned.path, "success", outputs=(path,), elapsed_s=0.1)

            out = io.StringIO()
            with patch.object(JobRunner, "resolve_models", return_value=[]), patch.object(
                JobRunner, "_run_one_planned", one
            ), redirect_stdout(out):
                run_batch(_args(report="jsonl"), job)

            events = [json.loads(line) for line in out.getvalue().splitlines()]
            self.assertEqual(
                [
                    (item["event"], item.get("phase"), item["input"])
                    for item in events
                ],
                [
                    ("progress", "input_started", inputs[0]),
                    ("input_finished", None, inputs[0]),
                    ("progress", "input_started", inputs[1]),
                    ("input_finished", None, inputs[1]),
                ],
            )

    def test_run_batch_unexpected_failure_after_success_is_not_success(self) -> None:
        """A runner-level raise mid-batch must fail the in-flight input."""
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
                if planned.path.endswith("b.wav"):
                    self.last_outcomes = ()
                    if callbacks.on_error:
                        callbacks.on_error(RuntimeError("boom"))
                    return
                stage = kwargs["export_paths"][0]
                name = f"{format_stem_basename(planned.naming.track_base, 'Vocals')}.wav"
                path = os.path.join(stage, name)
                with open(path, "wb") as handle:
                    handle.write(b"ok")
                self.last_outcomes = (
                    InputOutcome(planned.path, "success", outputs=(path,), elapsed_s=0.1),
                )
                if callbacks.on_complete:
                    callbacks.on_complete()

            with patch.object(JobRunner, "resolve_models", return_value=[]), patch(
                "core.job_runner.JobRunner.start_resolved", fake_start_resolved
            ):
                outcome = run_batch(_args(), job)

            self.assertEqual(
                [(item["input"], item["status"]) for item in outcome.inputs],
                [(inputs[0], "success"), (inputs[1], "failed")],
            )
            self.assertIn("RuntimeError: boom", outcome.inputs[1]["error"])
            self.assertEqual(outcome.status, "partial")
            self.assertEqual(outcome.exit_code, 3)
            self.assertTrue(os.path.isfile(os.path.join(output, "a (Vocals).wav")))

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
                resolved=_core_job("ensemble", settings, planned, output),
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
