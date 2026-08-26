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
    FOCUS_PRIMARY,
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

    def test_explicit_logical_secondary_survives_semantic_route_projection(self) -> None:
        secondary_role = StemRoleId("vocal.lead")
        semantics = ModelStemSemantics(
            model_id="mdx:fixture",
            context=StemProcessingContext.FULL_MIX,
            intent="karaoke",
            outputs=(
                SemanticStemOutput(
                    native=StemId("Lead"),
                    role=secondary_role,
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                    logical_secondary=True,
                ),
                SemanticStemOutput(
                    native=StemId("Backing"),
                    role=StemRoleId("vocal.backing"),
                    production=StemProduction.NATIVE,
                    backend_primary=True,
                    logical_primary=True,
                ),
            ),
            status=StemReviewStatus.REVIEWED,
            evidence="fixture",
            logical_secondary_role=secondary_role,
        )

        routes = _semantic_routes(semantics)

        self.assertEqual([route.logical_secondary for route in routes], [False, True])
        self.assertEqual(
            [route.role for route in routes if route.logical_secondary],
            [secondary_role],
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
        self.assertIn("resolve_catalogue_stem_semantics", source)

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

    def _apply_focus(
        self,
        *,
        mode: str,
        routes: tuple[StemRoute, ...],
        focus: str,
        sidecar: tuple[str, ...] = (),
    ):
        from unittest import mock

        from core.model_config.config import ModelConfig

        settings = Settings.defaults()
        settings.ensemble.main_stem = mode
        settings.process.stem_focus = focus
        model = self._model(
            available_stem_routes=routes,
            selected_stem_routes=(),
            is_ensemble_mode=True,
            settings=settings,
            primary_stem="vocals",
            secondary_stem="other",
            mdx_model_stems=[route.native.raw for route in routes if route.native is not None],
            mdxnet_stems_selected=list(sidecar),
        )
        with mock.patch("core.stems.model_stem_routes", return_value=routes):
            ModelConfig._apply_stem_focus(model)  # type: ignore[arg-type]
        return model

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
            selected_stem_routes=available,
            is_ensemble_mode=True,
            settings=settings,
            mdx_stem_count=4,
        )
        self.assertEqual(run_export_routes(model), available)
        self.assertTrue(exports_named_stem(model, "vocals"))
        self.assertTrue(exports_named_stem(model, "bass"))

    def test_stem_mode_focus_resolves_exactly_from_available_routes(self) -> None:
        available = (
            StemRoute(
                StemId("drums"),
                StemRoleId("instrument.drums"),
                label="Drums",
                filename_tag="Drums",
            ),
            StemRoute(
                StemId("bass"),
                StemRoleId("instrument.bass"),
                label="Bass",
                filename_tag="Bass",
            ),
            StemRoute(
                StemId("other"),
                StemRoleId("residual.other"),
                label="Residual",
                filename_tag="Residual",
                logical_secondary=True,
            ),
            StemRoute(
                StemId("vocals"),
                StemRoleId("vocal.vocals"),
                label="Vocals",
                filename_tag="Vocals",
                logical_primary=True,
            ),
            StemRoute(
                StemId("mystery"),
                StemLiteral("mystery"),
                label="Mystery",
                filename_tag="Mystery",
                selected_by_default=False,
                selection_scope="fixture",
            ),
        )
        cases = (
            (
                "mode.four_stem",
                "instrument.bass",
                available,
                StemRoleId("instrument.bass"),
            ),
            (
                "mode.multi_stem",
                persisted_stem_focus(available[4]),
                tuple(route for route in available if route.selected_by_default),
                StemLiteral("mystery"),
            ),
            ("mode.four_stem", FOCUS_PRIMARY, available, StemRoleId("vocal.vocals")),
            (
                "mode.multi_stem",
                "secondary",
                tuple(route for route in available if route.selected_by_default),
                StemRoleId("residual.other"),
            ),
        )
        for mode, focus, preselected, expected_role in cases:
            with self.subTest(mode=mode, focus=focus):
                settings = Settings.defaults()
                settings.ensemble.main_stem = mode
                settings.process.stem_focus = focus
                model = self._model(
                    available_stem_routes=available,
                    selected_stem_routes=preselected,
                    is_ensemble_mode=True,
                    settings=settings,
                )

                exported = run_export_routes(model)

                self.assertEqual(len(exported), 1)
                self.assertEqual(exported[0].role, expected_role)

    def test_model_config_records_default_focus_and_sidecar_provenance(self) -> None:
        routes = (
            _route("drums", StemBucket.DRUMS.value),
            _route("bass", StemBucket.BASS.value),
            _route("other", StemBucket.OTHER.value),
            _route("vocals", StemBucket.VOCALS.value),
        )
        cases = (
            ("", (), False, routes),
            ("instrument.bass", (), True, routes[1:2]),
            ("", ("drums", "bass"), True, routes[:2]),
            ("", ("drums", "bass", "other", "vocals"), True, routes),
        )
        for focus, sidecar, explicit, expected in cases:
            with self.subTest(focus=focus, sidecar=sidecar):
                model = self._apply_focus(
                    mode="mode.multi_stem",
                    routes=routes,
                    focus=focus,
                    sidecar=sidecar,
                )

                self.assertEqual(model.selected_stem_routes, expected)
                self.assertEqual(
                    getattr(model, "selected_stem_routes_explicit", None),
                    explicit,
                )

    def test_model_config_snapshots_route_selection_provenance(self) -> None:
        from unittest.mock import MagicMock

        from core.model_config.config import ModelConfig

        model = MagicMock()
        model.available_stem_routes = ()
        model.selected_stem_routes = ()
        model.selected_stem_routes_explicit = True

        ModelConfig._sync_option_groups(model)  # type: ignore[arg-type]

        self.assertIs(model.stem_routing.selected_routes_explicit, True)

    def test_giant_default_false_route_materializes_when_explicitly_focused(self) -> None:
        from core.model_stem_manifest import resolve_model_stem_semantics

        semantics = resolve_model_stem_semantics(
            "mdx:bs_karaoke_3stem_giantailab",
            native_stems=("vocals", "backing_vocal", "instrumental"),
            backend_primary="vocals",
        )
        routes = _semantic_routes(semantics)
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.multi_stem"
        settings.process.stem_focus = "mix.instrumental_with_backing_vocals"
        model = self._model(
            available_stem_routes=routes,
            selected_stem_routes=tuple(route for route in routes if route.selected_by_default),
            is_ensemble_mode=True,
            settings=settings,
        )

        exported = run_export_routes(model)
        self.assertEqual(len(exported), 1)
        self.assertEqual(
            exported[0].role,
            StemRoleId("mix.instrumental_with_backing_vocals"),
        )
        self.assertFalse(exported[0].selected_by_default)

    def test_explicit_raw_route_focus_survives_multi_stem_execution(self) -> None:
        raw_routes = (
            StemRoute(
                StemId("mystery-a"),
                StemLiteral("mystery-a"),
                label="Mystery A",
                filename_tag="Mystery_A",
                selection_scope="fixture",
            ),
            StemRoute(
                StemId("mystery-b"),
                StemLiteral("mystery-b"),
                label="Mystery B",
                filename_tag="Mystery_B",
                selection_scope="fixture",
            ),
        )
        model = self._apply_focus(
            mode="mode.multi_stem",
            routes=raw_routes,
            focus=persisted_stem_focus(raw_routes[1]),
        )

        self.assertEqual(run_export_routes(model), raw_routes[1:])

    def test_unfiltered_no_default_inventory_falls_back_to_every_route(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.multi_stem"
        available = (
            StemRoute(
                StemId("a"),
                StemLiteral("a"),
                label="A",
                filename_tag="A",
                selected_by_default=False,
            ),
            StemRoute(
                StemId("b"),
                StemLiteral("b"),
                label="B",
                filename_tag="B",
                selected_by_default=False,
            ),
        )
        model = self._model(
            available_stem_routes=available,
            selected_stem_routes=available,
            is_ensemble_mode=True,
            settings=settings,
        )

        self.assertEqual(run_export_routes(model), available)

    def test_explicit_focus_fails_on_zero_ambiguous_or_explicit_mismatch(self) -> None:
        bass = StemRoute(
            StemId("bass"),
            StemRoleId("instrument.bass"),
            label="Bass",
            filename_tag="Bass",
        )
        duplicate_bass = StemRoute(
            StemId("bass-copy"),
            StemRoleId("instrument.bass"),
            label="Bass Copy",
            filename_tag="Bass_Copy",
        )
        drums = StemRoute(
            StemId("drums"),
            StemRoleId("instrument.drums"),
            label="Drums",
            filename_tag="Drums",
        )
        cases = (
            ("raw:missing", (bass,), (bass,), False, "resolved 0"),
            ("instrument.bass", (bass, duplicate_bass), (bass,), False, "resolved 2"),
            ("instrument.bass", (bass, drums), (drums,), True, "conflicts"),
        )
        for focus, available, selected, explicit, error in cases:
            with self.subTest(focus=focus, error=error):
                settings = Settings.defaults()
                settings.ensemble.main_stem = "mode.multi_stem"
                settings.process.stem_focus = focus
                model = self._model(
                    available_stem_routes=available,
                    selected_stem_routes=selected,
                    selected_stem_routes_explicit=explicit,
                    is_ensemble_mode=True,
                    settings=settings,
                )

                with self.assertRaisesRegex(RuntimeError, error):
                    run_export_routes(model)

    def test_no_focus_honors_explicit_selection_provenance(self) -> None:
        default = _route("vocals", StemBucket.VOCALS.value)
        optional = StemRoute(
            native=None,
            role=StemRoleId("mix.instrumental"),
            label="Optional Mix",
            filename_tag="Optional_Mix",
            kind=StemRouteKind.DERIVED,
            selected_by_default=False,
        )
        available = (default, optional)
        cases = (
            (False, available, (default,)),
            (True, available, available),
            (True, (optional,), (optional,)),
        )
        for explicit, selected, expected in cases:
            with self.subTest(explicit=explicit, selected=len(selected)):
                settings = Settings.defaults()
                settings.ensemble.main_stem = "mode.multi_stem"
                model = self._model(
                    available_stem_routes=available,
                    selected_stem_routes=selected,
                    selected_stem_routes_explicit=explicit,
                    is_ensemble_mode=True,
                    settings=settings,
                )

                self.assertEqual(run_export_routes(model), expected)

    def test_dual_pair_keeps_its_explicit_selected_route(self) -> None:
        routes = (
            StemRoute(
                StemId("center"),
                StemRoleId("spatial.center"),
                label="Center",
                filename_tag="Center",
            ),
            StemRoute(
                StemId("wide"),
                StemRoleId("spatial.side"),
                label="Side",
                filename_tag="Side",
            ),
        )
        model = self._apply_focus(
            mode="pair.center_side",
            routes=routes,
            focus="spatial.center",
        )

        self.assertEqual(run_export_routes(model), routes[:1])

    def test_multi_stem_member_omits_optional_default_false_routes(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.multi_stem"
        available = (
            _route("vocals", StemBucket.VOCALS.value),
            StemRoute(
                native=None,
                role=StemRoleId("mix.instrumental"),
                label="Optional Mix",
                filename_tag="Optional_Mix",
                kind=StemRouteKind.DERIVED,
                selected_by_default=False,
                logical_primary=True,
            ),
        )
        model = self._model(
            available_stem_routes=available,
            selected_stem_routes=available,
            is_ensemble_mode=True,
            settings=settings,
        )

        self.assertEqual(run_export_routes(model), available[:1])

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
