"""Mapping an EnsemblePair id to its two buckets / combo choices."""

import tempfile
import unittest

from core.stem_pairs import is_stem_mode, stem_pair_definition
from core.stems import (
    EnsemblePair,
    StemBucket,
    StemId,
    StemRoleId,
    StemRoute,
    StemRouteKind,
    coerce_ensemble_pair,
    ensemble_pair_choices,
    routes_for_ensemble_pair,
    ui_label,
)


class PairBucketTests(unittest.TestCase):
    def test_vocal_pair(self) -> None:
        self.assertEqual(
            coerce_ensemble_pair("pair.vocals_instrumental").buckets(),
            (StemBucket.VOCALS, StemBucket.INSTRUMENTAL),
        )
        self.assertEqual(
            coerce_ensemble_pair("vocals_instrumental"),
            EnsemblePair.CHOOSE,
        )

    def test_karaoke_pair(self) -> None:
        self.assertEqual(
            coerce_ensemble_pair("pair.karaoke").buckets(),
            (StemBucket.LEAD_VOCALS, StemBucket.INST_WITH_BV),
        )
        self.assertEqual(
            coerce_ensemble_pair("karaoke"),
            EnsemblePair.CHOOSE,
        )

    def test_other_pair_keeps_other_as_a_real_stem(self) -> None:
        # Regression: resolving this through bucket_for_model_stem would give
        # StemBucket.INSTRUMENTAL, because a 1-stem 'other' is the instrumental
        # complement. A pair is a request, not a model description.
        self.assertEqual(
            EnsemblePair.OTHER.buckets(),
            (StemBucket.OTHER, StemBucket.UNKNOWN),
        )

    def test_bass_pair(self) -> None:
        primary, _secondary = EnsemblePair.BASS.buckets()
        self.assertEqual(primary, StemBucket.BASS)

    def test_complement_half_is_unknown_not_a_bucket(self) -> None:
        # 'No Other' / 'No Bass' are derived by inversion, never trained, so
        # they are not a bucket any model can match. Callers discard UNKNOWN.
        for pair in (EnsemblePair.OTHER, EnsemblePair.BASS, EnsemblePair.DRUMS):
            with self.subTest(pair=pair):
                self.assertEqual(pair.buckets()[1], StemBucket.UNKNOWN)

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
    def test_ensemble_pair_choices_use_current_namespaced_ids(self) -> None:
        choices = list(ensemble_pair_choices())
        ids = [stored for stored, _label in choices]
        self.assertEqual(
            ids,
            [
                "",
                "pair.vocals_instrumental",
                "pair.karaoke",
                "pair.backing_vocals",
                "pair.center_side",
                "mode.four_stem",
                "mode.multi_stem",
            ],
        )
        for stored, label in choices:
            with self.subTest(stored=stored):
                pair = coerce_ensemble_pair(stored)
                self.assertIsInstance(pair, EnsemblePair)
                definition = stem_pair_definition(stored)
                if definition is not None:
                    self.assertEqual(label, definition.display)
                elif is_stem_mode(stored) or not stored:
                    self.assertEqual(label, ui_label(pair))
                else:
                    self.fail(f"unexpected ensemble choice {stored!r}")

    def test_karaoke_id_is_offered(self) -> None:
        ids = [stored for stored, _label in ensemble_pair_choices()]
        self.assertIn("pair.karaoke", ids)

    def test_stem_halves_are_slash_free_labels(self) -> None:
        primary, secondary = EnsemblePair.KARAOKE.stem_halves()
        self.assertTrue(primary)
        self.assertTrue(secondary)
        self.assertNotIn("/", primary)
        self.assertNotIn("/", secondary)

    def test_center_side_uses_the_reviewed_pair_role_labels(self) -> None:
        from core.ensembler import Ensembler
        from core.settings import Settings

        definition = stem_pair_definition("pair.center_side")
        assert definition is not None
        self.assertEqual(definition.display, "Center/Side")
        routes = (
            StemRoute(
                StemId("center"),
                StemRoleId("spatial.center"),
                label="Center",
                filename_tag="Center",
                kind=StemRouteKind.NATIVE,
            ),
            StemRoute(
                StemId("wide"),
                StemRoleId("spatial.side"),
                label="Side",
                filename_tag="Side",
                kind=StemRouteKind.NATIVE,
            ),
        )
        self.assertEqual(routes_for_ensemble_pair(routes, definition), routes)

        with tempfile.TemporaryDirectory() as export_path:
            settings = Settings.defaults()
            settings.ensemble.main_stem = "pair.center_side"
            settings.ensemble.save_all_outputs = True
            settings.process.export_path = export_path
            ensembler = Ensembler(settings)

        self.assertEqual(ensembler.ensemble_primary_stem, "Center")
        self.assertEqual(ensembler.ensemble_secondary_stem, "Side")

    def test_routes_for_pair_accepts_the_reviewed_definition(self) -> None:
        """A pair is its exact two role IDs, never its display spelling."""
        definition = stem_pair_definition("pair.center_side")
        assert definition is not None
        routes = (
            StemRoute(
                StemId("Similarity"),
                StemRoleId("spatial.center"),
                label="Center",
                filename_tag="Center",
                kind=StemRouteKind.NATIVE,
            ),
            StemRoute(
                StemId("Difference"),
                StemRoleId("spatial.side"),
                label="Side",
                filename_tag="Side",
                kind=StemRouteKind.NATIVE,
            ),
        )

        self.assertEqual(routes_for_ensemble_pair(routes, definition), routes)


if __name__ == "__main__":
    unittest.main()
