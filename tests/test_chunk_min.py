"""Chunk Min uses recording-independent windows and preserves real audio tails."""

import tempfile
import unittest
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import numpy as np
import soundfile as sf

from bundled.constants import CHUNK_MIN
from ml.spec_utils import combine_ensemble_waveforms


class ChunkMinTests(unittest.TestCase):
    def combine(self, *members: np.ndarray) -> np.ndarray:
        output, rate = combine_ensemble_waveforms(members, CHUNK_MIN, is_array=True)
        self.assertEqual(rate, 44100)
        return output

    def test_short_quiet_patch_does_not_replace_a_quieter_window(self) -> None:
        # A quiet quarter-second cannot win a one-second window whose mean is louder.
        a = np.full((2, 44100), 0.9)
        a[:, :11025] = 0.1
        b = np.full_like(a, 0.5)
        np.testing.assert_allclose(self.combine(a, b), b)

    def test_appending_audio_does_not_move_existing_decisions(self) -> None:
        a = np.tile(np.where((np.arange(44100) // 4000) % 2, 0.9, 0.1), (2, 1))
        b = np.full_like(a, 0.5)
        short = self.combine(a, b)
        extended = self.combine(np.tile(a, 3), np.tile(b, 3))
        np.testing.assert_array_equal(short[:, :33075], extended[:, :33075])

    def test_model_switch_is_crossfaded(self) -> None:
        t = np.arange(88200) / 88200
        a = np.tile(0.15 + 0.1 * t, (2, 1))
        b = np.tile(-(0.25 - 0.1 * t), (2, 1))
        output = self.combine(a, b)
        np.testing.assert_allclose(output[:, :10000], a[:, :10000])
        np.testing.assert_allclose(output[:, -10000:], b[:, -10000:])
        self.assertLess(float(np.max(np.abs(np.diff(output, axis=1)))), 0.00015)

    def test_missing_tail_never_competes_as_silence(self) -> None:
        short = np.full((2, 7000), 0.1)
        long = np.full((2, 23001), 0.5)
        output = self.combine(short, long)
        self.assertEqual(output.shape, long.shape)
        np.testing.assert_allclose(output[:, :4000], short[:, :4000])
        np.testing.assert_allclose(output[:, 7000:], long[:, 7000:])

    def test_stereo_channels_choose_the_same_member(self) -> None:
        a = np.tile([[0.0], [0.8]], (1, 44100))
        b = np.full_like(a, 0.3)
        np.testing.assert_allclose(self.combine(a, b), b)

    def test_tiny_clip_and_identical_members_keep_samples_and_gain(self) -> None:
        for length in (1, 7, 239, 12001):
            with self.subTest(length=length):
                wave = np.tile(np.linspace(-0.2, 0.2, length), (2, 1))
                original = wave.copy()
                with warnings.catch_warnings():
                    warnings.simplefilter("error", RuntimeWarning)
                    np.testing.assert_array_equal(self.combine(wave, wave.copy()), original)
                np.testing.assert_array_equal(wave, original)

    def test_mono_file_inputs_are_preserved_as_stereo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            a = Path(directory) / "quiet.wav"
            b = Path(directory) / "loud.wav"
            sf.write(a, np.full(5000, 0.125), 44100, subtype="FLOAT")
            sf.write(b, np.full(5000, 0.5), 44100, subtype="FLOAT")
            output, rate = combine_ensemble_waveforms([str(a), str(b)], CHUNK_MIN)
        self.assertEqual(rate, 44100)
        self.assertEqual(output.shape, (2, 5000))
        np.testing.assert_allclose(output, 0.125)

    def test_window_duration_uses_sample_rate(self) -> None:
        from ml.ensemble_chunk_min import combine_chunk_min

        for rate in (8000, 48000):
            with self.subTest(rate=rate):
                a = np.full((2, rate), 0.9)
                a[:, : rate // 4] = 0.1
                b = np.full_like(a, 0.5)
                np.testing.assert_allclose(combine_chunk_min([a, b], rate), b)

    def test_empty_members_do_not_erase_real_audio(self) -> None:
        from ml.ensemble_chunk_min import combine_chunk_min

        wave = np.full((2, 19), 0.3, dtype=np.float32)
        output = combine_chunk_min([np.empty((2, 0), dtype=np.float32), wave], 44100)
        np.testing.assert_array_equal(output, wave)
        self.assertEqual(output.dtype, np.float32)
        self.assertEqual(combine_chunk_min([wave[:, :0]], 44100).shape, (2, 0))

    def test_invalid_member_layout_and_sample_rate_are_rejected(self) -> None:
        from ml.ensemble_chunk_min import combine_chunk_min

        for members, rate in (
            ([], 44100),
            ([np.ones((2, 3))], 0),
            ([np.ones((2, 3)), np.ones((1, 3))], 44100),
        ):
            with self.subTest(rate=rate, members=len(members)):
                with self.assertRaises(ValueError):
                    combine_chunk_min(members, rate)

    def test_invalid_valid_starts_are_rejected(self) -> None:
        from ml.ensemble_chunk_min import combine_chunk_min

        member = np.ones((2, 3))
        for valid_starts in ([], [-1], [4], [1.5], [True]):
            with self.subTest(valid_starts=valid_starts):
                with self.assertRaises(ValueError):
                    combine_chunk_min(
                        [member],
                        44100,
                        valid_starts=cast(Sequence[int], valid_starts),
                    )

    def test_small_improvement_stays_but_large_improvement_switches(self) -> None:
        a = np.full((2, 3 * 44100), 0.5)
        b = np.tile(np.repeat([0.6, 0.475, 0.4], 44100), (2, 1))
        output = self.combine(a, b)
        np.testing.assert_allclose(output[:, 50000:80000], 0.5)
        np.testing.assert_allclose(output[:, 100000:120000], 0.4)

    def test_tie_keeps_current_member_instead_of_first_member(self) -> None:
        a = np.tile(np.repeat([0.6, 0.5], 44100), (2, 1))
        b = np.tile(np.repeat([-0.4, -0.5], 44100), (2, 1))
        np.testing.assert_allclose(self.combine(a, b), b)

    def test_ended_member_switches_even_without_quieter_replacement(self) -> None:
        a = np.full((2, 44100), 0.4)
        b = np.full((2, 88200), 0.5)
        output = self.combine(a, b)
        np.testing.assert_allclose(output[:, 44100:], 0.5)

    def test_invalid_prefix_never_wins_or_enters_crossfade(self) -> None:
        from ml.ensemble_chunk_min import combine_chunk_min

        start = 200
        present = np.full((2, 1000), 0.5, dtype=np.float32)
        delayed_quiet = np.full((2, 1000), 0.1, dtype=np.float32)
        delayed_quiet[:, :start] = 0.0

        output = combine_chunk_min(
            [present, delayed_quiet],
            sample_rate=1000,
            valid_starts=[0, start],
        )

        np.testing.assert_array_equal(output[:, :start], present[:, :start])
        self.assertEqual(float(output[0, start]), 0.5)
        self.assertLess(float(output[0, start + 49]), 0.5)
        np.testing.assert_allclose(output[:, start + 50 :], 0.1)

    def test_uncovered_prefix_is_zero_until_first_valid_member(self) -> None:
        from ml.ensemble_chunk_min import combine_chunk_min

        member = np.full((2, 300), 0.25, dtype=np.float32)

        output = combine_chunk_min([member], 1000, valid_starts=[75])

        np.testing.assert_array_equal(output[:, :75], 0.0)
        np.testing.assert_array_equal(output[:, 75:], member[:, 75:])
