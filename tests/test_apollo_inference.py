"""Tests for Apollo restore helpers."""

import unittest

import torch

from ml.apollo_inference import _getWindowingArray


class ApolloWindowTests(unittest.TestCase):
    def test_fade_ramps_are_monotonic(self) -> None:
        window = _getWindowingArray(1000, 100)
        fadein = window[:100]
        fadeout = window[-100:]
        middle = window[100:-100]
        self.assertAlmostEqual(float(fadein[0]), 0.0, places=5)
        self.assertAlmostEqual(float(fadein[-1]), 1.0, places=5)
        self.assertTrue(torch.all(fadein[1:] >= fadein[:-1]))
        self.assertAlmostEqual(float(fadeout[0]), 1.0, places=5)
        self.assertAlmostEqual(float(fadeout[-1]), 0.0, places=5)
        self.assertTrue(torch.all(fadeout[1:] <= fadeout[:-1]))
        self.assertTrue(torch.allclose(middle, torch.ones_like(middle)))

    def test_zero_fade_is_all_ones(self) -> None:
        window = _getWindowingArray(64, 0)
        self.assertTrue(torch.allclose(window, torch.ones_like(window)))


if __name__ == "__main__":
    unittest.main()
