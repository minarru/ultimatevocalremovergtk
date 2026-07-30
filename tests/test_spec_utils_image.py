"""Unit tests for ``spec_utils.spectrogram_to_image``."""

from __future__ import annotations

import unittest

import numpy as np

from ml import spec_utils


class SpectrogramToImageTests(unittest.TestCase):
    def test_2d_spectrogram_passes_through(self):
        spec = np.linspace(0.1, 1.0, 12).reshape(3, 4)
        img = spec_utils.spectrogram_to_image(spec)
        self.assertEqual(img.shape, (3, 4))
        self.assertEqual(img.dtype, np.uint8)

    def test_3d_spectrogram_prepends_channel_max(self):
        """A (C, H, W) spec becomes (H, W, C+1) with the max channel first.

        Both the transpose and the max must run on the same array; taking the
        max of the pre-transpose view reduces over W instead of over channels
        and makes the concatenate fail on mismatched shapes.
        """
        spec = np.linspace(0.1, 1.0, 24).reshape(2, 3, 4)
        img = spec_utils.spectrogram_to_image(spec)

        self.assertEqual(img.shape, (3, 4, 3))
        transposed = img[:, :, 1:]
        np.testing.assert_array_equal(img[:, :, 0], transposed.max(axis=2))

    def test_3d_spectrogram_non_square_dims(self):
        """Guards the shape bug specifically: C != H, so a mixed-up axis raises."""
        spec = np.linspace(0.1, 1.0, 2 * 5 * 7).reshape(2, 5, 7)
        self.assertEqual(spec_utils.spectrogram_to_image(spec).shape, (5, 7, 3))


if __name__ == "__main__":
    unittest.main()
