import unittest

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


if __name__ == "__main__":
    unittest.main()
