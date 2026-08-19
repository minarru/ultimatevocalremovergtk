"""One semantic rule for 'what stem does this model produce'."""

import re
import unittest

from core.export_naming import format_stem_basename
from core.stems import StemBucket, bucket_for_model_stem, concept_is, filename_tag

_ALL_BUCKETS = (
    StemBucket.VOCALS, StemBucket.INSTRUMENTAL, StemBucket.OTHER, StemBucket.DRUMS,
    StemBucket.BASS, StemBucket.LEAD_VOCALS, StemBucket.BACKING_VOCALS,
    StemBucket.INST_WITH_BV, StemBucket.INST_WITH_LEAD,
)


class OtherOverloadTests(unittest.TestCase):
    """'other' means three different things depending on context."""

    def test_two_stem_other_is_instrumental(self) -> None:
        self.assertEqual(bucket_for_model_stem("other", stem_count=1), StemBucket.INSTRUMENTAL)
        self.assertEqual(bucket_for_model_stem("other", stem_count=2), StemBucket.INSTRUMENTAL)

    def test_four_stem_other_is_its_own_stem(self) -> None:
        self.assertEqual(bucket_for_model_stem("other", stem_count=4), StemBucket.OTHER)

    def test_karaoke_instrumental_is_its_own_bucket(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("Instrumental", stem_count=2, is_karaoke=True),
            StemBucket.INST_WITH_BV,
        )
        self.assertEqual(
            bucket_for_model_stem("other", stem_count=2, is_karaoke=True),
            StemBucket.INST_WITH_BV,
        )


class KaraokeAndBvTests(unittest.TestCase):
    def test_karaoke_vocals_is_lead_vocals(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("Vocals", stem_count=1, is_karaoke=True), StemBucket.LEAD_VOCALS
        )

    def test_bv_model_mirrors_karaoke(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("Vocals", stem_count=1, is_bv=True), StemBucket.BACKING_VOCALS
        )
        self.assertEqual(
            bucket_for_model_stem("Instrumental", stem_count=2, is_bv=True), StemBucket.INST_WITH_LEAD
        )


class CaseAndAliasTests(unittest.TestCase):
    def test_case_variants_fold(self) -> None:
        for raw in ("vocals", "Vocals", "VOCALS", "Vocal", "voc"):
            with self.subTest(raw=raw):
                self.assertEqual(bucket_for_model_stem(raw, stem_count=1), StemBucket.VOCALS)

    def test_instrument_alias_is_admitted(self) -> None:
        # bs_inst_hyperace2_unwa declares its stem as 'instrument'.
        self.assertEqual(bucket_for_model_stem("instrument", stem_count=1), StemBucket.INSTRUMENTAL)

    def test_four_stem_musdb_names(self) -> None:
        self.assertEqual(bucket_for_model_stem("drums", stem_count=4), StemBucket.DRUMS)
        self.assertEqual(bucket_for_model_stem("bass", stem_count=4), StemBucket.BASS)
        self.assertEqual(bucket_for_model_stem("vocals", stem_count=4), StemBucket.VOCALS)

    def test_unknown_vocabulary_is_unknown(self) -> None:
        # Phantom Centre. Must never land in Vocals/Instrumental.
        self.assertEqual(bucket_for_model_stem("Similarity", stem_count=1), StemBucket.UNKNOWN)
        self.assertEqual(bucket_for_model_stem("Sfx", stem_count=1), StemBucket.UNKNOWN)

    def test_empty_is_unknown(self) -> None:
        self.assertEqual(bucket_for_model_stem("", stem_count=1), StemBucket.UNKNOWN)


