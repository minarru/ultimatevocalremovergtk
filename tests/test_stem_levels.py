import unittest
from collections.abc import Callable

import numpy as np

from core.stem_levels import (
    apply_stem_level_options,
    export_format_can_clip,
    match_gain_to_mix,
    peak_limit_gain,
    scale_to_peak_limit,
)


class MatchMixTests(unittest.TestCase):
    def test_match_gain_recovers_known_scale(self):
        rng = np.random.default_rng(0)
        mix = rng.normal(scale=0.2, size=(2, 8000))
        stems = {
            "a": mix * 0.4,
            "b": mix * 0.6,
        }
        # Make stems systematically hot vs mix.
        hot = {key: value * 2.0 for key, value in stems.items()}
        summed = hot["a"] + hot["b"]
        gain = match_gain_to_mix(summed, mix)
        self.assertAlmostEqual(gain, 0.5, places=5)

    def test_apply_match_mix_scales_all_stems_equally(self):
        mix = np.ones((2, 1000)) * 0.5
        stems = {
            "drums": np.ones((2, 1000)) * 0.5,
            "vocals": np.ones((2, 1000)) * 0.5,
        }
        adjusted, messages = apply_stem_level_options(
            stems, mix, match_mix_level=True, prevent_export_clipping=False
        )
        self.assertTrue(any("Matched stem levels" in msg for msg in messages))
        np.testing.assert_allclose(adjusted["drums"] + adjusted["vocals"], mix, atol=1e-6)


class PreventClippingTests(unittest.TestCase):
    def test_shared_peak_limit_preserves_relative_levels(self):
        stems = {
            "loud": np.array([[1.5, -1.5]], dtype=np.float64),
            "quiet": np.array([[0.75, -0.75]], dtype=np.float64),
        }
        gain = peak_limit_gain(stems, peak_limit=1.0)
        self.assertAlmostEqual(gain, 1.0 / 1.5, places=6)
        adjusted, messages = apply_stem_level_options(
            stems, None, match_mix_level=False, prevent_export_clipping=True
        )
        self.assertTrue(any("prevent export clipping" in msg for msg in messages))
        self.assertAlmostEqual(float(np.max(np.abs(adjusted["loud"]))), 1.0, places=6)
        self.assertAlmostEqual(float(np.max(np.abs(adjusted["quiet"]))), 0.5, places=6)

    def test_scale_to_peak_limit_noop_when_safe(self):
        audio = np.array([0.25, -0.5], dtype=np.float64)
        out, gain = scale_to_peak_limit(audio)
        self.assertEqual(gain, 1.0)
        np.testing.assert_array_equal(out, audio)


class FormatClipTests(unittest.TestCase):
    def test_float_wav_skips_clip_guard(self):
        self.assertFalse(export_format_can_clip("WAV", "32-bit Float"))
        self.assertFalse(export_format_can_clip("WAV", "64-bit Float"))
        self.assertTrue(export_format_can_clip("WAV", "PCM_16"))
        self.assertTrue(export_format_can_clip("FLAC", "PCM_16"))
        self.assertTrue(export_format_can_clip("MP3", "320k"))
        self.assertTrue(export_format_can_clip("OPUS", "192k"))


def _traced_peak_bytes(fn: Callable[[], object]) -> int:
    import tracemalloc

    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


class LevelMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        rng = np.random.default_rng(0)
        self.stem = (rng.standard_normal((2, 1_000_000)) * 0.1).astype(np.float32)
        self.stem[1, 1234] = -4.0  # the peak is negative

    def test_peak_gain_reads_the_stem_without_copies(self) -> None:
        gain = peak_limit_gain({"a": self.stem, "b": self.stem * 0.5})
        self.assertAlmostEqual(gain, 0.25, places=7)
        stems = {"a": self.stem}
        peak = _traced_peak_bytes(lambda: peak_limit_gain(stems))
        self.assertLess(peak, self.stem.nbytes * 0.05)

    def test_scaling_keeps_float32(self) -> None:
        out, gain = scale_to_peak_limit(self.stem)
        self.assertEqual(out.dtype, np.float32)
        self.assertAlmostEqual(gain, 0.25, places=7)
        np.testing.assert_allclose(out, self.stem.astype(np.float64) * 0.25, rtol=1e-6)

    def test_mix_gain_matches_float64_least_squares_in_bounded_memory(self) -> None:
        rng = np.random.default_rng(1)
        mix = (self.stem * 0.8 + rng.standard_normal(self.stem.shape) * 0.01).astype(np.float32)
        s64, m64 = self.stem.astype(np.float64).ravel(), mix.astype(np.float64).ravel()
        expected = float(np.dot(s64, m64) / np.dot(s64, s64))
        self.assertAlmostEqual(match_gain_to_mix(self.stem, mix), expected, places=10)
        peak = _traced_peak_bytes(lambda: match_gain_to_mix(self.stem, mix))
        # Bounded float64 blocks, not float64 copies of both arrays (4x a stem).
        self.assertLess(peak, self.stem.nbytes / 2)


if __name__ == "__main__":
    unittest.main()
