"""Smoke tests for Bandit modules."""

import unittest

import torch

from ml.bandit import Bandit, MultiMaskMultiSourceBandSplitRNN


class BanditModuleTests(unittest.TestCase):
    def test_bandit_v2_forward_shape(self) -> None:
        model = Bandit(
            in_channels=1,
            stems=["speech", "music", "sfx"],
            band_type="musical",
            n_bands=64,
            fs=48000,
            n_fft=2048,
            hop_length=512,
        )
        output = model(torch.randn(1, 2, 8192))
        self.assertEqual(output.shape, (1, 3, 2, 8192))

    def test_bandit_plus_forward_shape(self) -> None:
        model = MultiMaskMultiSourceBandSplitRNN(
            in_channel=1,
            stems=["speech", "music", "effects"],
            band_specs="musical",
            n_bands=64,
            fs=44100,
            n_fft=2048,
            hop_length=512,
        )
        output = model(torch.randn(1, 2, 8192))
        self.assertEqual(output.shape, (1, 3, 2, 8192))


if __name__ == "__main__":
    unittest.main()