class IdentityCodeTests(unittest.TestCase):
    """Splitter identity codes name the product, so flags must not override."""

    def test_lead_only_resolves_without_the_karaoke_flag(self) -> None:
        # A vocal splitter writes 'lead_only' regardless of the parent model's
        # own flags — the flags describe the model, the code describes the stem.
        self.assertEqual(bucket_for_model_stem("lead_only", stem_count=2), StemBucket.LEAD_VOCALS)
        self.assertEqual(bucket_for_model_stem("Lead Vocals", stem_count=2), StemBucket.LEAD_VOCALS)

    def test_backing_only_resolves_without_the_bv_flag(self) -> None:
        self.assertEqual(bucket_for_model_stem("backing_only", stem_count=2), StemBucket.BACKING_VOCALS)
        self.assertEqual(bucket_for_model_stem("Backing Vocals", stem_count=2), StemBucket.BACKING_VOCALS)
        self.assertEqual(bucket_for_model_stem("backing_vocal", stem_count=3), StemBucket.BACKING_VOCALS)
        self.assertEqual(bucket_for_model_stem("backing_vocals", stem_count=3), StemBucket.BACKING_VOCALS)

    def test_identity_code_is_not_folded_into_plain_vocals(self) -> None:
        self.assertNotEqual(bucket_for_model_stem("lead_only", stem_count=2), StemBucket.VOCALS)


class FilenameSafetyTests(unittest.TestCase):
    """A bucket with parentheses silently breaks ensemble collection."""

    #: Verbatim from core/job_runner.py:1315.
    COLLECT_RE = re.compile(r"\(([^()]+)\)\.(?:wav|flac|mp3)$", re.IGNORECASE)

    def test_no_bucket_contains_parentheses(self) -> None:
        for bucket in _ALL_BUCKETS:
            with self.subTest(bucket=bucket):
                tag = filename_tag(bucket)
                self.assertNotIn("(", tag)
                self.assertNotIn(")", tag)

    def test_every_bucket_round_trips_through_the_collection_regex(self) -> None:
        for bucket in _ALL_BUCKETS:
            with self.subTest(bucket=bucket):
                tag = filename_tag(bucket)
                name = format_stem_basename("Song Model", tag) + ".wav"
                match = self.COLLECT_RE.search(name)
                self.assertIsNotNone(match, f"{name!r} would not be collected")
                assert match is not None
                self.assertEqual(match.group(1), tag)


class ThirdVocabularyConsolidationTests(unittest.TestCase):
    """core/stems.py's bucket_for_model_stem had its own private token sets,
    already drifted from the other two tables (it alone recognized
    "instrument"). This locks in that the drift is now gone in both
    directions: the new alias reaches bucketing (already true) *and* stays
    behavior-identical for every token the old private sets recognized."""

    def test_instrument_alias_resolves_to_instrumental_bucket(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("instrument", stem_count=1), StemBucket.INSTRUMENTAL
        )

    def test_voc_alias_resolves_to_vocals_bucket(self) -> None:
        self.assertEqual(bucket_for_model_stem("voc", stem_count=2), StemBucket.VOCALS)


class VocalSplitRoleTests(unittest.TestCase):
    """Splitter role is not karaoke-as-primary: inst is Backing Vocals, not Inst w BGV."""

    def test_karaoke_splitter_vocals_is_lead(self) -> None:
        for raw in ("Vocals", "vocals"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    bucket_for_model_stem(raw, stem_count=2, is_vocal_split=True),
                    StemBucket.LEAD_VOCALS,
                )

    def test_karaoke_splitter_inst_is_backing_not_inst_with_bv(self) -> None:
        for raw in ("Instrumental", "other", "instrument"):
            with self.subTest(raw=raw):
                self.assertEqual(
                    bucket_for_model_stem(
                        raw, stem_count=2, is_karaoke=True, is_vocal_split=True
                    ),
                    StemBucket.BACKING_VOCALS,
                )
                self.assertNotEqual(
                    bucket_for_model_stem(
                        raw, stem_count=2, is_karaoke=True, is_vocal_split=True
                    ),
                    StemBucket.INST_WITH_BV,
                )

    def test_karaoke_primary_inst_stays_inst_with_bv(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("Instrumental", stem_count=2, is_karaoke=True),
            StemBucket.INST_WITH_BV,
        )

    def test_bv_splitter_inverts(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("vocals", stem_count=2, is_bv=True, is_vocal_split=True),
            StemBucket.BACKING_VOCALS,
        )
        self.assertEqual(
            bucket_for_model_stem("other", stem_count=2, is_bv=True, is_vocal_split=True),
            StemBucket.LEAD_VOCALS,
        )

    def test_four_stem_other_is_not_backing_under_vocal_split(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("other", stem_count=4, is_vocal_split=True),
            StemBucket.OTHER,
        )

    def test_center_stays_unknown(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("center", stem_count=2, is_vocal_split=True),
            StemBucket.UNKNOWN,
        )

    def test_concept_is_matches_yaml_vocals_to_vocals_bucket(self) -> None:
        self.assertTrue(concept_is("vocals", StemBucket.VOCALS, stem_count=2))
        self.assertFalse(
            concept_is("vocals", StemBucket.VOCALS, stem_count=2, is_vocal_split=True)
        )
        self.assertTrue(
            concept_is(
                "vocals", StemBucket.LEAD_VOCALS, stem_count=2, is_vocal_split=True
            )
        )


