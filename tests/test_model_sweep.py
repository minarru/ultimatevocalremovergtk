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


if __name__ == "__main__":
    unittest.main()
