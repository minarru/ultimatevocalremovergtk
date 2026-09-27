"""Tests for whole-file time slicing and crossfade concat."""

from __future__ import annotations

import unittest
from collections.abc import Callable

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
            chunk_count_for_samples(mix.shape[1], chunk_seconds=10, overlap_seconds=2),
            len(chunks),
        )

    def test_matches_slice_mix_for_pulled_back_final_chunk(self) -> None:
        sr = 100
        mix = np.arange(23 * sr, dtype=np.float64)
        mix = np.stack([mix, mix])
        chunks = slice_mix(mix, sample_rate=sr, chunk_seconds=10.0, overlap_seconds=2.0)
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


def _reference_concat(parts: list[np.ndarray], overlaps: list[int]) -> np.ndarray:
    """The original join: pairwise concatenation with a float64 linear crossfade."""
    result = parts[0].astype(np.float64)
    for right, ov in zip(parts[1:], overlaps, strict=True):
        ov = min(ov, result.shape[1], right.shape[1])
        fade_out = np.linspace(1.0, 0.0, ov, dtype=np.float64)
        mixed = result[:, -ov:] * fade_out + right[:, :ov] * (1.0 - fade_out)
        result = np.concatenate([result[:, :-ov], mixed, right[:, ov:]], axis=1)
    return result


def _traced_peak_bytes(fn: Callable[[], object]) -> int:
    import tracemalloc

    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


class ChunkMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        rng = np.random.default_rng(0)
        self.mix = rng.standard_normal((2, 23 * 1000)).astype(np.float32)

    def _chunks(self):
        return slice_mix(self.mix, sample_rate=1000, chunk_seconds=5, overlap_seconds=1)

    def test_chunks_are_views_of_the_mix(self) -> None:
        chunks = self._chunks()
        self.assertGreater(len(chunks), 1)
        for start, end, chunk in chunks:
            self.assertTrue(np.shares_memory(chunk, self.mix))
            np.testing.assert_array_equal(chunk, self.mix[:, start:end])

    def test_concat_matches_the_reference_crossfade_exactly_for_float64(self) -> None:
        chunks = self._chunks()
        parts = [chunk.astype(np.float64) * (i + 1) for i, (_s, _e, chunk) in enumerate(chunks)]
        overlaps = overlaps_for_chunks(chunks)
        np.testing.assert_array_equal(
            concat_stems(parts, overlap_samples=overlaps), _reference_concat(parts, overlaps)
        )

    def test_concat_keeps_float32_parts_float32(self) -> None:
        chunks = self._chunks()
        parts = [chunk * (i + 1) for i, (_s, _e, chunk) in enumerate(chunks)]
        overlaps = overlaps_for_chunks(chunks)
        joined = concat_stems(parts, overlap_samples=overlaps)
        self.assertEqual(joined.dtype, np.float32)
        np.testing.assert_allclose(joined, _reference_concat(parts, overlaps), rtol=0, atol=1e-5)

    def test_concat_allocates_about_one_output(self) -> None:
        from unittest import mock

        chunks = self._chunks()
        parts = [np.ascontiguousarray(chunk) for _s, _e, chunk in chunks]
        overlaps = overlaps_for_chunks(chunks)
        block = 256
        with mock.patch("core.audio_chunking._FADE_BLOCK", block):
            peak = _traced_peak_bytes(lambda: concat_stems(parts, overlap_samples=overlaps))
        # The joined float32 stem, the float64 fade ramp and a few bounded
        # blend blocks, instead of re-copying the accumulated (float64) stem
        # at every join and allocating whole-window temporaries.
        ramp = max(overlaps) * 8
        block_temps = 8 * self.mix.shape[0] * block * 8
        self.assertLess(peak, self.mix.nbytes + ramp + block_temps)


if __name__ == "__main__":
    unittest.main()
