"""Pure-helper tests for the local model sweep. No models, no torch."""

import importlib.util
import os
import sys
import unittest
from typing import Any

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
            ensemble[0].overrides["ensemble_main_stem"], "Vocals/Instrumental"
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
        from types import SimpleNamespace
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            export_dir = os.path.join(tmp, "out")
            spec = {
                "kind": model_sweep.KIND_SINGLE,
                "method": "mdx",
                "model": None,
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

            fake_outcome = SimpleNamespace(error=None, stopped=False)
            with mock.patch(
                "core.headless_run.build_settings", return_value=object()
            ), mock.patch(
                "core.headless_run.run_separation_sync", return_value=fake_outcome
            ):
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
        from types import SimpleNamespace
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            export_dir = os.path.join(tmp, "out")
            spec = {
                "kind": model_sweep.KIND_SINGLE,
                "method": "mdx",
                "model": None,
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

            def _fake_run_separation_sync(*_args: object, **_kwargs: object) -> SimpleNamespace:
                os.makedirs(export_dir, exist_ok=True)
                with open(os.path.join(export_dir, "out (Vocals).wav"), "wb") as handle:
                    handle.write(b"RIFFdata")
                return SimpleNamespace(error=None, stopped=False)

            with mock.patch(
                "core.headless_run.build_settings", return_value=object()
            ), mock.patch(
                "core.headless_run.run_separation_sync",
                side_effect=_fake_run_separation_sync,
            ):
                rc = model_sweep.run_child(spec_path)

            with open(os.path.join(tmp, "result.json")) as handle:
                result = json.load(handle)

        self.assertEqual(rc, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["outputs"]), 1)

    def test_run_tool_force_stops_worker_on_timeout(self) -> None:
        """Finding 2: a timed-out audio tool must be force-stopped so the
        non-daemon worker thread doesn't outlive the child process."""
        from unittest import mock

        fake_model_data = mock.Mock(is_model_status=True, extracted_params={}, config={})
        fake_repo = mock.Mock(model_hash_table={})
        fake_runner = mock.Mock()

        settings = mock.Mock()
        settings.audio_tools.apollo_model = "apollo_universal_model.ckpt"

        with mock.patch(
            "core.apollo.ApolloModelData", return_value=fake_model_data
        ), mock.patch(
            "core.audio_tools.AudioToolRunner", return_value=fake_runner
        ), mock.patch(
            "core.ModelRepository", return_value=fake_repo
        ):
            with self.assertRaises(TimeoutError):
                model_sweep._run_tool(settings, "/tmp/in.wav", 0.01)

        fake_runner.stop.assert_called_once_with(force=True)


if __name__ == "__main__":
    unittest.main()