class FinalEnsembleFilterTests(unittest.TestCase):
    def test_native_focus_filters_only_the_final_route(self) -> None:
        from core.ensembler import _filter_final_ensemble_stems

        self.assertEqual(
            _filter_final_ensemble_stems(
                ["Bass", "Drums", "Other", "Vocals"], "Bass"
            ),
            ["Bass"],
        )

    def test_unmatched_inherited_focus_falls_back_to_all_routes(self) -> None:
        from core.ensembler import _filter_final_ensemble_stems

        stems = ["Bass", "Drums", "Other", "Vocals"]
        self.assertEqual(_filter_final_ensemble_stems(stems, "Piano"), stems)


class StemFocusMatchTests(unittest.TestCase):
    def test_vocals_focus_on_inst_primary_selects_secondary(self) -> None:
        from core.stems import exclusive_flags_for_focus

        flags = exclusive_flags_for_focus(
            StemBucket.VOCALS.value,
            primary_stem="other",
            secondary_stem="vocals",
            stem_count=2,
        )
        self.assertEqual(flags, (False, True))

    def test_empty_focus_returns_none(self) -> None:
        from core.stems import exclusive_flags_for_focus

        self.assertIsNone(
            exclusive_flags_for_focus(
                "",
                primary_stem="Vocals",
                secondary_stem="Instrumental",
                stem_count=2,
            )
        )

    def test_normalize_stem_focus_aliases_vocals(self) -> None:
        from core.stems import normalize_stem_focus

        self.assertEqual(normalize_stem_focus("vocals"), StemBucket.VOCALS.value)
        self.assertEqual(normalize_stem_focus("Vocals"), StemBucket.VOCALS.value)
        self.assertEqual(normalize_stem_focus(""), "")

    def test_normalize_stem_focus_keeps_positional_sentinels(self) -> None:
        from core.stems import FOCUS_PRIMARY, FOCUS_SECONDARY, normalize_stem_focus

        self.assertEqual(normalize_stem_focus("primary"), FOCUS_PRIMARY)
        self.assertEqual(normalize_stem_focus("PRIMARY"), FOCUS_PRIMARY)
        self.assertEqual(normalize_stem_focus("secondary", strict=True), FOCUS_SECONDARY)

    def test_focus_other_is_the_other_stem_not_the_instrumental_side(self) -> None:
        """``other`` as a *pick* means Other; only a 2-stem model's native
        ``other`` reads as the instrumental side, and that match happens in
        focus_matches_stem, not in the stored value."""
        from core.stems import focus_matches_stem, normalize_stem_focus

        self.assertEqual(normalize_stem_focus("other"), StemBucket.OTHER.value)
        self.assertEqual(normalize_stem_focus("Other"), StemBucket.OTHER.value)
        self.assertTrue(
            focus_matches_stem(StemBucket.OTHER.value, "other", stem_count=2)
        )
        self.assertTrue(
            focus_matches_stem(StemBucket.OTHER.value, "other", stem_count=4)
        )
        self.assertFalse(
            focus_matches_stem(StemBucket.OTHER.value, "vocals", stem_count=4)
        )

    def test_export_labels_canonicalize_community_yaml_spellings(self) -> None:
        """Export filenames read the concept, so a community yaml's ``vocals``/
        ``other`` pair lands on ``Vocals``/``Instrumental`` rather than the raw
        checkpoint spelling. 4-stem ``other`` stays Other, and specialty stems
        keep their native name (no bucket to canonicalize onto)."""
        from core.stems import export_stem_label

        class _Model:
            is_karaoke = False
            is_bv_model = False
            is_vocal_split_model = False
            demucs_stem_count = 0
            demucs_source_list: list[str] = []

            def __init__(self, stems: list[str]) -> None:
                self.mdx_model_stems = stems
                self.mdx_stem_count = len(stems)

        two_stem = _Model(["vocals", "other"])
        self.assertEqual(export_stem_label(two_stem, "vocals"), "Vocals")
        self.assertEqual(export_stem_label(two_stem, "other"), "Instrumental")
        self.assertEqual(export_stem_label(two_stem, "Vocals"), "Vocals")

        four_stem = _Model(["vocals", "drums", "bass", "other"])
        self.assertEqual(export_stem_label(four_stem, "other"), "Other")
        self.assertEqual(export_stem_label(four_stem, "drums"), "Drums")

        specialty = _Model(["dry", "noreverb"])
        self.assertEqual(export_stem_label(specialty, "noreverb"), "noreverb")

    def test_specialty_focus_needs_the_raw_prefix(self) -> None:
        from core.stems import normalize_stem_focus

        self.assertEqual(normalize_stem_focus("raw:center"), "raw:center")
        self.assertEqual(normalize_stem_focus("raw:Center"), "raw:center")
        # A bare unrecognized token is a typo, not a specialty pick: permissive
        # coercion drops it (export everything), strict mode rejects it.
        self.assertEqual(normalize_stem_focus("center"), "")
        self.assertEqual(normalize_stem_focus("vocalss"), "")
        with self.assertRaises(ValueError):
            normalize_stem_focus("vocalss", strict=True)
        self.assertEqual(normalize_stem_focus("raw:center", strict=True), "raw:center")

    def test_vocals_focus_matches_lead_vocals_label(self) -> None:
        """Already-remapped pair halves must still family-match ``--stems vocals``."""
        from core.stems import focus_matches_stem

        self.assertTrue(
            focus_matches_stem(StemBucket.VOCALS.value, "Lead Vocals", stem_count=2)
        )
        self.assertFalse(
            focus_matches_stem(
                StemBucket.INSTRUMENTAL.value, "Lead Vocals", stem_count=2
            )
        )

    def test_pair_flags_karaoke_vocals_picks_lead_only(self) -> None:
        from core.stems import EnsemblePair, exclusive_flags_for_pair

        self.assertEqual(
            exclusive_flags_for_pair(StemBucket.VOCALS.value, EnsemblePair.KARAOKE),
            (True, False),
        )

    def test_pair_flags_other_is_not_instrumental(self) -> None:
        """Ensemble Other halves must not go through stem_count=2 (that
        resolves native ``other`` as Instrumental)."""
        from core.stems import EnsemblePair, exclusive_flags_for_pair

        self.assertEqual(
            exclusive_flags_for_pair(
                StemBucket.INSTRUMENTAL.value, EnsemblePair.OTHER
            ),
            (False, False),
        )
        self.assertEqual(
            exclusive_flags_for_pair(StemBucket.OTHER.value, EnsemblePair.OTHER),
            (True, False),
        )

    def test_pair_flags_empty_focus_returns_none(self) -> None:
        from core.stems import EnsemblePair, exclusive_flags_for_pair

        self.assertIsNone(exclusive_flags_for_pair("", EnsemblePair.VOCALS_INSTRUMENTAL))

    def test_exclusive_flags_for_pair_positional_sentinels(self) -> None:
        from core.stems import (
            EnsemblePair,
            FOCUS_PRIMARY,
            FOCUS_SECONDARY,
            exclusive_flags_for_focus,
            exclusive_flags_for_pair,
        )

        self.assertEqual(
            exclusive_flags_for_pair(FOCUS_PRIMARY, EnsemblePair.VOCALS_INSTRUMENTAL),
            (True, False),
        )
        self.assertEqual(
            exclusive_flags_for_pair(FOCUS_SECONDARY, EnsemblePair.FOUR_STEM),
            (False, True),
        )
        self.assertEqual(
            exclusive_flags_for_focus(
                FOCUS_PRIMARY,
                primary_stem="other",
                secondary_stem="vocals",
                stem_count=2,
            ),
            (True, False),
        )


if __name__ == "__main__":
    unittest.main()
