"""Reviewed September configs keep native outputs distinct from user-facing roles."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from core.model_data import load_mdx_c_config_data
from core.model_manifest import load_model_manifest
from core.model_stem_manifest import resolve_model_stem_semantics
from core.stem_roles import StemProcessingContext, StemReviewStatus

_ROOT = Path(__file__).resolve().parents[1]
_OUTPUTS = {
    "bs_bowed_str2_gilliaaan": (
        ("strings", "instrument.bowed_strings"),
        ("other", "instrument.bowed_strings.removed"),
    ),
    "bs_deeffect_gilliaaan": (("vocals", "effect.effects.removed"), (None, "effect.effects")),
    "bs_invert_clean1_gilliaaan": (("vocals", "vocal.vocals"), (None, "mix.instrumental")),
    "bs_pope_karaoke2_lambda": (
        ("lead", "vocal.lead"),
        (None, "mix.instrumental_with_backing_vocals"),
    ),
    "mbr_karaoke1_gilliaaan": (
        ("lead", "vocal.lead"),
        ("back-instrum", "mix.instrumental_with_backing_vocals"),
    ),
    "mbr_mid_side3_gilliaaan": (("center", "spatial.center"), ("wide", "spatial.side")),
    "mbr_xeno3": (("vocals", "vocal.vocals"), (None, "mix.instrumental")),
}


class SeptemberMvseplessReviewTests(unittest.TestCase):
    def test_configs_and_routes_match_reviewed_outputs(self) -> None:
        registry = load_model_manifest()
        for basename, expected in _OUTPUTS.items():
            with self.subTest(model=basename):
                model_id = f"mdx:{basename}"
                record = registry.models[model_id]
                config_name = f"{basename}_config.yaml"
                config_path = _ROOT / "models/MDX_Net_Models/model_data/mdx_c_configs" / config_name
                data = config_path.read_bytes()
                config = load_mdx_c_config_data(data)
                evidence = record.config_evidence[config_name]
                self.assertEqual(evidence.content_sha256, hashlib.sha256(data).hexdigest())
                self.assertEqual(
                    evidence.training_instruments, tuple(config["training"]["instruments"])
                )
                self.assertEqual(
                    evidence.target_instrument, config["training"].get("target_instrument")
                )
                native = tuple(key for key, _role in expected if key is not None)
                self.assertEqual(config["model"]["num_stems"], len(native))
                semantics = resolve_model_stem_semantics(
                    model_id, native_stems=native, registry=registry.stems
                )
                self.assertEqual(semantics.status, StemReviewStatus.REVIEWED)
                self.assertEqual(
                    tuple(
                        (out.native.raw if out.native else None, str(out.role))
                        for out in semantics.outputs
                    ),
                    expected,
                )

    def test_karaoke_contexts_preserve_native_or_derived_backing_output(self) -> None:
        registry = load_model_manifest()
        for basename, backing_native in (
            ("bs_pope_karaoke2_lambda", None),
            ("mbr_karaoke1_gilliaaan", "back-instrum"),
        ):
            with self.subTest(model=basename):
                native = ("lead",) if backing_native is None else ("lead", backing_native)
                semantics = resolve_model_stem_semantics(
                    f"mdx:{basename}",
                    native_stems=native,
                    context=StemProcessingContext.VOCAL_SPLIT,
                    registry=registry.stems,
                )
                self.assertEqual(semantics.status, StemReviewStatus.REVIEWED)
                primary = next(out for out in semantics.outputs if out.logical_primary)
                self.assertEqual(str(primary.role), "vocal.backing")
                self.assertEqual(primary.native.raw if primary.native else None, backing_native)
