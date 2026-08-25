"""Exact reviewed pair IDs drive combo choices, halves, and routes."""

import tempfile
import unittest

from core.stem_pairs import (
    ensemble_pair_choices,
    is_stem_mode,
    stem_pair_definition,
    stem_pair_display,
    stem_pair_halves,
)
from core.stems import (
    StemId,
    StemRoleId,
    StemRoute,
    StemRouteKind,
    routes_for_ensemble_pair,
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
                definition = stem_pair_definition(stored)
                if definition is not None:
                    self.assertEqual(label, definition.display)
                elif is_stem_mode(stored) or not stored:
                    self.assertEqual(label, stem_pair_display(stored))
                else:
                    self.fail(f"unexpected ensemble choice {stored!r}")

    def test_karaoke_id_is_offered(self) -> None:
        ids = [stored for stored, _label in ensemble_pair_choices()]
        self.assertIn("pair.karaoke", ids)

    def test_stem_halves_are_slash_free_labels(self) -> None:
        primary, secondary = stem_pair_halves("pair.karaoke")
        self.assertTrue(primary)
        self.assertTrue(secondary)
        self.assertNotIn("/", primary)
        self.assertNotIn("/", secondary)

    def test_unknown_or_mode_ids_have_no_pair_halves(self) -> None:
        self.assertEqual(stem_pair_halves("mode.four_stem"), ("", ""))
        self.assertEqual(stem_pair_halves("Vocals/Instrumental"), ("", ""))

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
