"""Pure-helper tests for the local model sweep. No models, no torch."""

import importlib.util
import os
import sys
import unittest
from typing import Any, Dict, List, Tuple

_SPEC = importlib.util.spec_from_file_location(
    "model_sweep",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "model_sweep.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
model_sweep = importlib.util.module_from_spec(_SPEC)
sys.modules["model_sweep"] = model_sweep
_SPEC.loader.exec_module(model_sweep)


def _installed(**kwargs: Any):
    base = dict(mdx=[], vr=[], demucs=[], apollo=[], ensemble_tags=[], karaoke_tags=[])
    base.update(kwargs)
    return model_sweep.Installed(**base)


class DiscoveryTests(unittest.TestCase):
    ALL = {"mdx", "vr", "demucs", "apollo", "composite"}

    def test_one_job_per_installed_weight(self) -> None:
        installed = _installed(
            mdx=["a.ckpt", "b.onnx"], vr=["v.pth"], demucs=["hdemucs_mmi.yaml"]
        )
        jobs = model_sweep.discover_jobs(installed, methods={"mdx", "vr", "demucs"})
        self.assertEqual(
            [(j.method, j.model) for j in jobs],
            [
                ("mdx", "a.ckpt"),
                ("mdx", "b.onnx"),
                ("vr", "v.pth"),
                ("demucs", "hdemucs_mmi.yaml"),
            ],
        )
        self.assertTrue(all(j.kind == model_sweep.KIND_SINGLE for j in jobs))

    def test_method_filter_excludes_others(self) -> None:
        installed = _installed(mdx=["a.ckpt"], vr=["v.pth"])
        jobs = model_sweep.discover_jobs(installed, methods={"vr"})
        self.assertEqual([j.model for j in jobs], ["v.pth"])

    def test_only_filter_is_substring_match(self) -> None:
        installed = _installed(mdx=["roformer_inst.ckpt", "mdx23c.ckpt"])
        jobs = model_sweep.discover_jobs(installed, methods={"mdx"}, only="roformer")
        self.assertEqual([j.model for j in jobs], ["roformer_inst.ckpt"])

    def test_skip_filter_drops_named_model(self) -> None:
        installed = _installed(mdx=["a.ckpt", "b.ckpt"])
        jobs = model_sweep.discover_jobs(
            installed, methods={"mdx"}, skip=frozenset({"a.ckpt"})
        )
        self.assertEqual([j.model for j in jobs], ["b.ckpt"])

    def test_apollo_models_become_tool_jobs(self) -> None:
        installed = _installed(apollo=["apollo_universal_model.ckpt"])
        jobs = model_sweep.discover_jobs(installed, methods={"apollo"})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].kind, model_sweep.KIND_TOOL)
        self.assertEqual(
            jobs[0].overrides["audio_tools.apollo_model"], "apollo_universal_model.ckpt"
        )

    def test_ensemble_composite_uses_two_member_tags(self) -> None:
        installed = _installed(
            mdx=["a.ckpt", "b.ckpt"],
            ensemble_tags=["MDX-Net: A", "MDX-Net: B", "MDX-Net: C"],
        )
        jobs = model_sweep.discover_jobs(installed, methods={"composite"})
        ensemble = [j for j in jobs if j.kind == model_sweep.KIND_ENSEMBLE]
        self.assertEqual(len(ensemble), 1)
        self.assertEqual(
            ensemble[0].overrides["selected_models"], ["MDX-Net: A", "MDX-Net: B"]
        )
        self.assertEqual(ensemble[0].overrides["ensemble_type"], "Max Spec/Min Spec")
        self.assertEqual(
            ensemble[0].overrides["ensemble_main_stem"], "vocals_instrumental"
        )
        self.assertFalse(ensemble[0].overrides["is_save_all_outputs_ensemble"])

    def test_ensemble_composite_skips_with_one_member(self) -> None:
        installed = _installed(mdx=["a.ckpt"], ensemble_tags=["MDX-Net: A"])
        jobs = model_sweep.discover_jobs(installed, methods={"composite"})
        ensemble = [j for j in jobs if j.id == "composite:ensemble"]
        self.assertEqual(len(ensemble), 1)
        self.assertEqual(ensemble[0].kind, model_sweep.KIND_SKIP)
        self.assertIn("two", ensemble[0].detail)

    def test_secondary_chain_composite_pairs_vr_with_mdx(self) -> None:
        installed = _installed(
            mdx=["m.ckpt"], vr=["v.pth"], ensemble_tags=["MDX-Net: M", "VR Arc: V"]
        )
        jobs = model_sweep.discover_jobs(installed, methods={"composite"})
        chain = next(j for j in jobs if j.id == "composite:secondary-chain")
        self.assertEqual(chain.method, "vr")
        self.assertEqual(chain.model, "v.pth")
        self.assertTrue(chain.overrides["vr_is_secondary_model_activate"])
        self.assertEqual(chain.overrides["vr_voc_inst_secondary_model"], "MDX-Net: M")
        self.assertEqual(chain.overrides["vr_voc_inst_secondary_model_scale"], 0.5)

    def test_vocal_splitter_composite_needs_a_karaoke_model(self) -> None:
        installed = _installed(mdx=["m.ckpt"], karaoke_tags=[])
        jobs = model_sweep.discover_jobs(installed, methods={"composite"})
        splitter = next(j for j in jobs if j.id == "composite:vocal-splitter")
        self.assertEqual(splitter.kind, model_sweep.KIND_SKIP)

    def test_job_ids_are_unique(self) -> None:
        installed = _installed(
            mdx=["a.ckpt", "b.ckpt"],
            vr=["v.pth"],
            demucs=["d.yaml"],
            apollo=["ap.ckpt"],
            ensemble_tags=["MDX-Net: A", "MDX-Net: B"],
            karaoke_tags=["MDX-Net: K"],
        )
        jobs = model_sweep.discover_jobs(installed, methods=self.ALL)
        ids = [j.id for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))


