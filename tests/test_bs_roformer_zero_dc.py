"""The opt-in upstream DC filter preserves other bins and legacy defaults."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import torch

from engines.mdx_c import filter_init_kwargs
from ml.bs_roformer import BSRoformer
from ml.stft_device import torch_istft


class BSRoformerZeroDcTests(unittest.TestCase):
    def test_config_option_reaches_constructor(self) -> None:
        self.assertEqual(filter_init_kwargs(BSRoformer, {"zero_dc": True}), {"zero_dc": True})

    def test_only_dc_bin_is_removed_for_every_channel_and_stem(self) -> None:
        for stereo, stems in ((False, 1), (True, 1), (True, 2)):
            with self.subTest(stereo=stereo, stems=stems):
                model = BSRoformer(
                    dim=8,
                    depth=1,
                    stereo=stereo,
                    num_stems=stems,
                    time_transformer_depth=1,
                    freq_transformer_depth=1,
                    freqs_per_bands=(16, 16, 16, 17),
                    dim_head=4,
                    heads=2,
                    flash_attn=False,
                    stft_n_fft=128,
                    stft_hop_length=32,
                    stft_win_length=128,
                ).eval()
                self.assertFalse(model.zero_dc)
                audio = torch.randn(1, 2 if stereo else 1, 512) + 2
                with (
                    torch.no_grad(),
                    patch("ml.bs_roformer.torch_istft", wraps=torch_istft) as inverse,
                ):
                    original = model(audio)
                    original_spectrum = inverse.call_args.args[0].clone()
                    model.zero_dc = False
                    torch.testing.assert_close(model(audio), original, rtol=0, atol=0)
                    model.zero_dc = True
                    filtered = model(audio)
                    filtered_spectrum = inverse.call_args.args[0]
                self.assertGreater(original_spectrum[:, 0].abs().max().item(), 0)
                self.assertEqual(torch.count_nonzero(filtered_spectrum[:, 0]).item(), 0)
                torch.testing.assert_close(
                    filtered_spectrum[:, 1:], original_spectrum[:, 1:], rtol=0, atol=0
                )
                expected_spectrum = original_spectrum.clone()
                expected_spectrum[:, 0] = 0
                expected = torch_istft(
                    expected_spectrum,
                    **model.stft_kwargs,
                    window=model.stft_window_fn(),
                    length=512,
                    return_complex=False,
                ).reshape(filtered.shape)
                torch.testing.assert_close(filtered, expected)
