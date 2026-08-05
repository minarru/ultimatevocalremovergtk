"""Smoke tests for the SCNet module."""

import unittest

import torch

from ml.scnet import SCNet, SCNetMasked


class SCNetModuleTests(unittest.TestCase):
    def test_forward_shape(self) -> None:
        model = SCNet(
            sources=["drums", "bass", "other", "vocals"],
            audio_channels=2,
            nfft=4096,
            hop_size=1024,
            win_size=4096,
            normalized=True,
            dims=[4, 32, 64, 128],
            band_SR=[0.175, 0.392, 0.433],
            band_stride=[1, 4, 16],
            band_kernel=[3, 4, 16],
            conv_depths=[3, 2, 1],
            compress=4,
            conv_kernel=3,
            num_dplayer=6,
            expand=1,
        )
        output = model(torch.randn(2, 2, 8192))
        self.assertEqual(output.shape, (2, 4, 2, 8192))


class SCNetMaskedModuleTests(unittest.TestCase):
    def test_forward_shape(self) -> None:
        model = SCNetMasked(
            sources=["drums", "bass", "other", "vocals"],
            audio_channels=2,
            nfft=4096,
            hop_size=1024,
            win_size=4096,
            normalized=True,
            dims=[4, 32, 64, 128],
            band_SR=[0.175, 0.392, 0.433],
            band_stride=[1, 4, 16],
            band_kernel=[3, 4, 16],
            conv_depths=[3, 2, 1],
            compress=4,
            conv_kernel=3,
            num_dplayer=6,
            expand=1,
        )
        output = model(torch.randn(2, 2, 8192))
        self.assertEqual(output.shape, (2, 4, 2, 8192))
        self.assertTrue(hasattr(model, "mask_layer"))
        self.assertTrue(hasattr(model, "pos_embed_f"))


if __name__ == "__main__":
    unittest.main()
