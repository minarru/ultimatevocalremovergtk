"""HyperACE segmentation branch for BS-Roformer.

The checkpoints for these models carry a ``mask_estimators.N.segm.*`` subtree
that plain BSRoformer has no home for. Key parity against a real checkpoint is
the definitive test; the shape tests below need no weights at all.
"""

import os
import unittest
from typing import Any

_REPO = os.path.dirname(os.path.dirname(__file__))
_CKPT = os.path.join(_REPO, "models", "MDX_Net_Models", "bs_inst_hyperace2_unwa.ckpt")
_CONFIG = os.path.join(
    _REPO, "models", "MDX_Net_Models", "model_data", "mdx_c_configs",
    "bs_inst_hyperace2_unwa_config.yaml",
)


class SegmModelShapeTests(unittest.TestCase):
    """``MaskEstimator`` feeds it (B, dim, T, bands) and wants (B, 4, T, bins)."""

    def test_maps_band_features_to_full_resolution_bins(self) -> None:
        import torch

        from ml.hyperace import SegmModel

        model = SegmModel(in_bands=16, in_dim=32, out_bins=64, base_channels=8).eval()
        with torch.no_grad():
            out = model(torch.randn(1, 32, 64, 16))
        self.assertEqual(out.shape[0], 1)
        self.assertEqual(out.shape[1], 4)
        self.assertEqual(out.shape[3], 64)

    def test_output_is_finite(self) -> None:
        import torch

        from ml.hyperace import SegmModel

        model = SegmModel(in_bands=16, in_dim=32, out_bins=64, base_channels=8).eval()
        with torch.no_grad():
            out = model(torch.randn(1, 32, 64, 16))
        self.assertTrue(bool(torch.isfinite(out).all()))


class VariantDetectionTests(unittest.TestCase):
    """Upstream ships three sources; only the packaged v2-inst yaml carries a
    ``hyperace2`` flag, so the checkpoint's own keys are the reliable signal."""

    def test_v2_is_recognised_by_its_upsample_out_conv(self) -> None:
        from ml.hyperace import hyperace_variant_from_state_dict

        keys = [
            "mask_estimators.0.segm.backbone.stem.dwconv.weight",
            "mask_estimators.0.segm.upsample_head.block1.conv.dwconv.weight",
            "mask_estimators.0.segm.upsample_head.block1.out_conv.blocks.0.tfc1.0.weight",
        ]
        self.assertEqual(hyperace_variant_from_state_dict(keys), "v2")

    def test_v1_has_segm_but_no_out_conv(self) -> None:
        from ml.hyperace import hyperace_variant_from_state_dict

        keys = [
            "mask_estimators.0.segm.backbone.stem.dwconv.weight",
            "mask_estimators.0.segm.upsample_head.block1.conv.dwconv.weight",
        ]
        self.assertEqual(hyperace_variant_from_state_dict(keys), "v1")

    def test_a_plain_bs_roformer_checkpoint_has_no_variant(self) -> None:
        from ml.hyperace import hyperace_variant_from_state_dict

        self.assertIsNone(
            hyperace_variant_from_state_dict(["mask_estimators.0.to_freqs.0.0.0.weight"])
        )


class V1VariantTests(unittest.TestCase):
    """Published v1 weights: 1097 keys total, 398 under segm, no ``out_conv``."""

    def _segm(self):
        from ml.hyperace import SegmModel

        return SegmModel(in_bands=62, in_dim=256, out_bins=1025, variant="v1")

    def test_v1_parameter_count_matches_the_published_checkpoint(self) -> None:
        self.assertEqual(len(self._segm().state_dict()), 398)

    def test_v1_upsample_head_has_no_out_conv(self) -> None:
        self.assertFalse(any("out_conv" in k for k in self._segm().state_dict()))

    def test_v2_parameter_count_matches_the_published_checkpoint(self) -> None:
        from ml.hyperace import SegmModel

        model = SegmModel(in_bands=62, in_dim=256, out_bins=1025, variant="v2")
        self.assertEqual(len(model.state_dict()), 471)


