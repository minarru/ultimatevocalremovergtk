"""Typed stem identity and hard-cutover ensemble pair coerce."""

from __future__ import annotations

import unittest
from pathlib import Path

from bundled.constants import (
    BASS_STEM,
    DRUM_STEM,
    INST_STEM,
    OTHER_STEM,
    VOCAL_PAIR,
)
from core.settings import Settings
from core.settings.coerce import coerce_field
from core.stem_pairs import ensemble_pair_choices, stem_pair_display, stem_pair_halves
from core.stem_roles import (
    ModelStemSemantics,
    SemanticStemOutput,
    StemProcessingContext,
    StemProduction,
    StemReviewStatus,
    StemRoleId,
)
from core.stem_roles import (
    StemId as RoleStemId,
)
from core.stem_roles import (
    StemLiteral as RoleStemLiteral,
)
from core.stems import (
    StemBucket,
    StemId,
    StemLiteral,
    StemRoute,
    StemRouteKind,
    StemSelectionStatus,
    _semantic_routes,
    bucket_for_model_stem,
    export_stem_label,
    exports_named_stem,
    filename_tag,
    model_stem_routes,
    persisted_stem_focus,
    routes_matching_stems,
    run_export_routes,
    select_stem_routes,
)


class EnsemblePairCoerceTests(unittest.TestCase):
    def test_coerce_field_settings_path(self) -> None:
        self.assertEqual(
            coerce_field("ensemble", "main_stem", "mode.multi_stem"),
            "mode.multi_stem",
        )
        self.assertEqual(
            coerce_field("ensemble", "main_stem", "Vocals/Instrumental"),
            "",
        )


class StemCompatibilityExportTests(unittest.TestCase):
    def test_stems_reexports_the_exact_native_identity_classes(self) -> None:
        self.assertIs(StemId, RoleStemId)
        self.assertIs(StemLiteral, RoleStemLiteral)


