"""HyperACE segmentation branch for BS-Roformer.

The checkpoints for these models carry a ``mask_estimators.N.segm.*`` subtree
that plain BSRoformer has no home for. Key parity against a real checkpoint is
the definitive test; the shape tests below need no weights at all.
"""

import os
import unittest

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
        from engines.mdx import _build_mdx_c_model

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