@unittest.skipUnless(os.path.isfile(_CONFIG), "HyperACE config not installed")
class BuildDetectionTests(unittest.TestCase):
    """Upstream's own yamls declare no flag, so the build must follow the weights."""

    def _config(self, *, flag: bool):
        from ml_collections import ConfigDict

        from core.model_data import load_mdx_c_config

        raw = load_mdx_c_config(_CONFIG)
        raw.pop("hyperace2", None)
        if flag:
            raw["hyperace2"] = True
        return ConfigDict(raw)

    def _segm_keys(self, model: Any) -> list:
        return [k for k in model.state_dict() if ".segm." in k]

    def test_flagless_config_builds_plain_without_checkpoint_keys(self) -> None:
        from engines.mdx_c import _build_mdx_c_model

        model = _build_mdx_c_model(self._config(flag=False))
        self.assertEqual(self._segm_keys(model), [])

    def test_checkpoint_keys_enable_the_branch_without_any_flag(self) -> None:
        from engines.mdx_c import _build_mdx_c_model

        model = _build_mdx_c_model(
            self._config(flag=False),
            state_dict_keys=[
                "mask_estimators.0.segm.backbone.stem.dwconv.weight",
                "mask_estimators.0.segm.upsample_head.block1.out_conv.blocks.0.tfc1.0.weight",
            ],
        )
        self.assertEqual(len(self._segm_keys(model)), 471)

    def test_v1_checkpoint_keys_select_the_v1_head(self) -> None:
        from engines.mdx_c import _build_mdx_c_model

        model = _build_mdx_c_model(
            self._config(flag=False),
            state_dict_keys=[
                "mask_estimators.0.segm.backbone.stem.dwconv.weight",
                "mask_estimators.0.segm.upsample_head.block1.conv.dwconv.weight",
            ],
        )
        self.assertEqual(len(self._segm_keys(model)), 398)

    def test_the_packaged_flag_still_works_on_its_own(self) -> None:
        from engines.mdx_c import _build_mdx_c_model

        model = _build_mdx_c_model(self._config(flag=True))
        self.assertEqual(len(self._segm_keys(model)), 471)


class MaskEstimatorWiringTests(unittest.TestCase):
    def test_segm_absent_unless_hyperace_is_requested(self) -> None:
        from ml.bs_roformer import MaskEstimator

        plain = MaskEstimator(dim=16, dim_inputs=(4, 4), depth=1)
        self.assertFalse(any("segm" in k for k in plain.state_dict()))

    def test_segm_present_when_hyperace_is_requested(self) -> None:
        from ml.bs_roformer import MaskEstimator

        with_ace = MaskEstimator(dim=16, dim_inputs=(4, 4), depth=1, hyperace=True)
        self.assertTrue(any("segm" in k for k in with_ace.state_dict()))

    def test_hyperace_adds_its_output_to_the_band_mlp_result(self) -> None:
        """The segm branch is additive; shape must survive it unchanged."""
        import torch

        from ml.bs_roformer import MaskEstimator

        dim_inputs = tuple([8] * 16)
        plain = MaskEstimator(dim=16, dim_inputs=dim_inputs, depth=1).eval()
        with_ace = MaskEstimator(
            dim=16, dim_inputs=dim_inputs, depth=1, hyperace=True
        ).eval()
        x = torch.randn(1, 64, 16, 16)
        with torch.no_grad():
            self.assertEqual(plain(x).shape, with_ace(x).shape)


@unittest.skipUnless(
    os.path.isfile(_CKPT) and os.path.isfile(_CONFIG),
    "HyperACE checkpoint not installed (weights are gitignored)",
)
class CheckpointParityTests(unittest.TestCase):
    """The real bar: every checkpoint key has a home, and none is left over."""

    @classmethod
    def setUpClass(cls) -> None:
        import torch
        from ml_collections import ConfigDict

        from core.model_data import load_mdx_c_config
        from engines.mdx_c import _build_mdx_c_model

        cls.config = ConfigDict(load_mdx_c_config(_CONFIG))
        cls.model = _build_mdx_c_model(cls.config)
        raw = torch.load(_CKPT, map_location="cpu", weights_only=True)
        cls.checkpoint = raw.get("state_dict", raw)

    def test_state_dict_loads_strictly(self) -> None:
        self.model.load_state_dict(self.checkpoint, strict=True)

    def test_no_key_is_missing_or_unexpected(self) -> None:
        mine = set(self.model.state_dict())
        theirs = set(self.checkpoint)
        self.assertEqual(sorted(theirs - mine), [], "checkpoint keys with no home")
        self.assertEqual(sorted(mine - theirs), [], "module keys absent from checkpoint")

    def test_every_shape_agrees(self) -> None:
        mine = self.model.state_dict()
        bad = [
            k for k, v in self.checkpoint.items()
            if k in mine and tuple(mine[k].shape) != tuple(v.shape)
        ]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
