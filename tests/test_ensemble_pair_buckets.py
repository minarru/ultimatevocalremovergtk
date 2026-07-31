"""Mapping an EnsemblePair id to its two buckets / combo choices."""

import unittest

from core.model_stem_semantics import (
    BUCKET_BASS,
    BUCKET_INST_WITH_BV,
    BUCKET_INSTRUMENTAL,
    BUCKET_LEAD_VOCALS,
    BUCKET_OTHER,
    BUCKET_UNKNOWN,
    BUCKET_VOCALS,
    ensemble_pair_buckets,
)
from core.stems import EnsemblePair, coerce_ensemble_pair, ensemble_pair_choices, ui_label


class PairBucketTests(unittest.TestCase):
    def test_vocal_pair(self) -> None:
        self.assertEqual(
            ensemble_pair_buckets(EnsemblePair.VOCALS_INSTRUMENTAL),
            (BUCKET_VOCALS, BUCKET_INSTRUMENTAL),
        )
        self.assertEqual(
            ensemble_pair_buckets("vocals_instrumental"),
            (BUCKET_VOCALS, BUCKET_INSTRUMENTAL),
        )

    def test_karaoke_pair(self) -> None:
        self.assertEqual(
            ensemble_pair_buckets(EnsemblePair.KARAOKE),
            (BUCKET_LEAD_VOCALS, BUCKET_INST_WITH_BV),
        )
        self.assertEqual(
            ensemble_pair_buckets("karaoke"),
            (BUCKET_LEAD_VOCALS, BUCKET_INST_WITH_BV),
        )

    def test_other_pair_keeps_other_as_a_real_stem(self) -> None:
        # Regression: resolving this through ensemble_stem_bucket would give
        # BUCKET_INSTRUMENTAL, because a 1-stem 'other' is the instrumental
        # complement. A pair is a request, not a model description.
        self.assertEqual(
            ensemble_pair_buckets(EnsemblePair.OTHER),
            (BUCKET_OTHER, BUCKET_UNKNOWN),
        )

    def test_bass_pair(self) -> None:
        primary, _secondary = ensemble_pair_buckets(EnsemblePair.BASS)
        self.assertEqual(primary, BUCKET_BASS)

    def test_complement_half_is_unknown_not_a_bucket(self) -> None:
        # 'No Other' / 'No Bass' are derived by inversion, never trained, so
        # they are not a bucket any model can match. Callers discard UNKNOWN.
        for pair in (EnsemblePair.OTHER, EnsemblePair.BASS, EnsemblePair.DRUMS):
            with self.subTest(pair=pair):
                self.assertEqual(ensemble_pair_buckets(pair)[1], BUCKET_UNKNOWN)

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
                    ensemble_pair_buckets(value), (BUCKET_UNKNOWN, BUCKET_UNKNOWN)
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
