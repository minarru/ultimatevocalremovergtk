"""Typed stem identity and hard-cutover ensemble pair coerce."""

import unittest

from bundled.constants import (
    BASS_STEM,
    DRUM_STEM,
    INST_STEM,
    NO_BASS_STEM,
    NO_DRUM_STEM,
    NO_OTHER_STEM,
    OTHER_STEM,
    VOCAL_PAIR,
    VOCAL_STEM,
)
from core.settings.coerce import coerce_field
from core.stems import (
    EnsemblePair,
    StemBucket,
    StemLiteral,
    bucket_for_model_stem,
    coerce_ensemble_pair,
    ensemble_pair_choices,
    export_stem_label,
    filename_tag,
    ui_label,
)


class EnsemblePairCoerceTests(unittest.TestCase):
    def test_accepts_stable_ids(self) -> None:
        self.assertEqual(coerce_ensemble_pair("karaoke"), EnsemblePair.KARAOKE)
        self.assertEqual(
            coerce_ensemble_pair("vocals_instrumental"),
            EnsemblePair.VOCALS_INSTRUMENTAL,
        )
        self.assertEqual(coerce_ensemble_pair(EnsemblePair.OTHER), EnsemblePair.OTHER)
        self.assertEqual(coerce_ensemble_pair("four_stem"), EnsemblePair.FOUR_STEM)

    def test_legacy_display_string_becomes_choose(self) -> None:
        self.assertEqual(coerce_ensemble_pair(VOCAL_PAIR), EnsemblePair.CHOOSE)
        self.assertEqual(
            coerce_ensemble_pair("Lead Vocals/Instrumental (With Backing Vocals)"),
            EnsemblePair.CHOOSE,
        )
        self.assertEqual(
            coerce_ensemble_pair("4 Stem Ensemble"), EnsemblePair.CHOOSE
        )

    def test_unknown_becomes_choose(self) -> None:
        self.assertEqual(coerce_ensemble_pair("nope"), EnsemblePair.CHOOSE)
        self.assertEqual(coerce_ensemble_pair(None), EnsemblePair.CHOOSE)

    def test_coerce_field_settings_path(self) -> None:
        self.assertEqual(
            coerce_field("ensemble", "main_stem", "multi_stem"),
            EnsemblePair.MULTI_STEM,
        )
        self.assertEqual(
            coerce_field("ensemble", "main_stem", "Vocals/Instrumental"),
            EnsemblePair.CHOOSE,
        )


class StemHalvesTests(unittest.TestCase):
    def test_pair_halves(self) -> None:
        self.assertEqual(
            EnsemblePair.VOCALS_INSTRUMENTAL.stem_halves(),
            (VOCAL_STEM, INST_STEM),
        )
        self.assertEqual(
            EnsemblePair.OTHER.stem_halves(), (OTHER_STEM, NO_OTHER_STEM)
        )
        self.assertEqual(
            EnsemblePair.DRUMS.stem_halves(), (DRUM_STEM, NO_DRUM_STEM)
        )
        self.assertEqual(
            EnsemblePair.BASS.stem_halves(), (BASS_STEM, NO_BASS_STEM)
        )

    def test_non_pair_halves_empty(self) -> None:
        for pair in (
            EnsemblePair.CHOOSE,
            EnsemblePair.FOUR_STEM,
            EnsemblePair.MULTI_STEM,
        ):
            with self.subTest(pair=pair):
                self.assertEqual(pair.stem_halves(), ("", ""))


class FilenameTagTests(unittest.TestCase):
    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            filename_tag(StemBucket.UNKNOWN)

    def test_bucket_and_literal(self) -> None:
        self.assertEqual(filename_tag(StemBucket.LEAD_VOCALS), "Lead_Vocals")
        self.assertEqual(filename_tag(StemLiteral("Speech")), "Speech")


class BucketAndExportTests(unittest.TestCase):
    def test_karaoke_buckets(self) -> None:
        self.assertEqual(
            bucket_for_model_stem("Vocals", stem_count=2, is_karaoke=True),
            StemBucket.LEAD_VOCALS,
        )
        self.assertEqual(
            EnsemblePair.KARAOKE.buckets(),
            (StemBucket.LEAD_VOCALS, StemBucket.INST_WITH_BV),
        )

    def test_export_label_matches_bucket_value(self) -> None:
        class M:
            is_karaoke = True
            is_bv_model = False
            mdx_stem_count = 2
            demucs_stem_count = 0
            mdx_model_stems = []
            demucs_source_list = []

        self.assertEqual(
            export_stem_label(M(), "Vocals", for_ensemble=True),
            StemBucket.LEAD_VOCALS.value,
        )

    def test_ui_label_for_pair(self) -> None:
        self.assertEqual(ui_label(EnsemblePair.VOCALS_INSTRUMENTAL), "Vocals/Instrumental")
        self.assertIn("Lead Vocals", ui_label(EnsemblePair.KARAOKE))
        self.assertEqual(ui_label(EnsemblePair.FOUR_STEM), "4 Stem Ensemble")

    def test_choices_ids_are_stable(self) -> None:
        ids = [stored for stored, _label in ensemble_pair_choices()]
        self.assertIn("vocals_instrumental", ids)
        self.assertIn("karaoke", ids)
        self.assertNotIn(VOCAL_PAIR, ids)


if __name__ == "__main__":
    unittest.main()
