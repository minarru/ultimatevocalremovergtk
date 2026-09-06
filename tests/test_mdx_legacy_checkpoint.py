"""Legacy checkpoint layer counts survive lint-driven constructor renames."""

import tempfile
import unittest
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import torch

from engines.mdx import SeperateMDX
from ml.mdxnet import ConvTDFNet


class LegacyCheckpointTests(unittest.TestCase):
    def test_engine_loads_legacy_layer_key_and_weights(self) -> None:
        params: dict[str, Any] = dict(
            target_name="vocals", lr=0.001, optimizer="adamw", dim_c=4,
            dim_f=8, dim_t=8, n_fft=16, hop_length=4, num_blocks=2,
            num_layers=1, g=4, k=3, bn=2, bias=True, overlap=2,
        )
        model = ConvTDFNet(**params)
        params["l"] = params.pop("num_layers")
        checkpoint = {
            "hyper_parameters": params, "state_dict": model.state_dict(),
            "pytorch-lightning_version": version("pytorch-lightning"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.ckpt"
            torch.save(checkpoint, path)
            state = SimpleNamespace(
                primary_model_name=None, model_cache_key="test:legacy",
                model_display_label="Legacy", is_mdx_ckpt=True,
                model_path=str(path), device=torch.device("cpu"),
                start_inference_console_write=Mock(), write_to_console=Mock(),
                running_inference_console_write=Mock(), audio_file="unused.wav",
            )
            # Stop at the audio boundary, after the real checkpoint load.
            with patch("engines.model_weight_cache.get_weight_cache") as cache:
                cache.return_value.get.return_value = None
                with patch("engines.mdx.prepare_mix", side_effect=InterruptedError("loaded")):
                    with self.assertRaisesRegex(InterruptedError, "loaded"):
                        SeperateMDX.seperate(cast(Any, state))
            loaded = cast(Any, state).model_run
            self.assertEqual(loaded.l, 1)
            self.assertFalse(loaded.training)
            self.assertEqual(loaded.state_dict().keys(), model.state_dict().keys())
            for name, value in model.state_dict().items():
                torch.testing.assert_close(loaded.state_dict()[name], value)