class ClassifyTests(unittest.TestCase):
    def _result(self, **kwargs: Any):
        base = {
            "ok": True,
            "error_type": None,
            "message": "",
            "elapsed_s": 1.0,
            "outputs": [["/tmp/out/x (Vocals).wav", 1024]],
            "stopped": False,
            "unrecognized": False,
        }
        base.update(kwargs)
        return base

    def test_clean_run_with_output_passes(self) -> None:
        verdict, _ = model_sweep.classify(exit_code=0, result=self._result(), timed_out=False)
        self.assertEqual(verdict, model_sweep.PASS)

    def test_clean_run_without_output_is_no_output(self) -> None:
        verdict, _ = model_sweep.classify(
            exit_code=0, result=self._result(outputs=[]), timed_out=False
        )
        self.assertEqual(verdict, model_sweep.NO_OUTPUT)

    def test_exception_becomes_typed_failure(self) -> None:
        verdict, detail = model_sweep.classify(
            exit_code=1,
            result=self._result(
                ok=False,
                error_type="BeartypeCallHintParamViolation",
                message="parameter attn_dropout=0 violates type hint <class 'float'>",
                outputs=[],
            ),
            timed_out=False,
        )
        self.assertEqual(verdict, "FAIL(BeartypeCallHintParamViolation)")
        self.assertIn("attn_dropout", detail)

    def test_cuda_oom_is_classified_as_oom(self) -> None:
        verdict, _ = model_sweep.classify(
            exit_code=1,
            result=self._result(
                ok=False,
                error_type="OutOfMemoryError",
                message="CUDA out of memory. Tried to allocate 3.00 GiB",
                outputs=[],
            ),
            timed_out=False,
        )
        self.assertEqual(verdict, model_sweep.OOM)

    def test_ort_allocation_failure_is_oom(self) -> None:
        verdict, _ = model_sweep.classify(
            exit_code=1,
            result=self._result(
                ok=False,
                error_type="Fail",
                message="Failed to allocate memory for requested buffer of size 4",
                outputs=[],
            ),
            timed_out=False,
        )
        self.assertEqual(verdict, model_sweep.OOM)

    def test_missing_result_is_crash(self) -> None:
        verdict, _ = model_sweep.classify(exit_code=-11, result=None, timed_out=False)
        self.assertEqual(verdict, "CRASH(exit -11)")

    def test_timeout_wins_over_everything(self) -> None:
        verdict, _ = model_sweep.classify(exit_code=None, result=None, timed_out=True)
        self.assertEqual(verdict, model_sweep.TIMEOUT)

    def test_unrecognized_model_is_its_own_verdict(self) -> None:
        verdict, _ = model_sweep.classify(
            exit_code=0, result=self._result(unrecognized=True, outputs=[]), timed_out=False
        )
        self.assertEqual(verdict, model_sweep.UNRECOGNIZED)

    def test_detail_is_first_line_only(self) -> None:
        _, detail = model_sweep.classify(
            exit_code=1,
            result=self._result(
                ok=False, error_type="RuntimeError", message="line one\nline two", outputs=[]
            ),
            timed_out=False,
        )
        self.assertEqual(detail, "line one")


