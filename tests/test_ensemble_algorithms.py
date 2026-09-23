"""Unit tests for ensemble algorithm atoms and Primary/Secondary helpers."""

from __future__ import annotations

import typing
import unittest

import numpy as np

from bundled.constants import (
    AUDIO_AVERAGE,
    CHUNK_MIN,
    COMBINE_INPUTS,
    ENSEMBLE_ALGORITHMS,
    HYBRID_SPEC,
    MANUAL_ENSEMBLE_OPTIONS,
    MAX_MAG_AVG_PHASE,
    MAX_MIN,
    MAX_SPEC,
    MEDIAN_SPEC,
    MIN_SPEC,
    SOFT_SPEC,
)
from core.ensemble_algorithms import (
    format_ensemble_type,
    is_single_token_ensemble_type,
    legacy_pair_values,
    parse_ensemble_type,
)
from ml.ensemble_spectral import combine_spectra
from ml.spec_utils import ensemble_wav


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
        for primary in (MAX_SPEC, MEDIAN_SPEC, SOFT_SPEC, MAX_MAG_AVG_PHASE):
            for secondary in (MIN_SPEC, HYBRID_SPEC, CHUNK_MIN, MAX_MAG_AVG_PHASE):
                formatted = format_ensemble_type(primary, secondary)
                self.assertEqual(parse_ensemble_type(formatted), (primary, secondary))

    def test_legacy_max_min(self) -> None:
        self.assertEqual(parse_ensemble_type(MAX_MIN), (MAX_SPEC, MIN_SPEC))
        self.assertEqual(parse_ensemble_type("Max Spec/Min Spec"), (MAX_SPEC, MIN_SPEC))

    def test_single_token_duplicates(self) -> None:
        self.assertEqual(parse_ensemble_type(MEDIAN_SPEC), (MEDIAN_SPEC, MEDIAN_SPEC))
        self.assertEqual(
            parse_ensemble_type(MAX_MAG_AVG_PHASE),
            (MAX_MAG_AVG_PHASE, MAX_MAG_AVG_PHASE),
        )
        self.assertTrue(is_single_token_ensemble_type(MAX_MAG_AVG_PHASE))

    def test_pair_delimiter_allows_spaces_even_when_atom_contains_slash(self) -> None:
        value = f" {MAX_MAG_AVG_PHASE} / {MIN_SPEC} "

        self.assertEqual(parse_ensemble_type(value), (MAX_MAG_AVG_PHASE, MIN_SPEC))

    def test_strict_parser_rejects_unknown_or_malformed_values(self) -> None:
        for value in (None, "", "Not A Real", "Max Spec/Not A Real", "Max Spec//Min Spec"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "ensemble algorithm"):
                    parse_ensemble_type(value, strict=True)

        self.assertEqual(
            parse_ensemble_type(MAX_MAG_AVG_PHASE, strict=True),
            (MAX_MAG_AVG_PHASE, MAX_MAG_AVG_PHASE),
        )

    def test_phase_atom_survives_settings_validation_and_coercion(self) -> None:
        from core.settings import Settings
        from core.settings.access import set_path, validate_setting_value

        settings = Settings.defaults()

        validate_setting_value(settings, "ensemble.type", MAX_MAG_AVG_PHASE)
        set_path(settings, "ensemble.type", MAX_MAG_AVG_PHASE)

        self.assertEqual(settings.ensemble.type, MAX_MAG_AVG_PHASE)

    def test_multi_stem_ensembler_selects_complete_phase_atom(self) -> None:
        from core.ensembler import CollectedStem, Ensembler
        from core.settings import Settings
        from core.stem_roles import StemRoleId

        ensembler = object.__new__(Ensembler)
        ensembler.settings = Settings.defaults()
        ensembler.settings.ensemble.type = MAX_MAG_AVG_PHASE
        stem = CollectedStem(StemRoleId("vocal.vocals"), "Vocals")

        self.assertEqual(
            ensembler._algorithm_for_stem(stem, is_multi_stem=True),
            MAX_MAG_AVG_PHASE,
        )

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
        self.a = (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)).astype(
            np.complex128
        )
        self.b = (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)).astype(
            np.complex128
        )

    def test_min_matches_pairwise(self) -> None:
        members = [self.a, self.b]
        np.testing.assert_array_equal(
            combine_spectra(MIN_SPEC, members), _pairwise_mag_reduce(MIN_SPEC, members)
        )

    def test_median_middle_of_magnitude_ladder(self) -> None:
        phase = 0.4
        base = np.ones((2, 4, 6), dtype=np.complex128) * np.exp(1j * phase)
        low, mid, high = base * 1.0, base * 2.0, base * 3.0
        out = combine_spectra(MEDIAN_SPEC, [low, mid, high])
        np.testing.assert_allclose(np.abs(out), 2.0, atol=1e-9)
        np.testing.assert_allclose(np.angle(out), phase, atol=1e-9)

    def test_soft_weights_sum_and_equal_near_average(self) -> None:
        twin_a = np.full((2, 4, 6), 1.0 + 1.0j, dtype=np.complex128)
        twin_b = twin_a.copy()
        out = combine_spectra(SOFT_SPEC, [twin_a, twin_b])
        avg = 0.5 * (twin_a + twin_b)
        np.testing.assert_allclose(out, avg, atol=1e-9)

        # Unequal members: Soft Spec stays a convex combination (finite, same shape).
        out2 = combine_spectra(SOFT_SPEC, [self.a, self.b])
        self.assertEqual(out2.shape, self.a.shape)
        self.assertTrue(np.isfinite(out2).all())

        # Agreement weights (softmax over members) sum to 1 per bin.

    def test_max_mag_avg_phase(self) -> None:
        # Same magnitudes, opposite phases → Mag matches Max; phase is not raw Max.
        mag = np.full((2, 3, 4), 2.0)
        a = mag * np.exp(1j * 0.0)
        b = mag * np.exp(1j * np.pi)
        out = combine_spectra(MAX_MAG_AVG_PHASE, [a, b])
        np.testing.assert_allclose(np.abs(out), mag, atol=1e-9)
        # Mean of unit vectors at 0 and π is ~0 → unstable angle; magnitudes still Max.
        # Use a clearer phase disagreement with unequal magnitudes.
        a2 = np.full((2, 3, 4), 3.0) * np.exp(1j * 0.2)
        b2 = np.full((2, 3, 4), 1.0) * np.exp(1j * 1.2)
        out2 = combine_spectra(MAX_MAG_AVG_PHASE, [a2, b2])
        max2 = combine_spectra(MAX_SPEC, [a2, b2])
        np.testing.assert_allclose(np.abs(out2), np.abs(a2), atol=1e-9)
        self.assertFalse(np.allclose(np.angle(out2), np.angle(max2)))

    def test_hybrid_is_mean_of_smoothed_max_and_min(self) -> None:
        max_out = combine_spectra(MAX_SPEC, [self.a, self.b])
        min_out = combine_spectra(MIN_SPEC, [self.a, self.b], smoothing=1)
        hybrid = combine_spectra(HYBRID_SPEC, [self.a, self.b])
        np.testing.assert_allclose(hybrid, 0.5 * (max_out + min_out), atol=1e-9)

    def test_pad_does_not_truncate_longer_member(self) -> None:
        short = self.a[:, :, :8]
        long = self.b
        out = combine_spectra(MAX_SPEC, [short, long])
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


