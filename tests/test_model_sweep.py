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


if __name__ == "__main__":
    unittest.main()
