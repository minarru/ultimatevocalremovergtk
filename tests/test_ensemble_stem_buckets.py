"""One semantic rule for 'what stem does this model produce'."""

import re
import unittest

from core.export_naming import format_stem_basename
from core.model_stem_semantics import (
    BUCKET_BASS,
    BUCKET_BV_VOCALS,
    BUCKET_DRUMS,
    BUCKET_INST_WITH_BV,
    BUCKET_INST_WITH_LEAD,
    BUCKET_INSTRUMENTAL,
    BUCKET_LEAD_VOCALS,
    BUCKET_OTHER,
    BUCKET_UNKNOWN,
    BUCKET_VOCALS,
    ensemble_stem_bucket,
)

_ALL_BUCKETS = (
    BUCKET_VOCALS, BUCKET_INSTRUMENTAL, BUCKET_OTHER, BUCKET_DRUMS, BUCKET_BASS,
    BUCKET_LEAD_VOCALS, BUCKET_BV_VOCALS, BUCKET_INST_WITH_BV, BUCKET_INST_WITH_LEAD,
)


class OtherOverloadTests(unittest.TestCase):
    """'other' means three different things depending on context."""

    def test_two_stem_other_is_instrumental(self) -> None:
        self.assertEqual(ensemble_stem_bucket("other", stem_count=1), BUCKET_INSTRUMENTAL)
        self.assertEqual(ensemble_stem_bucket("other", stem_count=2), BUCKET_INSTRUMENTAL)

    def test_four_stem_other_is_its_own_stem(self) -> None:
        self.assertEqual(ensemble_stem_bucket("other", stem_count=4), BUCKET_OTHER)

    def test_karaoke_instrumental_is_its_own_bucket(self) -> None:
        self.assertEqual(
            ensemble_stem_bucket("Instrumental", stem_count=2, is_karaoke=True),
            BUCKET_INST_WITH_BV,
        )
        self.assertEqual(
            ensemble_stem_bucket("other", stem_count=2, is_karaoke=True),
            BUCKET_INST_WITH_BV,
        )


class KaraokeAndBvTests(unittest.TestCase):
    def test_karaoke_vocals_is_lead_vocals(self) -> None:
        self.assertEqual(
            ensemble_stem_bucket("Vocals", stem_count=1, is_karaoke=True), BUCKET_LEAD_VOCALS
        )

    def test_bv_model_mirrors_karaoke(self) -> None:
        self.assertEqual(
            ensemble_stem_bucket("Vocals", stem_count=1, is_bv=True), BUCKET_BV_VOCALS
        )
        self.assertEqual(
            ensemble_stem_bucket("Instrumental", stem_count=2, is_bv=True), BUCKET_INST_WITH_LEAD
        )


class CaseAndAliasTests(unittest.TestCase):
    def test_case_variants_fold(self) -> None:
        for raw in ("vocals", "Vocals", "VOCALS", "Vocal", "voc"):
            with self.subTest(raw=raw):
                self.assertEqual(ensemble_stem_bucket(raw, stem_count=1), BUCKET_VOCALS)

    def test_instrument_alias_is_admitted(self) -> None:
        # bs_inst_hyperace2_unwa declares its stem as 'instrument'.
        self.assertEqual(ensemble_stem_bucket("instrument", stem_count=1), BUCKET_INSTRUMENTAL)

    def test_four_stem_musdb_names(self) -> None:
        self.assertEqual(ensemble_stem_bucket("drums", stem_count=4), BUCKET_DRUMS)
        self.assertEqual(ensemble_stem_bucket("bass", stem_count=4), BUCKET_BASS)
        self.assertEqual(ensemble_stem_bucket("vocals", stem_count=4), BUCKET_VOCALS)

    def test_unknown_vocabulary_is_unknown(self) -> None:
        # Phantom Centre. Must never land in Vocals/Instrumental.
        self.assertEqual(ensemble_stem_bucket("Similarity", stem_count=1), BUCKET_UNKNOWN)
        self.assertEqual(ensemble_stem_bucket("Sfx", stem_count=1), BUCKET_UNKNOWN)

    def test_empty_is_unknown(self) -> None:
        self.assertEqual(ensemble_stem_bucket("", stem_count=1), BUCKET_UNKNOWN)


class IdentityCodeTests(unittest.TestCase):
    """Splitter identity codes name the product, so flags must not override."""

    def test_lead_only_resolves_without_the_karaoke_flag(self) -> None:
        # A vocal splitter writes 'lead_only' regardless of the parent model's
        # own flags — the flags describe the model, the code describes the stem.
        self.assertEqual(ensemble_stem_bucket("lead_only", stem_count=2), BUCKET_LEAD_VOCALS)
        self.assertEqual(ensemble_stem_bucket("Lead Vocals", stem_count=2), BUCKET_LEAD_VOCALS)

    def test_backing_only_resolves_without_the_bv_flag(self) -> None:
        self.assertEqual(ensemble_stem_bucket("backing_only", stem_count=2), BUCKET_BV_VOCALS)
        self.assertEqual(ensemble_stem_bucket("Backing Vocals", stem_count=2), BUCKET_BV_VOCALS)

    def test_identity_code_is_not_folded_into_plain_vocals(self) -> None:
        self.assertNotEqual(ensemble_stem_bucket("lead_only", stem_count=2), BUCKET_VOCALS)


class FilenameSafetyTests(unittest.TestCase):
    """A bucket with parentheses silently breaks ensemble collection."""

    #: Verbatim from core/job_runner.py:1315.
    COLLECT_RE = re.compile(r"\(([^()]+)\)\.(?:wav|flac|mp3)$", re.IGNORECASE)

    def test_no_bucket_contains_parentheses(self) -> None:
        for bucket in _ALL_BUCKETS:
            with self.subTest(bucket=bucket):
                self.assertNotIn("(", bucket)
                self.assertNotIn(")", bucket)

    def test_every_bucket_round_trips_through_the_collection_regex(self) -> None:
        for bucket in _ALL_BUCKETS:
            with self.subTest(bucket=bucket):
                name = format_stem_basename("Song Model", bucket) + ".wav"
                match = self.COLLECT_RE.search(name)
                self.assertIsNotNone(match, f"{name!r} would not be collected")
                assert match is not None
                self.assertEqual(match.group(1), bucket)


if __name__ == "__main__":
    unittest.main()
