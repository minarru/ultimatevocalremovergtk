"""Typed stem identity and hard-cutover ensemble pair coerce."""

from __future__ import annotations

import unittest
from pathlib import Path

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
from core.settings import Settings
from core.settings.coerce import coerce_field
from core.stem_roles import StemId as RoleStemId
from core.stem_roles import StemLiteral as RoleStemLiteral
from core.stems import (
    EnsemblePair,
    StemBucket,
    StemId,
    StemLiteral,
    StemRoute,
    StemRouteKind,
    bucket_for_model_stem,
    coerce_ensemble_pair,
    ensemble_pair_choices,
    export_stem_label,
    exports_named_stem,
    filename_tag,
    model_stem_routes,
    routes_matching_stems,
    run_export_routes,
    select_stem_routes,
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
        self.assertEqual(coerce_ensemble_pair("4 Stem Ensemble"), EnsemblePair.CHOOSE)

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
        self.assertEqual(EnsemblePair.OTHER.stem_halves(), (OTHER_STEM, NO_OTHER_STEM))
        self.assertEqual(EnsemblePair.DRUMS.stem_halves(), (DRUM_STEM, NO_DRUM_STEM))
        self.assertEqual(EnsemblePair.BASS.stem_halves(), (BASS_STEM, NO_BASS_STEM))


class StemCompatibilityExportTests(unittest.TestCase):
    def test_stems_reexports_the_exact_native_identity_classes(self) -> None:
        self.assertIs(StemId, RoleStemId)
        self.assertIs(StemLiteral, RoleStemLiteral)


class StemRouteTests(unittest.TestCase):
    class _MultiModel:
        primary_stem = "vocals"
        secondary_stem = "Instrumental"
        mdx_model_stems = ["drums", "bass", "other", "vocals"]
        demucs_source_list: list[str] = []
        mdx_stem_count = 4
        demucs_stem_count = 0
        is_karaoke = False
        is_bv_model = False
        is_vocal_split_model = False

    def test_multi_model_inventory_keeps_native_keys_and_derived_instrumental(self) -> None:
        routes = model_stem_routes(self._MultiModel())
        by_concept = {route.concept: route for route in routes}
        self.assertEqual(by_concept[BASS_STEM].native.raw, "bass")  # type: ignore[union-attr]
        self.assertEqual(by_concept[OTHER_STEM].label, OTHER_STEM)
        self.assertIsNone(by_concept[INST_STEM].native)
        self.assertFalse(by_concept[INST_STEM].selected_by_default)

    def test_native_and_derived_routes_resolve_by_concept(self) -> None:
        routes = model_stem_routes(self._MultiModel())
        bass = select_stem_routes(routes, BASS_STEM)
        instrumental = select_stem_routes(routes, INST_STEM)
        self.assertEqual(bass.routes[0].native.raw, "bass")  # type: ignore[union-attr]
        self.assertIsNone(instrumental.routes[0].native)

    def test_subset_complement_ignores_leftover_exclusive_flags(self) -> None:
        """Inventory complement is not gated on dead ModelConfig exclusive attrs."""

        class Model(self._MultiModel):
            mdxnet_stems_selected = ["bass"]
            is_mdx_include_stem_complement = True
            is_primary_stem_only = True
            is_secondary_stem_only = True

        routes = model_stem_routes(Model())
        derived = [route for route in routes if route.concept == INST_STEM]
        self.assertEqual(len(derived), 1)
        self.assertIsNone(derived[0].native)
        self.assertTrue(derived[0].conditional)

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


class StemsModuleBoundaryTests(unittest.TestCase):
    def test_stems_does_not_import_model_stem_semantics(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "core" / "stems.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("model_stem_semantics", source)

    def test_semantics_does_not_reexport_stem_labels(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "core" / "model_stem_semantics.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("def export_stem_label", source)
        self.assertNotIn("def resolve_stem_dict_key", source)
        self.assertNotIn("def ensemble_stem_bucket", source)
        self.assertNotIn("def model_stem_count", source)
        self.assertNotIn("def ensemble_pair_buckets", source)
        self.assertNotIn("BUCKET_VOCALS =", source)

    def test_semantics_module_has_no_stem_label_helpers(self) -> None:
        import core.model_stem_semantics as semantics

        self.assertFalse(hasattr(semantics, "export_stem_label"))
        self.assertFalse(hasattr(semantics, "resolve_stem_dict_key"))
        self.assertFalse(hasattr(semantics, "ensemble_stem_bucket"))
        self.assertFalse(hasattr(semantics, "model_stem_count"))
        self.assertFalse(hasattr(semantics, "ensemble_pair_buckets"))
        self.assertFalse(hasattr(semantics, "BUCKET_VOCALS"))


def _route(name: str, concept: str) -> StemRoute:
    return StemRoute(
        native=StemId(name),
        concept=concept,
        label=name,
        filename_tag=name,
        kind=StemRouteKind.NATIVE,
    )


class RunExportRoutesTests(unittest.TestCase):
    def _model(self, **kwargs: object):
        from types import SimpleNamespace

        values: dict[str, object] = dict(
            available_stem_routes=(),
            selected_stem_routes=(),
            is_vocal_split_model=False,
            is_ensemble_mode=False,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_inst_only_voc_splitter=False,
            is_sec_bv_rebalance=False,
            settings=Settings.defaults(),
            primary_stem="vocals",
            secondary_stem="other",
            is_karaoke=False,
            is_bv_model=False,
            mdx_stem_count=2,
            demucs_stem_count=0,
            mdx_model_stems=[],
            demucs_source_list=[],
        )
        values.update(kwargs)
        return SimpleNamespace(**values)

    def test_splitter_emits_full_inventory(self) -> None:
        available = (
            _route("vocals", StemBucket.VOCALS.value),
            _route("other", StemBucket.INSTRUMENTAL.value),
        )
        model = self._model(
            available_stem_routes=available,
            selected_stem_routes=available[:1],
            is_vocal_split_model=True,
        )
        self.assertEqual(run_export_routes(model), available)

    def test_four_stem_ensemble_member_emits_full_inventory(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.FOUR_STEM
        available = (
            _route("drums", StemBucket.DRUMS.value),
            _route("bass", StemBucket.BASS.value),
            _route("other", StemBucket.OTHER.value),
            _route("vocals", StemBucket.VOCALS.value),
        )
        model = self._model(
            available_stem_routes=available,
            selected_stem_routes=(available[1],),
            is_ensemble_mode=True,
            settings=settings,
            mdx_stem_count=4,
        )
        self.assertEqual(run_export_routes(model), available)
        self.assertTrue(exports_named_stem(model, "vocals"))
        self.assertTrue(exports_named_stem(model, "bass"))

    def test_focused_run_uses_selected(self) -> None:
        available = (
            _route("drums", StemBucket.DRUMS.value),
            _route("bass", StemBucket.BASS.value),
            _route("other", StemBucket.OTHER.value),
            _route("vocals", StemBucket.VOCALS.value),
        )
        selected = (available[1],)
        model = self._model(
            available_stem_routes=available,
            selected_stem_routes=selected,
            mdx_stem_count=4,
        )
        self.assertEqual(run_export_routes(model), selected)
        self.assertTrue(exports_named_stem(model, "bass"))
        self.assertFalse(exports_named_stem(model, "vocals"))


class RoutesMatchingStemsTests(unittest.TestCase):
    def test_matches_canonical_labels_to_yaml_natives(self) -> None:
        routes = (
            _route("drums", StemBucket.DRUMS.value),
            _route("bass", StemBucket.BASS.value),
            _route("other", StemBucket.OTHER.value),
            _route("vocals", StemBucket.VOCALS.value),
        )
        matched = routes_matching_stems(routes, [BASS_STEM, DRUM_STEM])
        self.assertEqual(
            [route.native.raw if route.native else "" for route in matched],
            ["bass", "drums"],
        )

    def test_skips_derived_routes(self) -> None:
        derived = StemRoute(
            native=None,
            concept=StemBucket.INSTRUMENTAL.value,
            label=INST_STEM,
            filename_tag=INST_STEM,
            kind=StemRouteKind.DERIVED,
        )
        routes = (
            _route("vocals", StemBucket.VOCALS.value),
            derived,
            _route("bass", StemBucket.BASS.value),
        )
        matched = routes_matching_stems(routes, [INST_STEM, BASS_STEM])
        self.assertEqual([route.concept for route in matched], [StemBucket.BASS.value])


if __name__ == "__main__":
    unittest.main()
