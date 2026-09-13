from __future__ import annotations

import unittest
from collections.abc import Sequence
from typing import cast
from unittest.mock import patch

import numpy as np

import ml.ensemble_spectral as ensemble_spectral
from bundled.constants import (
    AUDIO_AVERAGE,
    HYBRID_SPEC,
    MAX_MAG_AVG_PHASE,
    MAX_SPEC,
    MEDIAN_SPEC,
    MIN_SPEC,
    SOFT_SPEC,
)
from ml.ensemble_spectral import combine_spectra


def _constant(value: complex, frames: int = 4) -> np.ndarray:
    return np.full((2, 3, frames), value, dtype=np.complex128)


class CombineSpectraValidationTests(unittest.TestCase):
    def test_rejects_empty_or_malformed_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            combine_spectra(MAX_SPEC, [])
        with self.assertRaisesRegex(ValueError, "complex"):
            combine_spectra(MAX_SPEC, [np.ones((2, 3, 4))])
        with self.assertRaisesRegex(ValueError, "three-dimensional"):
            combine_spectra(MAX_SPEC, [np.ones((2, 4), dtype=np.complex64)])
        with self.assertRaisesRegex(ValueError, "channel and frequency"):
            combine_spectra(MAX_SPEC, [_constant(1), np.ones((1, 3, 4), dtype=np.complex128)])
        invalid = _constant(1)
        invalid[0, 0, 0] = np.nan + 0j
        with self.assertRaisesRegex(ValueError, "finite"):
            combine_spectra(MAX_SPEC, [invalid])

    def test_rejects_unknown_algorithm_and_invalid_controls(self) -> None:
        member = _constant(1)
        with self.assertRaisesRegex(ValueError, "unknown algorithm"):
            combine_spectra("loudest", [member])
        for weights, message in (
            ([0.0], "positive total"),
            ([-1.0], "non-negative"),
            ([np.inf], "finite"),
        ):
            with self.subTest(weights=weights):
                with self.assertRaisesRegex(ValueError, message):
                    combine_spectra(MAX_SPEC, [member], weights=weights)
        for starts in ([-1], [5]):
            with self.subTest(valid_starts=starts):
                with self.assertRaisesRegex(ValueError, "valid_starts"):
                    combine_spectra(MAX_SPEC, [member], valid_starts=starts)
        for smoothing in (-0.1, 4.1):
            with self.subTest(smoothing=smoothing):
                with self.assertRaisesRegex(ValueError, "smoothing"):
                    combine_spectra(MAX_SPEC, [member], smoothing=smoothing)
        for strength in (np.inf, 10.1):
            with self.subTest(soft_strength=strength):
                with self.assertRaisesRegex(ValueError, "soft_strength"):
                    combine_spectra(MAX_SPEC, [member], soft_strength=strength)
        with self.assertRaisesRegex(ValueError, "hybrid_balance"):
            combine_spectra(MAX_SPEC, [member], hybrid_balance=1.1)

    def test_rejects_sequence_lengths_and_non_integer_valid_starts(self) -> None:
        members = [_constant(1), _constant(2)]
        with self.assertRaisesRegex(ValueError, "weights"):
            combine_spectra(MAX_SPEC, members, weights=[1.0])
        with self.assertRaisesRegex(ValueError, "valid_starts"):
            combine_spectra(MAX_SPEC, members, valid_starts=[0])
        with self.assertRaisesRegex(ValueError, "valid_starts"):
            combine_spectra(
                MAX_SPEC,
                members,
                valid_starts=cast(Sequence[int], [0, 1.5]),
            )


class CombineSpectraValidityTests(unittest.TestCase):
    def test_weighted_average_renormalizes_over_each_valid_interval(self) -> None:
        first = _constant(1, frames=4)
        delayed_short = _constant(3, frames=3)

        result = combine_spectra(
            AUDIO_AVERAGE,
            [first, delayed_short],
            weights=[1.0, 3.0],
            valid_starts=[0, 1],
        )

        expected = _constant(1, frames=4)
        expected[..., 1:3] = 2.5
        np.testing.assert_allclose(result, expected)

    def test_uncovered_prefix_is_zero(self) -> None:
        result = combine_spectra(MIN_SPEC, [_constant(4)], valid_starts=[2])

        np.testing.assert_array_equal(result[..., :2], 0)
        np.testing.assert_array_equal(result[..., 2:], 4)

    def test_zero_weight_member_is_excluded_from_shape_and_selection(self) -> None:
        included = _constant(2, frames=3)
        excluded = _constant(0, frames=9)

        result = combine_spectra(MIN_SPEC, [included, excluded], weights=[1.0, 0.0])

        self.assertEqual(result.shape, included.shape)
        np.testing.assert_array_equal(result, included)

    def test_large_finite_weight_priors_do_not_overflow(self) -> None:
        result = combine_spectra(
            AUDIO_AVERAGE,
            [_constant(1), _constant(3)],
            weights=[1e308, 1e308],
        )

        np.testing.assert_array_equal(result, _constant(2))

    def test_short_member_never_becomes_implicit_zero_for_minimum(self) -> None:
        long = _constant(5, frames=5)
        delayed_short = _constant(1, frames=3)

        result = combine_spectra(
            MIN_SPEC,
            [long, delayed_short],
            valid_starts=[0, 1],
            smoothing=0,
        )

        expected = _constant(5, frames=5)
        expected[..., 1:3] = 1
        np.testing.assert_array_equal(result, expected)

    def test_short_member_never_becomes_implicit_zero_for_median(self) -> None:
        low = _constant(5, frames=5)
        short_zero = _constant(0, frames=2)
        high = _constant(7, frames=5)

        result = combine_spectra(MEDIAN_SPEC, [low, short_zero, high])

        expected = _constant(6, frames=5)
        expected[..., :2] = 5
        np.testing.assert_allclose(result, expected, atol=1e-7)

    def test_smoothing_is_invariant_across_time_tile_boundaries(self) -> None:
        rng = np.random.default_rng(123)
        first = rng.standard_normal((2, 5, 23)) + 1j * rng.standard_normal((2, 5, 23))
        second = rng.standard_normal((2, 5, 17)) + 1j * rng.standard_normal((2, 5, 17))

        with patch.object(ensemble_spectral, "_TARGET_STACK_BYTES", 2**30):
            single_tile = combine_spectra(
                MAX_SPEC, [first, second], valid_starts=[0, 3], smoothing=2.0
            )
        with patch.object(ensemble_spectral, "_TARGET_STACK_BYTES", 640):
            many_tiles = combine_spectra(
                MAX_SPEC, [first, second], valid_starts=[0, 3], smoothing=2.0
            )

        np.testing.assert_allclose(many_tiles, single_tile, atol=1e-12)


