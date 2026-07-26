"""Tests for peak-limit + min-peak amplification in ``spec_utils.normalize``."""

from __future__ import annotations

import unittest

import numpy as np

from ml.spec_utils import normalize


class NormalizeAmplificationTests(unittest.TestCase):
    def test_peak_limit_when_normalize_enabled(self) -> None:
        wave = np.array([[1.5, -2.0], [0.5, 0.25]], dtype=np.float64)
        out = normalize(wave, is_normalize=True, min_peak=0.0)
        self.assertAlmostEqual(float(np.abs(out).max()), 1.0, places=6)

    def test_no_peak_limit_when_normalize_disabled(self) -> None:
        wave = np.array([[1.5, -2.0]], dtype=np.float64)
        out = normalize(wave, is_normalize=False, min_peak=0.0)
        self.assertAlmostEqual(float(np.abs(out).max()), 2.0, places=6)

    def test_quiet_boost_when_min_peak_set(self) -> None:
        wave = np.array([[0.1, -0.2], [0.05, 0.0]], dtype=np.float64)
        out = normalize(wave, is_normalize=False, min_peak=0.9)
        self.assertAlmostEqual(float(np.abs(out).max()), 0.9, places=6)

    def test_min_peak_zero_is_noop(self) -> None:
        wave = np.array([[0.1, -0.2]], dtype=np.float64)
        out = normalize(wave.copy(), is_normalize=False, min_peak=0.0)
        np.testing.assert_allclose(out, wave)

    def test_normalize_then_amplify_uses_post_limit_peak(self) -> None:
        wave = np.array([[2.0, -1.0]], dtype=np.float64)
        # After peak limit max becomes 1.0, so min_peak=0.9 must not re-scale.
        out = normalize(wave, is_normalize=True, min_peak=0.9)
        self.assertAlmostEqual(float(np.abs(out).max()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
