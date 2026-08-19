"""Mapping an EnsemblePair id to its two buckets / combo choices."""

import unittest

from core.stems import (
    EnsemblePair,
    StemBucket,
    coerce_ensemble_pair,
    ensemble_pair_choices,
    ui_label,
)


class PairBucketTests(unittest.TestCase):
    def test_vocal_pair(self) -> None:
        self.assertEqual(
            coerce_ensemble_pair(EnsemblePair.VOCALS_INSTRUMENTAL).buckets(),
            (StemBucket.VOCALS, StemBucket.INSTRUMENTAL),
        )
        self.assertEqual(
            coerce_ensemble_pair("vocals_instrumental").buckets(),
            (StemBucket.VOCALS, StemBucket.INSTRUMENTAL),
        )

    def test_karaoke_pair(self) -> None:
        self.assertEqual(
            coerce_ensemble_pair(EnsemblePair.KARAOKE).buckets(),
            (StemBucket.LEAD_VOCALS, StemBucket.INST_WITH_BV),
        )
        self.assertEqual(
            coerce_ensemble_pair("karaoke").buckets(),
            (StemBucket.LEAD_VOCALS, StemBucket.INST_WITH_BV),
        )

    def test_other_pair_keeps_other_as_a_real_stem(self) -> None:
        # Regression: resolving this through bucket_for_model_stem would give
        # StemBucket.INSTRUMENTAL, because a 1-stem 'other' is the instrumental
        # complement. A pair is a request, not a model description.
        self.assertEqual(
            coerce_ensemble_pair(EnsemblePair.OTHER).buckets(),
            (StemBucket.OTHER, StemBucket.UNKNOWN),
        )

    def test_bass_pair(self) -> None:
        primary, _secondary = coerce_ensemble_pair(EnsemblePair.BASS).buckets()
        self.assertEqual(primary, StemBucket.BASS)

    def test_complement_half_is_unknown_not_a_bucket(self) -> None:
        # 'No Other' / 'No Bass' are derived by inversion, never trained, so
        # they are not a bucket any model can match. Callers discard UNKNOWN.
        for pair in (EnsemblePair.OTHER, EnsemblePair.BASS, EnsemblePair.DRUMS):
            with self.subTest(pair=pair):
                self.assertEqual(
                    coerce_ensemble_pair(pair).buckets()[1], StemBucket.UNKNOWN
                )

    def test_non_pair_values_are_unknown(self) -> None:
        for value in (
            EnsemblePair.CHOOSE,
            EnsemblePair.FOUR_STEM,
            EnsemblePair.MULTI_STEM,
            "",
            "Vocals/Instrumental",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    coerce_ensemble_pair(value).buckets(),
                    (StemBucket.UNKNOWN, StemBucket.UNKNOWN),
                )


class MainStemChoiceTests(unittest.TestCase):
    def test_ensemble_pair_choices_cover_all_pairs(self) -> None:
        choices = list(ensemble_pair_choices())
        ids = [stored for stored, _label in choices]
        self.assertEqual(ids, [pair.value for pair in EnsemblePair])
        for stored, label in choices:
            with self.subTest(stored=stored):
                pair = coerce_ensemble_pair(stored)
                self.assertIsInstance(pair, EnsemblePair)
                self.assertEqual(label, ui_label(pair))

    def test_karaoke_id_is_offered(self) -> None:
        ids = [stored for stored, _label in ensemble_pair_choices()]
        self.assertIn(EnsemblePair.KARAOKE.value, ids)

    def test_stem_halves_are_slash_free_labels(self) -> None:
        primary, secondary = EnsemblePair.KARAOKE.stem_halves()
        self.assertTrue(primary)
        self.assertTrue(secondary)
        self.assertNotIn("/", primary)
        self.assertNotIn("/", secondary)


if __name__ == "__main__":
    unittest.main()
