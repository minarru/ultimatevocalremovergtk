"""Mapping an ENSEMBLE_MAIN_STEM pair string to its two buckets."""

import unittest

from bundled.constants import (
    BASS_PAIR,
    CHOOSE_STEM_PAIR,
    ENSEMBLE_MAIN_STEM,
    FOUR_STEM_ENSEMBLE,
    KARAOKE_PAIR,
    MULTI_STEM_ENSEMBLE,
    OTHER_PAIR,
    VOCAL_PAIR,
)
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


class PairBucketTests(unittest.TestCase):
    def test_vocal_pair(self) -> None:
        self.assertEqual(ensemble_pair_buckets(VOCAL_PAIR), (BUCKET_VOCALS, BUCKET_INSTRUMENTAL))

    def test_karaoke_pair(self) -> None:
        self.assertEqual(
            ensemble_pair_buckets(KARAOKE_PAIR), (BUCKET_LEAD_VOCALS, BUCKET_INST_WITH_BV)
        )

    def test_other_pair_keeps_other_as_a_real_stem(self) -> None:
        # Regression: resolving this through ensemble_stem_bucket would give
        # BUCKET_INSTRUMENTAL, because a 1-stem 'other' is the instrumental
        # complement. A pair is a request, not a model description.
        self.assertEqual(ensemble_pair_buckets(OTHER_PAIR), (BUCKET_OTHER, BUCKET_UNKNOWN))

    def test_bass_pair(self) -> None:
        primary, _secondary = ensemble_pair_buckets(BASS_PAIR)
        self.assertEqual(primary, BUCKET_BASS)

    def test_complement_half_is_unknown_not_a_bucket(self) -> None:
        # 'No Other' / 'No Bass' are derived by inversion, never trained, so
        # they are not a bucket any model can match. Callers discard UNKNOWN.
        for pair in (OTHER_PAIR, BASS_PAIR):
            with self.subTest(pair=pair):
                self.assertEqual(ensemble_pair_buckets(pair)[1], BUCKET_UNKNOWN)

    def test_non_pair_values_are_unknown(self) -> None:
        for value in (CHOOSE_STEM_PAIR, FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE, ""):
            with self.subTest(value=value):
                self.assertEqual(ensemble_pair_buckets(value), (BUCKET_UNKNOWN, BUCKET_UNKNOWN))


class MainStemListTests(unittest.TestCase):
    def test_karaoke_pair_is_offered(self) -> None:
        self.assertIn(KARAOKE_PAIR, ENSEMBLE_MAIN_STEM)

    def test_existing_pairs_are_preserved(self) -> None:
        # Additive only: stored settings.ensemble.main_stem must keep resolving.
        for value in (CHOOSE_STEM_PAIR, VOCAL_PAIR, OTHER_PAIR, BASS_PAIR,
                      FOUR_STEM_ENSEMBLE, MULTI_STEM_ENSEMBLE):
            with self.subTest(value=value):
                self.assertIn(value, ENSEMBLE_MAIN_STEM)

    def test_pair_splits_on_a_single_slash(self) -> None:
        # ui/ensemble/window.py:563 does main_stem.split("/", 1).
        primary, secondary = KARAOKE_PAIR.split("/", 1)
        self.assertTrue(primary)
        self.assertTrue(secondary)
        self.assertNotIn("/", secondary)


if __name__ == "__main__":
    unittest.main()
