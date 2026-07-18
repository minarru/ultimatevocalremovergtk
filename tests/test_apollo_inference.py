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

    def test_clamped_fade_keeps_start_finish_ramps(self) -> None:
        """Unclamped fade overrides must not wipe the window to all ones."""
        import ml.apollo_inference as apollo

        C = 100
        fade_size = max(0, min(int(3 * 44100), C // 2))  # clamps to 50
        middle = apollo._getWindowingArray(C, fade_size)
        start = middle.clone()
        finish = middle.clone()
        if fade_size > 0:
            start[:fade_size] = 1
            finish[-fade_size:] = 1
        self.assertAlmostEqual(float(start[0]), 1.0, places=5)
        self.assertLess(float(start[-1]), 1.0)
        self.assertAlmostEqual(float(finish[-1]), 1.0, places=5)
        self.assertLess(float(finish[0]), 1.0)


if __name__ == "__main__":
    unittest.main()
