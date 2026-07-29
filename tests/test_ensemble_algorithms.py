"""Unit tests for ensemble algorithm atoms and Primary/Secondary helpers."""

from __future__ import annotations
import typing

import unittest

import numpy as np

from bundled.constants import (
    AUDIO_AVERAGE,
    CHUNK_MIN,
    ENSEMBLE_ALGORITHMS,
    HYBRID_SPEC,
    MANUAL_ENSEMBLE_OPTIONS,
    MAX_MAG_AVG_PHASE,
    MAX_MIN,
    MAX_SPEC,
    MEDIAN_SPEC,
    MIN_SPEC,
    SOFT_SPEC,
    COMBINE_INPUTS,
)
from core.ensemble_algorithms import (
    format_ensemble_type,
    legacy_pair_values,
    parse_ensemble_type,
)
from ml.spec_utils import ensembling, ensemble_wav


def _pairwise_mag_reduce(algorithm: str, members: typing.Any):
    """Legacy pairwise Max/Min reduce used as a golden reference (equal lengths)."""
    out = members[0].copy()
    for other in members[1:]:
        if algorithm == MIN_SPEC:
            out = np.where(np.abs(other) <= np.abs(out), other, out)
        else:
            out = np.where(np.abs(other) >= np.abs(out), other, out)
    return out


class ParseFormatTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        for primary in (MAX_SPEC, MEDIAN_SPEC, SOFT_SPEC):
            for secondary in (MIN_SPEC, HYBRID_SPEC, CHUNK_MIN):
                formatted = format_ensemble_type(primary, secondary)
                self.assertEqual(parse_ensemble_type(formatted), (primary, secondary))

    def test_legacy_max_min(self) -> None:
        self.assertEqual(parse_ensemble_type(MAX_MIN), (MAX_SPEC, MIN_SPEC))
        self.assertEqual(parse_ensemble_type("Max Spec/Min Spec"), (MAX_SPEC, MIN_SPEC))

    def test_single_token_duplicates(self) -> None:
        self.assertEqual(parse_ensemble_type(MEDIAN_SPEC), (MEDIAN_SPEC, MEDIAN_SPEC))

    def test_unknown_falls_back(self) -> None:
        self.assertEqual(parse_ensemble_type("Not A Real/Also Fake"), (MAX_SPEC, MIN_SPEC))

    def test_legacy_pairs_still_listed(self) -> None:
        pairs = legacy_pair_values()
        self.assertIn(MAX_MIN, pairs)
        self.assertTrue(all("/" in p for p in pairs))

    def test_manual_options_include_new_atoms(self) -> None:
        for atom in ENSEMBLE_ALGORITHMS:
            self.assertIn(atom, MANUAL_ENSEMBLE_OPTIONS)
        self.assertIn(COMBINE_INPUTS, MANUAL_ENSEMBLE_OPTIONS)


