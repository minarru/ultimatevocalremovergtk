"""Tests for whole-file time slicing and crossfade concat."""

from __future__ import annotations

import unittest

import numpy as np

from core.audio_chunking import (
    chunk_count_for_samples,
    clamp_overlap_seconds,
    concat_stems,
    overlap_samples_for,
    overlaps_for_chunks,
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


class ChunkCountForSamplesTests(unittest.TestCase):
    def test_matches_slice_mix_when_chunking_disabled(self) -> None:
        mix = np.zeros((2, 44100), dtype=np.float64)
        chunks = slice_mix(mix, chunk_seconds=0)
        self.assertEqual(
            chunk_count_for_samples(mix.shape[1], chunk_seconds=0),
            len(chunks),
        )

    def test_matches_slice_mix_for_short_mix(self) -> None:
        mix = np.zeros((2, 1000), dtype=np.float64)
        chunks = slice_mix(mix, chunk_seconds=10, overlap_seconds=2)
        self.assertEqual(
            chunk_count_for_samples(
                mix.shape[1], chunk_seconds=10, overlap_seconds=2
            ),
            len(chunks),
        )

    def test_matches_slice_mix_for_pulled_back_final_chunk(self) -> None:
        sr = 100
        mix = np.arange(23 * sr, dtype=np.float64)
        mix = np.stack([mix, mix])
        chunks = slice_mix(
            mix, sample_rate=sr, chunk_seconds=10.0, overlap_seconds=2.0
        )
        self.assertEqual(
            chunk_count_for_samples(
                mix.shape[1],
                sample_rate=sr,
                chunk_seconds=10.0,
                overlap_seconds=2.0,
            ),
            len(chunks),
        )


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

    def test_overlaps_for_chunks_matches_pulled_back_final_chunk(self) -> None:
        # 23s at 100 Hz with 10s chunks / 2s overlap: the final chunk's start
        # gets pulled back so it ends exactly at the mix length, so its
        # overlap with the previous chunk differs from the configured 2s.
        sr = 100
        mix = np.arange(23 * sr, dtype=np.float64)
        mix = np.stack([mix, mix])
        chunks = slice_mix(mix, sample_rate=sr, chunk_seconds=10.0, overlap_seconds=2.0)
        overlaps = overlaps_for_chunks(chunks)
        self.assertEqual(len(overlaps), len(chunks) - 1)
        for i, ov in enumerate(overlaps):
            self.assertEqual(ov, chunks[i][1] - chunks[i + 1][0])

        parts = [chunk[2] for chunk in chunks]
        out = concat_stems(parts, overlap_samples=overlaps)
        # Reassembled length must match the original mix exactly — using a
        # single fixed overlap for every join would duplicate/drop samples
        # at the pulled-back final join.
        self.assertEqual(out.shape[1], mix.shape[1])

    def test_concat_stems_rejects_mismatched_overlap_sequence_length(self) -> None:
        parts = [np.ones((2, 10)), np.ones((2, 10)), np.ones((2, 10))]
        with self.assertRaises(ValueError):
            concat_stems(parts, overlap_samples=[5])


if __name__ == "__main__":
    unittest.main()