class CombineSpectraAlgorithmTests(unittest.TestCase):
    def test_hard_min_chooses_each_channel_independently(self) -> None:
        first = np.array([[[1 + 1j]], [[5 + 0j]]], dtype=np.complex128)
        second = np.array([[[3 + 0j]], [[0 + 2j]]], dtype=np.complex128)
        minimum = combine_spectra(MIN_SPEC, [first, second])
        np.testing.assert_array_equal(minimum, np.array([[[1 + 1j]], [[0 + 2j]]]))

    def test_min_smoothing_softens_selection_without_changing_max(self) -> None:
        low, high = _constant(1), _constant(3)
        hard_min = combine_spectra(MIN_SPEC, [low, high])
        soft_min = combine_spectra(MIN_SPEC, [low, high], smoothing=1)
        maximum = combine_spectra(MAX_SPEC, [low, high])
        np.testing.assert_array_equal(hard_min, low)
        self.assertTrue(np.all((np.real(soft_min) > 1) & (np.real(soft_min) < 3)))
        self.assertTrue(np.all((np.real(maximum) > np.real(soft_min)) & (np.real(maximum) < 3)))

    def test_soft_spec_downweights_a_magnitude_outlier(self) -> None:
        members = [_constant(1), _constant(1.2), _constant(10)]

        neutral = combine_spectra(SOFT_SPEC, members, soft_strength=0)
        robust = combine_spectra(SOFT_SPEC, members, soft_strength=4)

        np.testing.assert_allclose(neutral, (1 + 1.2 + 10) / 3)
        self.assertLess(abs(float(np.real(robust).mean()) - 1.1), 0.2)

    def test_component_median_rejects_separate_real_and_imaginary_outliers(self) -> None:
        result = combine_spectra(
            MEDIAN_SPEC, [_constant(1 + 9j), _constant(2 + 1j), _constant(9 + 2j)]
        )
        np.testing.assert_array_equal(result, _constant(2 + 2j))

    def test_component_median_averages_even_middle_values(self) -> None:
        result = combine_spectra(MEDIAN_SPEC, [_constant(1 + 4j), _constant(3 + 8j)])
        np.testing.assert_array_equal(result, _constant(2 + 6j))

    def test_component_median_honors_a_dominant_prior_exactly(self) -> None:
        trusted = _constant(2 + 3j)
        result = combine_spectra(
            MEDIAN_SPEC,
            [trusted, _constant(-20 + 5j), _constant(12 - 9j)],
            weights=[4, 1, 1],
        )

        np.testing.assert_array_equal(result, trusted)

    def test_max_magnitude_uses_unit_phases_without_magnitude_weighting(self) -> None:
        result = combine_spectra(MAX_MAG_AVG_PHASE, [_constant(10), _constant(1j)])
        np.testing.assert_allclose(result, _constant(10 * np.exp(1j * np.pi / 4)), atol=1e-7)

    def test_hybrid_balance_interpolates_between_smoothed_extremes(self) -> None:
        low, high = _constant(1 + 1j), _constant(4 + 2j)
        minimum = combine_spectra(MIN_SPEC, [low, high], smoothing=1)
        maximum = combine_spectra(MAX_SPEC, [low, high])
        for balance in (0, 0.25, 1):
            with self.subTest(balance=balance):
                result = combine_spectra(HYBRID_SPEC, [low, high], hybrid_balance=balance)
                np.testing.assert_allclose(result, minimum * (1 - balance) + maximum * balance)

    def test_all_public_spectral_algorithm_names_are_supported(self) -> None:
        members = [_constant(1), _constant(2)]

        for algorithm in (
            AUDIO_AVERAGE,
            MAX_SPEC,
            MIN_SPEC,
            MEDIAN_SPEC,
            SOFT_SPEC,
            MAX_MAG_AVG_PHASE,
            HYBRID_SPEC,
        ):
            with self.subTest(algorithm=algorithm):
                result = combine_spectra(algorithm, members)
                self.assertEqual(result.shape, members[0].shape)
                self.assertTrue(np.isfinite(result).all())


if __name__ == "__main__":
    unittest.main()
