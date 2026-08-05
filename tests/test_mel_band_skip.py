from __future__ import annotations

import inspect
import unittest
from typing import TypedDict, cast

import torch
from torch.nn import ModuleList

from engines.mdx import _filter_init_kwargs
from ml.mel_band_roformer import MelBandRoformer


class TinyMelBandKwargs(TypedDict):
    dim: int
    depth: int
    stereo: bool
    num_stems: int
    time_transformer_depth: int
    freq_transformer_depth: int
    num_bands: int
    dim_head: int
    heads: int
    flash_attn: bool
    dim_freqs_in: int
    stft_n_fft: int
    stft_hop_length: int
    stft_win_length: int
    mask_estimator_depth: int
    match_input_audio_length: bool


class MelBandSkipTests(unittest.TestCase):
    def _tiny_kwargs(self) -> TinyMelBandKwargs:
        return {
            "dim": 8,
            "depth": 2,
            "stereo": True,
            "num_stems": 1,
            "time_transformer_depth": 1,
            "freq_transformer_depth": 1,
            "num_bands": 8,
            "dim_head": 4,
            "heads": 2,
            "flash_attn": False,
            "dim_freqs_in": 65,
            "stft_n_fft": 128,
            "stft_hop_length": 32,
            "stft_win_length": 128,
            "mask_estimator_depth": 1,
            "match_input_audio_length": True,
        }

    def test_msst_kwargs_are_accepted(self) -> None:
        params = inspect.signature(MelBandRoformer.__init__).parameters
        for name in (
            "skip_connection",
            "use_torch_checkpoint",
            "mlp_expansion_factor",
            "linear_transformer_depth",
        ):
            self.assertIn(name, params)

        cfg = {
            "dim": 8,
            "depth": 1,
            "skip_connection": True,
            "use_torch_checkpoint": False,
            "mlp_expansion_factor": 4,
            "linear_transformer_depth": 0,
            "num_bands": 8,
        }
        filtered = _filter_init_kwargs(MelBandRoformer, {**cfg, "stereo": True})
        for name in (
            "skip_connection",
            "use_torch_checkpoint",
            "mlp_expansion_factor",
            "linear_transformer_depth",
        ):
            self.assertIn(name, filtered)

    def test_skip_connection_forward_shape(self) -> None:
        model = MelBandRoformer(**self._tiny_kwargs(), skip_connection=True)
        model.eval()
        with torch.no_grad():
            out = model(torch.randn(1, 2, 512))
        self.assertEqual(tuple(out.shape)[:2], (1, 2))

    def test_skip_with_linear_transformer_depth_forward(self) -> None:
        """linear runs before skip-sum (MSST order); both flags must coexist."""
        model = MelBandRoformer(
            **self._tiny_kwargs(),
            skip_connection=True,
            linear_transformer_depth=1,
        )
        self.assertEqual(len(cast_module_list(model.layers[0])), 3)
        model.eval()
        with torch.no_grad():
            out = model(torch.randn(1, 2, 512))
        self.assertEqual(tuple(out.shape)[:2], (1, 2))


def cast_module_list(layer: object) -> list[object]:
    return list(layer)  # type: ignore[arg-type]