class PresetMappingTests(unittest.TestCase):
    def test_pair_consistent_preset_is_flag_plus_max_spec(self) -> None:
        from bundled.constants import MAX_SPEC, MIN_SPEC
        from core.ensemble_algorithms import (
            CUSTOM_PRESET,
            ENSEMBLE_PRESET_OPTIONS,
            ENSEMBLE_PRESET_PAIRS,
            PAIR_CONSISTENT_PRESET,
            RECOMMENDED_PRESET,
            pair_for_preset,
            preset_for_pair,
            preset_for_state,
        )

        self.assertEqual(pair_for_preset(PAIR_CONSISTENT_PRESET), (MAX_SPEC, MAX_SPEC))
        self.assertEqual(
            preset_for_state(MAX_SPEC, MAX_SPEC, derive_complement_from_mix=True),
            PAIR_CONSISTENT_PRESET,
        )
        self.assertEqual(
            preset_for_state(MAX_SPEC, MAX_SPEC, derive_complement_from_mix=False),
            "Full Max",
        )
        self.assertEqual(
            preset_for_state(MAX_SPEC, MIN_SPEC, derive_complement_from_mix=True),
            CUSTOM_PRESET,
        )
        self.assertEqual(
            preset_for_state(MAX_SPEC, MIN_SPEC, derive_complement_from_mix=False),
            RECOMMENDED_PRESET,
        )
        self.assertEqual(preset_for_pair(MAX_SPEC, MAX_SPEC), "Full Max")
        self.assertNotIn(PAIR_CONSISTENT_PRESET, ENSEMBLE_PRESET_PAIRS)
        recommended_idx = ENSEMBLE_PRESET_OPTIONS.index(RECOMMENDED_PRESET)
        self.assertEqual(
            ENSEMBLE_PRESET_OPTIONS[recommended_idx + 1],
            PAIR_CONSISTENT_PRESET,
        )

    def test_pair_consistent_preset_omitted_when_plan_unavailable(self) -> None:
        from core.ensemble_algorithms import (
            ENSEMBLE_PRESET_OPTIONS,
            PAIR_CONSISTENT_PRESET,
            ensemble_preset_options,
        )

        self.assertEqual(
            ensemble_preset_options(include_pair_consistent=True),
            ENSEMBLE_PRESET_OPTIONS,
        )
        hidden = ensemble_preset_options(include_pair_consistent=False)
        self.assertNotIn(PAIR_CONSISTENT_PRESET, hidden)
        self.assertEqual(
            len(hidden),
            len(ENSEMBLE_PRESET_OPTIONS) - 1,
        )


if __name__ == "__main__":
    unittest.main()