class StemRouteTests(unittest.TestCase):
    class _ReviewedReversePrimaryModel:
        """The manifest declares Instrumental logical-primary, not Vocals."""

        canonical_id = "demucs:UVR_Demucs_Model_1"
        primary_stem = "Vocals"
        secondary_stem = "Instrumental"
        mdx_model_stems: list[str] = []
        demucs_source_list = ["VoCaLs", "INSTRUMENTAL"]
        mdx_stem_count = 0
        demucs_stem_count = 2
        is_karaoke = False
        is_bv_model = False
        is_vocal_split_model = False

    def test_reviewed_routes_keep_native_spelling_and_logical_primary(self) -> None:
        routes = model_stem_routes(self._ReviewedReversePrimaryModel())
        by_role = {route.role: route for route in routes}

        instrumental = by_role[StemRoleId("mix.instrumental")]
        self.assertEqual(instrumental.native, StemId("INSTRUMENTAL"))
        self.assertEqual(instrumental.concept, "mix.instrumental")
        self.assertTrue(instrumental.logical_primary)
        self.assertFalse(by_role[StemRoleId("vocal.vocals")].logical_primary)

    def test_reviewed_false_default_survives_route_selection(self) -> None:
        semantics = ModelStemSemantics(
            model_id="mdx:fixture",
            context=StemProcessingContext.FULL_MIX,
            intent="dual_voc_inst",
            outputs=(
                SemanticStemOutput(
                    native=StemId("Vocals"),
                    role=StemRoleId("vocal.vocals"),
                    production=StemProduction.NATIVE,
                    backend_primary=True,
                    logical_primary=True,
                ),
                SemanticStemOutput(
                    native=StemId("Instrumental"),
                    role=StemRoleId("mix.instrumental"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                    selected_by_default=False,
                ),
            ),
            status=StemReviewStatus.REVIEWED,
            evidence="fixture",
        )

        routes = _semantic_routes(semantics)
        by_role = {route.role: route for route in routes}

        self.assertFalse(by_role[StemRoleId("mix.instrumental")].selected_by_default)
        self.assertEqual(
            [route.role for route in select_stem_routes(routes, "").routes],
            [StemRoleId("vocal.vocals")],
        )

    def test_target_instrument_route_keeps_explicit_derived_dependency(self) -> None:
        class Model:
            canonical_id = "mdx:mbr_inst2_unwa"
            primary_stem = INST_STEM
            primary_stem_native = "other"
            secondary_stem = "Vocals"
            target_instrument = "other"
            mdx_model_stems = ["other"]
            demucs_source_list: list[str] = []
            mdx_stem_count = 1
            demucs_stem_count = 0
            is_karaoke = False
            is_bv_model = False
            is_vocal_split_model = False

        routes = model_stem_routes(Model())

        self.assertEqual(
            [route.role for route in routes],
            [StemRoleId("mix.instrumental"), StemRoleId("vocal.vocals")],
        )
        self.assertEqual(routes[0].native, StemId("other"))
        self.assertEqual(routes[0].derived_from, ())
        self.assertIsNone(routes[0].complement_of)
        self.assertIsNone(routes[1].native)
        self.assertEqual(routes[1].kind, StemRouteKind.DERIVED)
        self.assertEqual(routes[1].derived_from, ())
        self.assertEqual(routes[1].complement_of, StemRoleId("mix.instrumental"))

        # The dependency remains intact through semantic-role dedupe.
        duplicated = routes + (routes[1],)
        from core.stems import _dedupe_routes

        deduped = _dedupe_routes(duplicated)
        self.assertEqual(deduped[1].complement_of, StemRoleId("mix.instrumental"))

    def test_unknown_or_signature_mismatched_id_stays_raw_and_isolated(self) -> None:
        class Unknown(self._ReviewedReversePrimaryModel):
            canonical_id = "mdx:unreviewed-model"

        class Mismatched(self._ReviewedReversePrimaryModel):
            demucs_source_list = ["Vocals", "Instrumental", "Residual"]

        for model in (Unknown(), Mismatched()):
            with self.subTest(model=type(model).__name__):
                routes = model_stem_routes(model)
                self.assertTrue(all(isinstance(route.role, StemLiteral) for route in routes))
                natives = tuple(route.native for route in routes)
                self.assertTrue(all(native is not None for native in natives))
                self.assertEqual(
                    tuple(route.concept for route in routes),
                    tuple(f"raw:{native.raw.casefold()}" for native in natives if native),
                )
                self.assertEqual(
                    tuple(route.label for route in routes),
                    tuple(native.raw for native in natives if native),
                )

    def test_semantic_focus_matches_a_role_and_empty_focus_keeps_all_defaults(self) -> None:
        routes = model_stem_routes(self._ReviewedReversePrimaryModel())
        self.assertEqual(
            [route.role for route in select_stem_routes(routes, "mix.instrumental").routes],
            [StemRoleId("mix.instrumental")],
        )
        self.assertEqual(select_stem_routes(routes, "").routes, routes)

    def test_reviewed_routes_present_logical_primary_before_manifest_order(self) -> None:
        class Model(self._ReviewedReversePrimaryModel):
            canonical_id = "mdx:MDX23C_D1581"
            demucs_source_list: list[str] = []
            mdx_model_stems = ["Instrumental", "Vocals"]
            mdx_stem_count = 2
            demucs_stem_count = 0

        routes = model_stem_routes(Model())
        self.assertEqual(
            [route.concept for route in routes],
            ["vocal.vocals", "mix.instrumental"],
        )
        self.assertEqual(
            [route.native.raw if route.native is not None else "" for route in routes],
            ["Vocals", "Instrumental"],
        )
        self.assertEqual(select_stem_routes(routes, "").routes, routes)
        self.assertEqual(
            select_stem_routes(routes, "primary").status,
            StemSelectionStatus.UNMATCHED,
        )

    def test_raw_focus_is_scoped_and_legacy_names_cannot_select_semantic_routes(self) -> None:
        class First(self._ReviewedReversePrimaryModel):
            canonical_id = "mdx:unreviewed-first"

        class Second(self._ReviewedReversePrimaryModel):
            canonical_id = "mdx:unreviewed-second"

        class DifferentSignature(First):
            demucs_source_list = ["VoCaLs", "INSTRUMENTAL", "Residual"]

        raw_routes = model_stem_routes(First())
        other_raw_routes = model_stem_routes(Second())
        raw_focus = persisted_stem_focus(raw_routes[0])

        self.assertEqual(select_stem_routes(raw_routes, raw_focus).routes, raw_routes[:1])
        self.assertEqual(
            select_stem_routes(other_raw_routes, raw_focus).status,
            StemSelectionStatus.UNMATCHED,
        )
        self.assertEqual(
            select_stem_routes(model_stem_routes(DifferentSignature()), raw_focus).status,
            StemSelectionStatus.UNMATCHED,
        )
        self.assertEqual(
            select_stem_routes(raw_routes, raw_routes[0].concept).status,
            StemSelectionStatus.UNMATCHED,
        )
        self.assertEqual(
            select_stem_routes(raw_routes, "Vocals").status,
            StemSelectionStatus.UNMATCHED,
        )
        self.assertEqual(
            select_stem_routes(
                model_stem_routes(self._ReviewedReversePrimaryModel()), "Vocals"
            ).status,
            StemSelectionStatus.UNMATCHED,
        )

    def test_cached_semantics_are_rejected_after_model_id_signature_or_context_mutation(
        self,
    ) -> None:
        class Model(self._ReviewedReversePrimaryModel):
            canonical_id = "mdx:MDX23C_D1581"
            demucs_source_list: list[str] = []
            mdx_model_stems = ["Instrumental", "Vocals"]
            mdx_stem_count = 2
            demucs_stem_count = 0
            stem_semantics = None

        model = Model()
        model_stem_routes(model)
        cached = model.stem_semantics
        self.assertIsNotNone(cached)

        model.canonical_id = "mdx:not-the-cached-model"
        self.assertTrue(
            all(isinstance(route.role, StemLiteral) for route in model_stem_routes(model))
        )
        self.assertIsNot(model.stem_semantics, cached)

        model.canonical_id = "mdx:MDX23C_D1581"
        model.mdx_model_stems = ["Vocals", "Instrumental"]
        routes_after_signature_mutation = model_stem_routes(model)
        self.assertTrue(
            all(isinstance(route.role, StemRoleId) for route in routes_after_signature_mutation)
        )
        self.assertIsNot(model.stem_semantics, cached)

        model.mdx_model_stems = ["Instrumental", "Vocals"]
        model.is_vocal_split_model = True
        self.assertTrue(
            all(isinstance(route.role, StemLiteral) for route in model_stem_routes(model))
        )

    def test_cached_semantics_track_caller_signature_order_and_spelling(self) -> None:
        class Model(self._ReviewedReversePrimaryModel):
            canonical_id = "mdx:MDX23C_D1581"
            demucs_source_list: list[str] = []
            mdx_model_stems = ["Instrumental", "Vocals"]
            mdx_stem_count = 2
            demucs_stem_count = 0
            stem_semantics = None

        model = Model()
        first_routes = model_stem_routes(model)
        first_cached = model.stem_semantics
        self.assertEqual(
            [route.native.raw for route in first_routes if route.native],
            ["Vocals", "Instrumental"],
        )
        self.assertIs(model_stem_routes(model) and model.stem_semantics, first_cached)

        model.mdx_model_stems = ["instrumental", "vocals"]
        lower_routes = model_stem_routes(model)
        lower_cached = model.stem_semantics
        self.assertIsNot(lower_cached, first_cached)
        self.assertEqual(
            [route.native.raw for route in lower_routes if route.native],
            ["vocals", "instrumental"],
        )

        model.mdx_model_stems = ["Vocals", "Instrumental"]
        reversed_routes = model_stem_routes(model)
        self.assertIsNot(model.stem_semantics, lower_cached)
        self.assertEqual(
            [route.native.raw for route in reversed_routes if route.native],
            ["Vocals", "Instrumental"],
        )

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
        for pair_id in ("", "mode.four_stem", "mode.multi_stem"):
            with self.subTest(pair_id=pair_id):
                self.assertEqual(stem_pair_halves(pair_id), ("", ""))


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
        self.assertEqual(stem_pair_display("pair.vocals_instrumental"), "Vocals/Instrumental")
        self.assertIn("Lead Vocals", stem_pair_display("pair.karaoke"))
        self.assertEqual(stem_pair_display("mode.four_stem"), "4 Stem Ensemble")

    def test_choices_ids_are_stable(self) -> None:
        ids = [stored for stored, _label in ensemble_pair_choices()]
        self.assertIn("pair.vocals_instrumental", ids)
        self.assertIn("pair.karaoke", ids)
        self.assertNotIn(VOCAL_PAIR, ids)


class StemsModuleBoundaryTests(unittest.TestCase):
    def test_stems_routes_through_the_reviewed_manifest(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "core" / "stems.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("resolve_model_stem_semantics", source)

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
        settings.ensemble.main_stem = "mode.four_stem"
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