class FailurePolicyTests(unittest.TestCase):
    def test_pass_and_skip_are_not_failures(self) -> None:
        self.assertFalse(model_sweep.is_failure(model_sweep.PASS, strict=False))
        self.assertFalse(model_sweep.is_failure("SKIP(no model)", strict=False))

    def test_oom_cpu_ok_is_not_a_failure(self) -> None:
        self.assertFalse(model_sweep.is_failure(model_sweep.OOM_CPU_OK, strict=False))

    def test_bare_oom_is_a_failure(self) -> None:
        self.assertTrue(model_sweep.is_failure(model_sweep.OOM, strict=False))

    def test_unrecognized_only_fails_under_strict(self) -> None:
        self.assertFalse(model_sweep.is_failure(model_sweep.UNRECOGNIZED, strict=False))
        self.assertTrue(model_sweep.is_failure(model_sweep.UNRECOGNIZED, strict=True))

    def test_typed_failures_and_crashes_fail(self) -> None:
        self.assertTrue(model_sweep.is_failure("FAIL(RuntimeError)", strict=False))
        self.assertTrue(model_sweep.is_failure("CRASH(exit -11)", strict=False))
        self.assertTrue(model_sweep.is_failure(model_sweep.NO_OUTPUT, strict=False))
        self.assertTrue(model_sweep.is_failure(model_sweep.TIMEOUT, strict=False))


class RenderTests(unittest.TestCase):
    def test_row_contains_id_verdict_and_elapsed(self) -> None:
        row = model_sweep.render_row("mdx:a.ckpt", model_sweep.PASS, 12.5, "")
        self.assertIn("mdx:a.ckpt", row)
        self.assertIn("PASS", row)
        self.assertIn("12.5s", row)

    def test_summary_counts_each_verdict(self) -> None:
        summary = model_sweep.render_summary(
            [model_sweep.PASS, model_sweep.PASS, "FAIL(RuntimeError)"]
        )
        self.assertIn("2 passed", summary)
        self.assertIn("1 failed", summary)


