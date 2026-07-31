"""Tests for Apollo checkpoint loading (UVR envelope + Lightning)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import torch
import torch.nn as nn

from ml.apollo_model_data.base_model import BaseModel


class _TinyApollo(BaseModel):
    def __init__(self, sr: int = 44100, win: int = 20, feature_dim: int = 4, layer: int = 1) -> None:
        super().__init__(sample_rate=sr)
        self.lin = nn.Linear(feature_dim, feature_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # pragma: no cover - unused
        return self.lin(x)

    def get_model_args(self) -> dict:
        return {}


class ApolloFromPretrainTests(unittest.TestCase):
    def test_uvr_envelope_uses_model_name(self) -> None:
        model = _TinyApollo()
        envelope = {
            "model_name": "TinyApollo",
            "state_dict": model.state_dict(),
        }
        with patch("ml.apollo_model_data.base_model.load_torch_checkpoint", return_value=envelope):
            with patch("ml.apollo_model_data.get", return_value=_TinyApollo) as get_mock:
                loaded = BaseModel.from_pretrain("dummy.ckpt", sr=44100, feature_dim=4)
        get_mock.assert_called_once_with("TinyApollo")
        self.assertIsInstance(loaded, _TinyApollo)

    def test_lightning_checkpoint_strips_audio_model_prefix(self) -> None:
        model = _TinyApollo()
        weights = {f"audio_model.{k}": v for k, v in model.state_dict().items()}
        lightning = {
            "epoch": 54,
            "pytorch-lightning_version": "2.0.0",
            "state_dict": weights,
        }
        with patch("ml.apollo_model_data.base_model.load_torch_checkpoint", return_value=lightning):
            with patch("ml.apollo_model_data.get", return_value=_TinyApollo) as get_mock:
                loaded = BaseModel.from_pretrain(
                    "epoch.ckpt", sr=44100, win=20, feature_dim=4, layer=1
                )
        get_mock.assert_called_once_with("Apollo")
        self.assertIsInstance(loaded, _TinyApollo)
        for key, tensor in model.state_dict().items():
            self.assertTrue(torch.equal(loaded.state_dict()[key], tensor))

    def test_lightning_ignores_unknown_audio_model_keys(self) -> None:
        model = _TinyApollo()
        weights = {f"audio_model.{k}": v for k, v in model.state_dict().items()}
        weights["audio_model.net.99.extra.weight"] = torch.ones(2, 2)
        lightning = {"state_dict": weights}
        with patch("ml.apollo_model_data.base_model.load_torch_checkpoint", return_value=lightning):
            with patch("ml.apollo_model_data.get", return_value=_TinyApollo):
                loaded = BaseModel.from_pretrain("epoch.ckpt", feature_dim=4)
        self.assertNotIn("net.99.extra.weight", loaded.state_dict())


class MdxCPrimarySelectTests(unittest.TestCase):
    def test_falls_back_when_global_stem_missing(self) -> None:
        from core.model_data import _mdx_c_primary_for_select

        stems = ["drums", "bass", "other", "vocals"]
        self.assertEqual(_mdx_c_primary_for_select(stems, "Instrumental"), "vocals")
        self.assertEqual(_mdx_c_primary_for_select(stems, "drums"), "drums")
        self.assertEqual(
            _mdx_c_primary_for_select(["Drums", "Bass", "Other", "Vocals"], "Instrumental"),
            "Vocals",
        )


if __name__ == "__main__":
    unittest.main()
