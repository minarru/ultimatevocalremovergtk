from __future__ import annotations

import unittest
from typing import cast

import torch
from torch.nn import ModuleList

from engines.mdx_c import _filter_init_kwargs
from ml.bs_roformer import BSRoformer


class BSRoformerSkipTests(unittest.TestCase):
    def test_skip_kwargs_accepted(self) -> None:
        filtered = _filter_init_kwargs(
            BSRoformer,
            {
                "dim": 8,
                "depth": 1,
                "skip_connection": True,
                "use_torch_checkpoint": False,
                "freqs_per_bands": (2, 2, 2, 2),
                "flash_attn": False,
            },
        )
        self.assertIn("skip_connection", filtered)
        self.assertIn("use_torch_checkpoint", filtered)

    def test_skip_forward_runs(self) -> None:
        model = BSRoformer(
            dim=8,
            depth=2,
            stereo=True,
            time_transformer_depth=1,
            freq_transformer_depth=1,
            freqs_per_bands=(16, 16, 16, 17),
            dim_head=4,
            heads=2,
            flash_attn=False,
            stft_n_fft=128,
            stft_hop_length=32,
            stft_win_length=128,
            skip_connection=True,
        )
        model.eval()
        with torch.no_grad():
            out = model(torch.randn(1, 2, 512))
        self.assertEqual(out.shape[0], 1)

    def test_skip_with_linear_transformer_depth_forward(self) -> None:
        """linear runs before skip-sum (MSST order); both flags must coexist."""
        model = BSRoformer(
            dim=8,
            depth=2,
            stereo=True,
            time_transformer_depth=1,
            freq_transformer_depth=1,
            linear_transformer_depth=1,
            freqs_per_bands=(16, 16, 16, 17),
            dim_head=4,
            heads=2,
            flash_attn=False,
            stft_n_fft=128,
            stft_hop_length=32,
            stft_win_length=128,
            skip_connection=True,
        )
        self.assertEqual(len(cast(ModuleList, model.layers[0])), 3)
        model.eval()
        with torch.no_grad():
            out = model(torch.randn(1, 2, 512))
        self.assertEqual(out.shape[0], 1)