class ScratchEnvTests(unittest.TestCase):
    def test_clip_is_three_seconds_stereo(self) -> None:
        import tempfile

        import soundfile as sf

        with tempfile.TemporaryDirectory() as tmp:
            path = model_sweep.make_input_clip(os.path.join(tmp, "in.wav"))
            data, rate = sf.read(path)
        self.assertEqual(rate, 44100)
        self.assertEqual(data.shape[1], 2)
        self.assertEqual(data.shape[0], 44100 * 3)

    def test_clip_is_not_silent(self) -> None:
        import tempfile

        import soundfile as sf

        with tempfile.TemporaryDirectory() as tmp:
            path = model_sweep.make_input_clip(os.path.join(tmp, "in.wav"))
            data, _ = sf.read(path)
        self.assertGreater(abs(data).max(), 0.1)

    def test_clip_is_deterministic(self) -> None:
        import tempfile

        import soundfile as sf

        with tempfile.TemporaryDirectory() as tmp:
            a, _ = sf.read(model_sweep.make_input_clip(os.path.join(tmp, "a.wav")))
            b, _ = sf.read(model_sweep.make_input_clip(os.path.join(tmp, "b.wav")))
        self.assertTrue((a == b).all())

    def test_scratch_symlinks_models_and_copies_settings(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            models = os.path.join(tmp, "models")
            os.makedirs(os.path.join(models, "VR_Models"))
            src = os.path.join(tmp, "settings.json")
            with open(src, "w") as handle:
                json.dump({"schema_version": 1}, handle)

            data_dir, settings_path = model_sweep.prepare_scratch(
                os.path.join(tmp, "scratch"), models_dir=models, settings_src=src
            )

            self.assertTrue(os.path.islink(os.path.join(data_dir, "models")))
            self.assertTrue(
                os.path.isdir(os.path.join(data_dir, "models", "VR_Models"))
            )
            self.assertTrue(os.path.isfile(settings_path))
            self.assertNotEqual(os.path.abspath(settings_path), os.path.abspath(src))

    def test_scratch_without_source_settings_writes_defaults(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            models = os.path.join(tmp, "models")
            os.makedirs(models)
            _, settings_path = model_sweep.prepare_scratch(
                os.path.join(tmp, "scratch"), models_dir=models, settings_src=None
            )
            self.assertTrue(os.path.isfile(settings_path))

    def test_child_env_pins_data_dir_and_disables_warmup(self) -> None:
        env = model_sweep.child_env("/scratch/data")
        self.assertEqual(env["UVR_DATA_DIR"], "/scratch/data")
        self.assertEqual(env["UVR_SKIP_SEPARATE_WARMUP"], "1")
        self.assertEqual(env["UVR_DISABLE_POLITREES"], "1")


class ChildHelperTests(unittest.TestCase):
    def test_apply_overrides_handles_flat_and_dotted_keys(self) -> None:
        from core.settings import Settings

        settings = Settings()
        model_sweep.apply_overrides(
            settings,
            {
                "is_gpu_conversion": False,
                "mdx_segment_size": 256,
                "audio_tools.apollo_model": "apollo_universal_model.ckpt",
            },
        )
        self.assertFalse(settings.process.use_gpu)
        self.assertEqual(settings.mdx.segment_size, 256)
        self.assertEqual(settings.audio_tools.apollo_model, "apollo_universal_model.ckpt")

    def test_apply_overrides_raises_on_unmapped_flat_key(self) -> None:
        from core.settings import Settings

        with self.assertRaises(KeyError):
            model_sweep.apply_overrides(Settings(), {"totally_made_up_key": 1})

    def test_collect_outputs_lists_audio_only(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a (Vocals).wav", "b.flac", "notes.txt", "empty.wav"):
                with open(os.path.join(tmp, name), "wb") as handle:
                    handle.write(b"" if name == "empty.wav" else b"RIFFdata")
            outputs = model_sweep.collect_outputs(tmp)
        names = sorted(os.path.basename(p) for p, _ in outputs)
        self.assertEqual(names, ["a (Vocals).wav", "b.flac"])


class RunChildTests(unittest.TestCase):
    """Covers fix-round-1 findings: crash-path result.json, ok/exit-code parity."""

    def test_run_child_writes_result_json_on_missing_spec(self) -> None:
        """Finding 1: a spec file that can't even be opened must still leave
        a diagnosable result.json next to it, not a bare crash."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "spec.json")  # never created

            rc = model_sweep.run_child(spec_path)

            with open(os.path.join(tmp, "result.json")) as handle:
                result = json.load(handle)

        self.assertEqual(rc, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "FileNotFoundError")
        self.assertEqual(result["outputs"], [])

    def test_run_child_writes_result_json_on_malformed_json(self) -> None:
        """Finding 1: malformed JSON is a diagnosable failure, not a crash."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w") as handle:
                handle.write("{not valid json")

            rc = model_sweep.run_child(spec_path)

            with open(os.path.join(tmp, "result.json")) as handle:
                result = json.load(handle)

        self.assertEqual(rc, 1)
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error_type"])
        self.assertIn("JSONDecodeError", result["error_type"])

    def test_run_child_writes_result_json_when_export_dir_missing_from_spec(self) -> None:
        """Finding 1: a spec that parses but lacks ``export_dir`` still gets
        a result.json (job_dir is derived from spec_path, not export_dir)."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w") as handle:
                json.dump({"kind": "single"}, handle)

            rc = model_sweep.run_child(spec_path)

            with open(os.path.join(tmp, "result.json")) as handle:
                result = json.load(handle)

        self.assertEqual(rc, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "KeyError")

    def test_run_child_reports_ok_false_and_exit_1_on_empty_export_dir(self) -> None:
        """Finding 3: a clean run (no error, not stopped) that writes zero
        audio files must have ``ok`` agree with the non-zero exit code."""
        import json
        import tempfile
        from unittest import mock
        from core.blocking_runner import RunResult
        from core.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            export_dir = os.path.join(tmp, "out")
            spec = {
                "kind": model_sweep.KIND_SINGLE,
                "method": "mdx",
                "model": "test.onnx",
                "overrides": {},
                "settings_path": os.path.join(tmp, "settings.json"),
                "input_path": os.path.join(tmp, "in.wav"),
                "export_dir": export_dir,
                "cpu": True,
                "timeout": 5,
            }
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w") as handle:
                json.dump(spec, handle)

            settings = Settings.defaults()
            settings.process.export_path = export_dir
            record = mock.Mock(id="mdx:test.onnx", family="mdx", method="MDX-Net")
            plan = mock.Mock(diagnostics=[], settings=settings)
            with mock.patch("core.settings.Settings.load", return_value=settings), \
                 mock.patch("core.model_identity.ModelIdentityService.resolve", return_value=record), \
                 mock.patch("core.job_plan.JobResolver.resolve", return_value=plan), \
                 mock.patch("core.blocking_runner.run_blocking", return_value=RunResult(0.1, completed=True)):
                rc = model_sweep.run_child(spec_path)

            with open(os.path.join(tmp, "result.json")) as handle:
                result = json.load(handle)

        self.assertEqual(rc, 1)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["error_type"])
        self.assertFalse(result["stopped"])
        self.assertEqual(result["outputs"], [])

    def test_run_child_reports_ok_true_and_exit_0_when_output_written(self) -> None:
        """Sanity counterpart: a clean run that does write output still passes."""
        import json
        import tempfile
        from unittest import mock
        from core.blocking_runner import RunResult
        from core.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            export_dir = os.path.join(tmp, "out")
            spec = {
                "kind": model_sweep.KIND_SINGLE,
                "method": "mdx",
                "model": "test.onnx",
                "overrides": {},
                "settings_path": os.path.join(tmp, "settings.json"),
                "input_path": os.path.join(tmp, "in.wav"),
                "export_dir": export_dir,
                "cpu": True,
                "timeout": 5,
            }
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w") as handle:
                json.dump(spec, handle)

            def _fake_run_blocking(*_args: object, **_kwargs: object) -> RunResult:
                os.makedirs(export_dir, exist_ok=True)
                with open(os.path.join(export_dir, "out (Vocals).wav"), "wb") as handle:
                    handle.write(b"RIFFdata")
                return RunResult(0.1, completed=True)

            settings = Settings.defaults()
            settings.process.export_path = export_dir
            record = mock.Mock(id="mdx:test.onnx", family="mdx", method="MDX-Net")
            plan = mock.Mock(diagnostics=[], settings=settings)
            with mock.patch("core.settings.Settings.load", return_value=settings), \
                 mock.patch("core.model_identity.ModelIdentityService.resolve", return_value=record), \
                 mock.patch("core.job_plan.JobResolver.resolve", return_value=plan), \
                 mock.patch("core.blocking_runner.run_blocking", side_effect=_fake_run_blocking):
                rc = model_sweep.run_child(spec_path)

            with open(os.path.join(tmp, "result.json")) as handle:
                result = json.load(handle)

        self.assertEqual(rc, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["outputs"]), 1)

    def test_run_child_starts_from_planned_inputs(self) -> None:
        import json
        import tempfile
        from unittest import mock
        from core.blocking_runner import RunResult
        from core.export_naming import OutputNamingContext
        from core.job_plan import PlannedInput
        from core.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            export_dir = os.path.join(tmp, "out")
            spec = {
                "kind": model_sweep.KIND_SINGLE,
                "method": "mdx",
                "model": "test.onnx",
                "overrides": {},
                "settings_path": os.path.join(tmp, "settings.json"),
                "input_path": os.path.join(tmp, "in.wav"),
                "export_dir": export_dir,
                "cpu": True,
                "timeout": 5,
            }
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w") as handle:
                json.dump(spec, handle)

            settings = Settings.defaults()
            settings.process.export_path = export_dir
            planned = PlannedInput(
                path="/plan/clip.wav",
                naming=OutputNamingContext(
                    input_path="/plan/clip.wav",
                    track="clip",
                    track_base="clip",
                    export_directory=export_dir,
                    extension="wav",
                ),
                outputs=(),
            )
            plan = mock.Mock(
                diagnostics=[],
                settings=settings,
                inputs=(planned,),
                output="/plan/out",
            )
            record = mock.Mock(id="mdx:test.onnx", family="mdx", method="MDX-Net")
            captured: dict[str, object] = {}
            fake_runner = mock.Mock()

            def capture_start(paths: object, callbacks: object, **kwargs: object) -> None:
                captured["paths"] = paths
                captured["kwargs"] = kwargs

            fake_runner.start.side_effect = capture_start

            def fake_run_blocking(runner: object, start_runner: Any, **_kwargs: object) -> RunResult:
                start_runner(mock.Mock())
                os.makedirs(export_dir, exist_ok=True)
                with open(os.path.join(export_dir, "out (Vocals).wav"), "wb") as handle:
                    handle.write(b"RIFFdata")
                return RunResult(0.1, completed=True)

            with mock.patch("core.settings.Settings.load", return_value=settings), \
                 mock.patch("core.model_identity.ModelIdentityService.resolve", return_value=record), \
                 mock.patch("core.job_plan.JobResolver.resolve", return_value=plan), \
                 mock.patch("core.job_runner.JobRunner", return_value=fake_runner), \
                 mock.patch("core.blocking_runner.run_blocking", side_effect=fake_run_blocking):
                rc = model_sweep.run_child(spec_path)

        self.assertEqual(rc, 0)
        self.assertEqual(captured["paths"], ["/plan/clip.wav"])
        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
        self.assertEqual(kwargs["planned"], (planned,))
        self.assertEqual(kwargs["planned_output_root"], "/plan/out")
        fake_runner.start_resolved.assert_not_called()

    def test_run_child_ensemble_starts_from_planned_inputs(self) -> None:
        import json
        import tempfile
        from unittest import mock
        from core.blocking_runner import RunResult
        from core.export_naming import OutputNamingContext
        from core.job_plan import PlannedInput
        from core.settings import Settings
        from core.types import ProcessMethod

        with tempfile.TemporaryDirectory() as tmp:
            export_dir = os.path.join(tmp, "out")
            spec = {
                "kind": model_sweep.KIND_ENSEMBLE,
                "method": "ensemble",
                "overrides": {},
                "settings_path": os.path.join(tmp, "settings.json"),
                "input_path": os.path.join(tmp, "in.wav"),
                "export_dir": export_dir,
                "cpu": True,
                "timeout": 5,
            }
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w") as handle:
                json.dump(spec, handle)

            settings = Settings.defaults()
            settings.process.method = ProcessMethod.ENSEMBLE
            settings.process.export_path = export_dir
            planned = PlannedInput(
                path="/plan/mix.wav",
                naming=OutputNamingContext(
                    input_path="/plan/mix.wav",
                    track="mix",
                    track_base="mix",
                    export_directory=export_dir,
                    extension="wav",
                ),
                outputs=(),
            )
            plan = mock.Mock(
                diagnostics=[],
                settings=settings,
                inputs=(planned,),
                output=export_dir,
            )
            captured: dict[str, object] = {}
            fake_runner = mock.Mock()

            def capture_start(paths: object, callbacks: object, **kwargs: object) -> None:
                captured["paths"] = paths
                captured["kwargs"] = kwargs

            fake_runner.start.side_effect = capture_start

            def fake_run_blocking(runner: object, start_runner: Any, **_kwargs: object) -> RunResult:
                start_runner(mock.Mock())
                os.makedirs(export_dir, exist_ok=True)
                with open(os.path.join(export_dir, "out (Vocals).wav"), "wb") as handle:
                    handle.write(b"RIFFdata")
                return RunResult(0.1, completed=True)

            with mock.patch("core.settings.Settings.load", return_value=settings), \
                 mock.patch("core.job_plan.JobResolver.resolve", return_value=plan), \
                 mock.patch("core.job_runner.JobRunner", return_value=fake_runner), \
                 mock.patch("core.blocking_runner.run_blocking", side_effect=fake_run_blocking):
                rc = model_sweep.run_child(spec_path)

        self.assertEqual(rc, 0)
        self.assertEqual(captured["paths"], ["/plan/mix.wav"])
        kwargs = captured["kwargs"]
        assert isinstance(kwargs, dict)
        self.assertEqual(kwargs["planned"], (planned,))
        self.assertEqual(kwargs["planned_output_root"], export_dir)
        fake_runner.start_resolved.assert_not_called()

    def test_run_tool_uses_resolved_audio_plan_and_generic_blocker(self) -> None:
        from unittest import mock
        from core.blocking_runner import RunResult
        from core.settings import Settings

        fake_model_data = mock.Mock(is_model_status=True, extracted_params={"ok": True}, config={})
        fake_repo = mock.Mock(model_hash_table={})
        fake_runner = mock.Mock()
        settings = Settings.defaults()
        settings.audio_tools.apollo_model = "apollo_universal_model.ckpt"
        settings.process.export_path = "/tmp/out"
        plan = mock.Mock(diagnostics=[], settings=settings, output="/tmp/out")
        outcome = RunResult(0.01, stopped=True, error=TimeoutError("timeout"))

        def fake_run_blocking(runner: object, start_runner: Any, **_kwargs: object) -> RunResult:
            start_runner(mock.Mock())
            return outcome

        with mock.patch(
            "core.apollo.ApolloModelData", return_value=fake_model_data
        ), mock.patch(
            "core.audio_tools.AudioToolRunner", return_value=fake_runner
        ), mock.patch(
            "core.audio_plan.AudioJobResolver.resolve", return_value=plan
        ), mock.patch(
            "core.blocking_runner.run_blocking", side_effect=fake_run_blocking
        ), mock.patch(
            "os.makedirs"
        ):
            result = model_sweep._run_tool(settings, "/tmp/in.wav", 0.01, repo=fake_repo)
        self.assertIs(result, outcome)
        fake_runner.start.assert_called_once()
        self.assertEqual(fake_runner.start.call_args.args[0], model_sweep.APOLLO_RESTORE)
        self.assertNotIn("planned", fake_runner.start.call_args.kwargs)
        fake_runner.start_resolved.assert_not_called()


class SpawnChildProcessGroupTests(unittest.TestCase):
    """Fix round 1: a timed-out child must have its whole process group
    killed, not just the immediate process, since it can shell out to
    grandchildren (ffmpeg via pydub, rubberband via ml/pyrb.py) that would
    otherwise survive as orphans. A revert to ``subprocess.run`` +
    ``proc.kill()``/timeout-only-kills-the-child would still return
    ``(None, None, True)`` on timeout, so that alone can't discriminate the
    fix from a revert — this asserts the group kill was actually issued."""

    def test_timeout_kills_the_whole_process_group_and_reaps_it(self) -> None:
        import signal
        import subprocess
        import tempfile
        from unittest import mock

        class FakeProc:
            def __init__(self, argv: Any, env: Any = None, start_new_session: Any = None):
                self.pid = 4242
                self.start_new_session = start_new_session
                self.wait_calls = 0

            def wait(self, timeout: Any = None) -> int:
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)
                return -9

        created: Dict[str, Any] = {}

        def fake_popen(argv: Any, env: Any = None, start_new_session: Any = None) -> Any:
            proc = FakeProc(argv, env=env, start_new_session=start_new_session)
            created["proc"] = proc
            return proc

        killpg_calls: List[Any] = []

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "subprocess.Popen", side_effect=fake_popen
            ), mock.patch(
                "os.getpgid", return_value=9999
            ), mock.patch(
                "os.killpg", side_effect=lambda pgid, sig: killpg_calls.append((pgid, sig))
            ):
                exit_code, result, timed_out = model_sweep.spawn_child(
                    spec={"kind": "single"}, job_dir=tmp, env={}, timeout=1.0
                )

        # The fix: the child is started as its own process-group leader...
        self.assertTrue(created["proc"].start_new_session)
        # ...and on timeout the whole group is killed (not just the child)...
        self.assertEqual(killpg_calls, [(9999, signal.SIGKILL)])
        # ...then reaped so no zombie is left behind.
        self.assertEqual(created["proc"].wait_calls, 2)
        self.assertIsNone(exit_code)
        self.assertIsNone(result)
        self.assertTrue(timed_out)

    def test_timeout_kill_tolerates_a_process_that_already_exited(self) -> None:
        """``os.killpg`` racing an already-reaped process must not raise."""
        import subprocess
        import tempfile
        from unittest import mock

        class FakeProc:
            def __init__(self) -> None:
                self.pid = 4242
                self.wait_calls = 0

            def wait(self, timeout: Any = None) -> int:
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)
                return -9

        proc = FakeProc()

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "subprocess.Popen", return_value=proc
            ), mock.patch(
                "os.getpgid", return_value=9999
            ), mock.patch(
                "os.killpg", side_effect=ProcessLookupError()
            ):
                exit_code, result, timed_out = model_sweep.spawn_child(
                    spec={"kind": "single"}, job_dir=tmp, env={}, timeout=1.0
                )

        self.assertIsNone(exit_code)
        self.assertIsNone(result)
        self.assertTrue(timed_out)


class ParentControlFlowTests(unittest.TestCase):
    def _job(self, **kwargs: Any):
        base = dict(id="mdx:a.ckpt", kind=model_sweep.KIND_SINGLE, method="mdx", model="a.ckpt")
        base.update(kwargs)
        return model_sweep.SweepJob(**base)

    def _spawner(self, results: List[Tuple[Any, Any, bool]]):
        """Returns a fake spawn that pops (exit_code, result_dict, timed_out)."""
        calls: List[Dict[str, Any]] = []

        def spawn(*, spec: Dict[str, Any], job_dir: str, env: Dict[str, str], timeout: float):
            calls.append(spec)
            return results.pop(0)

        return spawn, calls

    def test_passing_job_never_retries(self) -> None:
        ok = {"ok": True, "outputs": [["x.wav", 10]], "error_type": None, "message": ""}
        spawn, calls = self._spawner([(0, ok, False)])
        verdict, _, _ = model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=True,
        )
        self.assertEqual(verdict, model_sweep.PASS)
        self.assertEqual(len(calls), 1)

    def test_oom_retries_on_cpu_and_reports_cpu_ok(self) -> None:
        oom = {
            "ok": False, "outputs": [], "error_type": "OutOfMemoryError",
            "message": "CUDA out of memory",
        }
        ok = {"ok": True, "outputs": [["x.wav", 10]], "error_type": None, "message": ""}
        spawn, calls = self._spawner([(1, oom, False), (0, ok, False)])
        verdict, _, _ = model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=True,
        )
        self.assertEqual(verdict, model_sweep.OOM_CPU_OK)
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[0]["cpu"])
        self.assertTrue(calls[1]["cpu"])

    def test_oom_that_also_fails_on_cpu_reports_the_cpu_failure(self) -> None:
        oom = {
            "ok": False, "outputs": [], "error_type": "OutOfMemoryError",
            "message": "CUDA out of memory",
        }
        broken = {
            "ok": False, "outputs": [], "error_type": "RuntimeError",
            "message": "shape mismatch",
        }
        spawn, _ = self._spawner([(1, oom, False), (1, broken, False)])
        verdict, detail, _ = model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=True,
        )
        self.assertEqual(verdict, "FAIL(RuntimeError)")
        self.assertIn("shape mismatch", detail)

    def test_cpu_retry_disabled_keeps_bare_oom(self) -> None:
        oom = {
            "ok": False, "outputs": [], "error_type": "OutOfMemoryError",
            "message": "CUDA out of memory",
        }
        spawn, calls = self._spawner([(1, oom, False)])
        verdict, _, _ = model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=False,
        )
        self.assertEqual(verdict, model_sweep.OOM)
        self.assertEqual(len(calls), 1)

    def test_no_retry_when_already_on_cpu(self) -> None:
        oom = {
            "ok": False, "outputs": [], "error_type": "OutOfMemoryError",
            "message": "CUDA out of memory",
        }
        spawn, calls = self._spawner([(1, oom, False)])
        model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=True, cpu_retry=True,
        )
        self.assertEqual(len(calls), 1)

    def test_skip_jobs_are_not_spawned(self) -> None:
        spawn, calls = self._spawner([])
        verdict, _detail, _ = model_sweep.run_one(
            self._job(id="composite:ensemble", kind=model_sweep.KIND_SKIP,
                      method=None, model=None, detail="needs two models"),
            spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=True,
        )
        self.assertTrue(verdict.startswith("SKIP"))
        self.assertEqual(calls, [])


class CliTests(unittest.TestCase):
    def test_parser_defaults(self) -> None:
        args = model_sweep.build_parser().parse_args([])
        self.assertEqual(args.timeout, 300.0)
        self.assertFalse(args.cpu)
        self.assertFalse(args.strict)
        self.assertTrue(args.cpu_retry)

    def test_method_filter_accepts_repeats(self) -> None:
        args = model_sweep.build_parser().parse_args(["--method", "mdx", "--method", "vr"])
        self.assertEqual(set(args.method), {"mdx", "vr"})

    def test_no_cpu_retry_flag(self) -> None:
        args = model_sweep.build_parser().parse_args(["--no-cpu-retry"])
        self.assertFalse(args.cpu_retry)


@unittest.skipUnless(
    os.getenv("UVR_MODEL_SWEEP"),
    "local-only: set UVR_MODEL_SWEEP=1 to run every installed model (10-25 min)",
)
class FullSweepTests(unittest.TestCase):
    def test_every_installed_model_starts_and_finishes(self) -> None:
        self.assertEqual(model_sweep.main([]), 0)


if __name__ == "__main__":
    unittest.main()
