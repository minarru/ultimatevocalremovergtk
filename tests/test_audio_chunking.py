"""Tests for whole-file time slicing and crossfade concat."""

from __future__ import annotations

import unittest

import numpy as np

from core.audio_chunking import (
    clamp_overlap_seconds,
    concat_stems,
    overlap_samples_for,
    slice_mix,
)


class SliceMixTests(unittest.TestCase):
    def test_disabled_returns_single_chunk(self) -> None:
        mix = np.zeros((2, 44100), dtype=np.float64)
        chunks = slice_mix(mix, chunk_seconds=0)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][0], 0)
        self.assertEqual(chunks[0][1], 44100)

    def test_short_mix_is_noop(self) -> None:
        mix = np.zeros((2, 1000), dtype=np.float64)
        chunks = slice_mix(mix, chunk_seconds=10, overlap_seconds=2)
        self.assertEqual(len(chunks), 1)

    def test_overlap_clamp(self) -> None:
        self.assertEqual(clamp_overlap_seconds(10, 100), 5.0 - 1e-6)
        self.assertEqual(clamp_overlap_seconds(0, 2), 0.0)

    def test_multiple_chunks(self) -> None:
        # 3 seconds at 100 Hz with 1s chunks and 0.25s overlap → several slices.
        sr = 100
        mix = np.arange(3 * sr, dtype=np.float64)
        mix = np.stack([mix, mix])
        chunks = slice_mix(mix, sample_rate=sr, chunk_seconds=1.0, overlap_seconds=0.25)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0][1] - chunks[0][0], sr)
        # Final sample of last chunk reaches the end.
        self.assertEqual(chunks[-1][1], mix.shape[1])


class ConcatStemsTests(unittest.TestCase):
    def test_single_part_passthrough(self) -> None:
        part = np.ones((2, 50), dtype=np.float64)
        out = concat_stems([part], overlap_samples=10)
        np.testing.assert_array_equal(out, part)

    def test_crossfade_length(self) -> None:
        left = np.ones((2, 100), dtype=np.float64)
        right = np.full((2, 100), 2.0, dtype=np.float64)
        out = concat_stems([left, right], overlap_samples=20)
        # 100 + 100 - 20
        self.assertEqual(out.shape[1], 180)
        # Mid-crossfade should be between 1 and 2.
        mid = out[0, 90]
        self.assertGreater(mid, 1.0)
        self.assertLess(mid, 2.0)

    def test_overlap_samples_for(self) -> None:
        self.assertEqual(
            overlap_samples_for(sample_rate=44100, chunk_seconds=10, overlap_seconds=2),
            88200,
        )


if __name__ == "__main__":
    unittest.main()