class EnsemblingAtomTests(unittest.TestCase):
    def setUp(self) -> None:
        rng = np.random.default_rng(0)
        shape = (2, 8, 16)
        self.a = (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)).astype(np.complex128)
        self.b = (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)).astype(np.complex128)

    def test_max_min_match_pairwise(self) -> None:
        members = [self.a, self.b]
        np.testing.assert_array_equal(
            ensembling(MAX_SPEC, members),
            _pairwise_mag_reduce(MAX_SPEC, members),
        )
        np.testing.assert_array_equal(
            ensembling(MIN_SPEC, members),
            _pairwise_mag_reduce(MIN_SPEC, members),
        )

    def test_median_middle_of_magnitude_ladder(self) -> None:
        phase = 0.4
        base = np.ones((2, 4, 6), dtype=np.complex128) * np.exp(1j * phase)
        low, mid, high = base * 1.0, base * 2.0, base * 3.0
        out = ensembling(MEDIAN_SPEC, [low, mid, high])
        np.testing.assert_allclose(np.abs(out), 2.0, atol=1e-9)
        np.testing.assert_allclose(np.angle(out), phase, atol=1e-9)

    def test_soft_weights_sum_and_equal_near_average(self) -> None:
        twin_a = np.full((2, 4, 6), 1.0 + 1.0j, dtype=np.complex128)
        twin_b = twin_a.copy()
        out = ensembling(SOFT_SPEC, [twin_a, twin_b])
        avg = 0.5 * (twin_a + twin_b)
        np.testing.assert_allclose(out, avg, atol=1e-9)

        # Unequal members: Soft Spec stays a convex combination (finite, same shape).
        out2 = ensembling(SOFT_SPEC, [self.a, self.b])
        self.assertEqual(out2.shape, self.a.shape)
        self.assertTrue(np.isfinite(out2).all())

        # Agreement weights (softmax over members) sum to 1 per bin.
        from ml.spec_utils import _softmax_weights

        stack = np.stack([self.a, self.b], axis=0)
        mags = np.abs(stack)
        mean_mag = np.mean(mags, axis=0, keepdims=True)
        var = np.var(mags, axis=0, keepdims=True)
        logits = -((mags - mean_mag) ** 2) / (var + 1e-8)
        weights = _softmax_weights(logits, axis=0)
        np.testing.assert_allclose(weights.sum(axis=0), np.ones(self.a.shape), atol=1e-9)

    def test_max_mag_avg_phase(self) -> None:
        # Same magnitudes, opposite phases → Mag matches Max; phase is not raw Max.
        mag = np.full((2, 3, 4), 2.0)
        a = mag * np.exp(1j * 0.0)
        b = mag * np.exp(1j * np.pi)
        out = ensembling(MAX_MAG_AVG_PHASE, [a, b])
        max_out = ensembling(MAX_SPEC, [a, b])
        np.testing.assert_allclose(np.abs(out), np.abs(max_out), atol=1e-9)
        # Mean of unit vectors at 0 and π is ~0 → unstable angle; magnitudes still Max.
        # Use a clearer phase disagreement with unequal magnitudes.
        a2 = np.full((2, 3, 4), 3.0) * np.exp(1j * 0.2)
        b2 = np.full((2, 3, 4), 1.0) * np.exp(1j * 1.2)
        out2 = ensembling(MAX_MAG_AVG_PHASE, [a2, b2])
        max2 = ensembling(MAX_SPEC, [a2, b2])
        np.testing.assert_allclose(np.abs(out2), np.abs(max2), atol=1e-9)
        self.assertFalse(np.allclose(np.angle(out2), np.angle(max2)))

    def test_hybrid_is_mean_of_max_and_min(self) -> None:
        max_out = ensembling(MAX_SPEC, [self.a, self.b])
        min_out = ensembling(MIN_SPEC, [self.a, self.b])
        hybrid = ensembling(HYBRID_SPEC, [self.a, self.b])
        np.testing.assert_allclose(hybrid, 0.5 * (max_out + min_out), atol=1e-9)

    def test_pad_does_not_truncate_longer_member(self) -> None:
        short = self.a[:, :, :8]
        long = self.b
        out = ensembling(MAX_SPEC, [short, long])
        self.assertEqual(out.shape[2], long.shape[2])

    def test_chunk_min_picks_quieter_region(self) -> None:
        # Time-major stereo: member 0 quiet in first half, member 1 quiet in second.
        t = 480  # divisible by default split_size=240
        loud = np.ones((t, 2), dtype=np.float64)
        quiet = np.full((t, 2), 0.01, dtype=np.float64)
        member0 = np.concatenate([quiet[: t // 2], loud[t // 2 :]], axis=0)
        member1 = np.concatenate([loud[: t // 2], quiet[t // 2 :]], axis=0)
        out = ensemble_wav([member0, member1], split_size=2)
        self.assertEqual(out.shape, (t, 2))
        self.assertLess(np.abs(out[: t // 2]).mean(), 0.05)
        self.assertLess(np.abs(out[t // 2 :]).mean(), 0.05)

    def test_average_constant_still_listed(self) -> None:
        self.assertEqual(AUDIO_AVERAGE, "Average")
        self.assertIn(AUDIO_AVERAGE, ENSEMBLE_ALGORITHMS)


if __name__ == "__main__":
    unittest.main()
