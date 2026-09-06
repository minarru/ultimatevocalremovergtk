"""Cold-cache and mutation boundaries for planning projections and diagnostics."""

from __future__ import annotations

import copy
import dataclasses
import unittest
from types import MappingProxyType, SimpleNamespace
from typing import Any
from unittest.mock import patch

from core.catalogue_types import StemSemanticProjection
from core.job_diagnostics import (
    FocusEvidence,
    PairEvidence,
    assess_ensemble_pair,
    assess_stem_focus,
    assess_stem_semantics,
    ensemble_pair_diagnostics,
    stem_focus_diagnostics,
    stem_semantics_diagnostics,
)
from core.job_plan import ModelDescriptor, planned_output_routes
from core.job_projection import OutputRouteEvidence, select_output_routes
from core.job_route_observations import collect_ensemble_routes, collect_output_route_evidence
from core.model_stem_manifest import (
    StemPairDefinition,
    StemSemanticsRegistry,
    load_bundled_stem_semantics,
)
from core.settings import Settings
from core.stem_roles import (
    ModelStemSemantics,
    StemProcessingContext,
    StemReviewStatus,
    StemRoleDefinition,
    StemRoleFamily,
    StemRoleId,
)
from core.stems import (
    StemRoute,
    StemRouteKind,
    StemSelection,
    StemSelectionStatus,
    model_stem_routes,
)

VOCALS = StemRoleId("vocal.vocals")
INSTRUMENTAL = StemRoleId("mix.instrumental")
PAIR = StemPairDefinition(
    "pair.vocals_instrumental", "Vocals / Instrumental", (VOCALS, INSTRUMENTAL)
)
ROUTES = (
    StemRoute(None, VOCALS, "Vocals", "Vocals", StemRouteKind.DERIVED, selected_by_default=True),
    StemRoute(
        None,
        INSTRUMENTAL,
        "Instrumental",
        "Instrumental",
        StemRouteKind.DERIVED,
        selected_by_default=True,
    ),
)


def _registry() -> StemSemanticsRegistry:
    return StemSemanticsRegistry(
        MappingProxyType(
            {
                VOCALS: StemRoleDefinition(VOCALS, "Vocals", "Vocals", StemRoleFamily.VOCAL),
                INSTRUMENTAL: StemRoleDefinition(
                    INSTRUMENTAL, "Instrumental", "Instrumental", StemRoleFamily.MIX
                ),
            }
        ),
        MappingProxyType({PAIR.id: PAIR}),
        MappingProxyType({}),
        MappingProxyType({}),
    )


class PurePlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings.defaults()
        load_bundled_stem_semantics.cache_clear()
        self.addCleanup(load_bundled_stem_semantics.cache_clear)
        self.acquire = patch(
            "core.model_stem_manifest.load_stem_manifest",
            side_effect=AssertionError("pure owner acquired manifest"),
        ).start()
        self.log = patch(
            "core.debug_log.log_event", side_effect=AssertionError("pure owner logged event")
        ).start()
        self.debug_spy = patch(
            "core.debug_log.debug", side_effect=AssertionError("pure owner logged focus")
        ).start()
        self.addCleanup(patch.stopall)

    def test_ensemble_selection_does_not_acquire_manifest(self) -> None:
        settings = self.settings
        settings.ensemble.main_stem = PAIR.id
        evidence = OutputRouteEvidence(
            "",
            "",
            ROUTES,
            StemSelection(
                "", ROUTES, StemSelectionStatus.EMPTY, (VOCALS.value, INSTRUMENTAL.value)
            ),
        )
        selected = select_output_routes(settings, (), command="ensemble", evidence=evidence)
        self.assertEqual(
            [route.filename_tag for route in selected.routes], ["Vocals", "Instrumental"]
        )
        self.assertEqual(self.acquire.call_count, 0)
        self.assertEqual(self.log.call_count, 0)

    def test_pair_assessment_does_not_acquire_manifest(self) -> None:
        settings = self.settings
        settings.ensemble.main_stem = PAIR.id
        member = ModelDescriptor("vr:a", "vr", "a", "A", routes=ROUTES)
        result = assess_ensemble_pair(
            settings, (member,), command="ensemble", evidence=PairEvidence(PAIR.id, PAIR)
        )
        self.assertEqual([item.code for item in result.diagnostics], ["ensemble.pair_repick"])
        self.assertEqual(result.events[0].fields, {"pair_id": PAIR.id, "eligible_count": 1})
        self.assertEqual(self.acquire.call_count, 0)

    def test_focus_assessment_does_not_mutate_model(self) -> None:
        model = SimpleNamespace(
            canonical_id="vr:review-fixture", primary_stem="Vocals", secondary_stem="Instrumental"
        )
        before = copy.deepcopy(model.__dict__)
        selection = StemSelection(
            "raw:missing", (), StemSelectionStatus.UNMATCHED, (VOCALS.value, INSTRUMENTAL.value)
        )
        facts = FocusEvidence(
            "raw:missing",
            selection,
            "model",
            available_labels=(model.primary_stem, model.secondary_stem),
        )
        result = assess_stem_focus(facts)
        self.assertEqual(model.__dict__, before)
        self.assertEqual(
            result[0].message,
            "stem focus 'raw:missing' matches no stem of model (has Vocals, Instrumental); exporting all stems",
        )
        self.assertEqual(self.acquire.call_count, 0)

    def test_selection_does_not_log_unknown_focus(self) -> None:
        settings = self.settings
        settings.process.stem_focus = "unknown-specialty"
        descriptor = ModelDescriptor(
            "vr:a", "vr", "a", "A", primary_stem="Vocals", secondary_stem="Instrumental"
        )
        evidence = OutputRouteEvidence(
            "unknown-specialty",
            "",
            ROUTES,
            StemSelection(
                "", ROUTES, StemSelectionStatus.EMPTY, (VOCALS.value, INSTRUMENTAL.value)
            ),
        )
        result = select_output_routes(
            settings, (descriptor,), command="separate", evidence=evidence
        )
        self.assertEqual(result.reason, "focus-unmatched-fallback-defaults")
        self.assertEqual(self.debug_spy.call_count, 0)

    def test_positional_mode_selection_uses_supplied_facts(self) -> None:
        settings = self.settings
        evidence = OutputRouteEvidence("primary", "primary", ROUTES, None, ensemble_multi=True)
        result = select_output_routes(settings, (), command="ensemble", evidence=evidence)
        self.assertEqual(result.routes, ROUTES)
        self.assertEqual(result.reason, "ensemble-positional-multi")
        self.assertEqual(self.acquire.call_count, 0)

    def test_semantic_assessment_uses_supplied_projection(self) -> None:
        semantics = ModelStemSemantics(
            "vr:a",
            StemProcessingContext.FULL_MIX,
            "",
            (),
            StemReviewStatus.RAW,
            "",
            warning="raw-fallback",
        )
        descriptor = ModelDescriptor("vr:a", "vr", "a", "A", stem_semantics=semantics)
        projection = StemSemanticProjection(None, None, None, None, "raw", "full_mix", ())
        result = assess_stem_semantics(descriptor, projection)
        self.assertEqual(result.events[0].name, "stem_semantics_fallback")
        self.assertEqual(result.diagnostics[0].severity, "warning")
        self.assertEqual(self.acquire.call_count, 0)


class ObservationOrderTests(unittest.TestCase):
    def test_pair_and_role_observations_keep_positional_frequency(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = PAIR.id
        for focus, expected in [
            ("", ["pair", "pair", "role", "role"]),
            ("primary", ["pair", "pair", "role", "role", "pair"]),
        ]:
            settings.process.stem_focus = focus
            seen = []
            registry = _registry()
            with (
                patch(
                    "core.stem_pairs.load_bundled_stem_semantics",
                    side_effect=lambda observed=seen, registry=registry: observed.append("pair") or registry,
                ),
                patch(
                    "core.job_route_observations.load_bundled_stem_semantics",
                    side_effect=lambda observed=seen, registry=registry: observed.append("role") or registry,
                ),
            ):
                evidence = collect_output_route_evidence(settings, (), command="ensemble")
            self.assertEqual(seen, expected)
            self.assertEqual(evidence.routes, ROUTES)

    def test_pair_assessment_acquires_only_for_ensemble(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = PAIR.id
        registry = _registry()
        for command, calls in [("separate", 0), ("ensemble", 2)]:
            with patch(
                "core.stem_pairs.load_bundled_stem_semantics", return_value=registry
            ) as load:
                self.assertEqual(ensemble_pair_diagnostics(settings, (), command=command), ())
            self.assertEqual(load.call_count, calls)

    def test_unknown_focus_logging_remains_in_observer(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = "unknown-specialty"
        descriptor = ModelDescriptor("vr:a", "vr", "a", "A", routes=ROUTES)
        with patch("core.debug_log.debug") as debug:
            selected = planned_output_routes(settings, (descriptor,), command="separate")
        self.assertEqual(selected, ROUTES)
        debug.assert_called_once_with(
            "settings", "process.stem_focus unknown value='unknown-specialty'; using all stems"
        )

    def test_focus_gates_and_descriptor_routes_do_not_materialize_models(self) -> None:
        settings = Settings.defaults()
        model = SimpleNamespace(is_vocal_split_model=False, model_basename="M")
        descriptor = ModelDescriptor("vr:a", "vr", "a", "A", routes=ROUTES)
        with patch(
            "core.job_diagnostics.model_stem_routes",
            side_effect=AssertionError("unexpected fallback"),
        ):
            for focus in ("", "primary", "secondary"):
                settings.process.stem_focus = focus
                self.assertEqual(stem_focus_diagnostics(settings, (model,), ()), [])
            settings.process.stem_focus = "raw:missing"
            model.is_vocal_split_model = True
            self.assertEqual(stem_focus_diagnostics(settings, (model,), ()), [])
            model.is_vocal_split_model = False
            self.assertEqual(
                stem_focus_diagnostics(settings, (model,), (descriptor,))[0].code,
                "stems.focus_unmatched",
            )

    def test_focus_materializes_and_assesses_before_later_member_failure(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = "raw:missing"
        seen = []

        class Model:
            canonical_id = "vr:fixture"
            primary_stem = "Vocals"
            secondary_stem = "Instrumental"

            @property
            def model_basename(self) -> str:
                seen.append("label:first")
                return "First"

        first, second = Model(), SimpleNamespace()

        def routes(value: Any):
            seen.append("routes:first" if value is first else "routes:second")
            if value is second:
                raise ValueError("later member failed")
            return model_stem_routes(value)

        with patch("core.job_diagnostics.model_stem_routes", side_effect=routes):
            with self.assertRaisesRegex(ValueError, "later member failed"):
                stem_focus_diagnostics(settings, (first, second), ())
        self.assertEqual(seen, ["routes:first", "label:first", "routes:second"])
        self.assertIn("stem_semantics", first.__dict__)

    def test_matched_focus_never_observes_fallback_model_label(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = VOCALS.value

        class Model:
            @property
            def model_basename(self) -> str:
                raise AssertionError("matched model label was read")

        with patch("core.job_diagnostics.model_stem_routes", return_value=ROUTES):
            self.assertEqual(stem_focus_diagnostics(settings, (Model(),), ()), [])

    def test_ensemble_member_projection_precedes_later_materialization_failure(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.multi_stem"
        first = ModelDescriptor("vr:a", "vr", "a", "A")
        second = dataclasses.replace(first, id="vr:b")
        seen = []

        class Route:
            selected_by_default = True

            @property
            def role(self):
                seen.append("project:first")
                return VOCALS

        def routes(descriptor: ModelDescriptor):
            seen.append(f"routes:{descriptor.id}")
            if descriptor is second:
                raise ValueError("later descriptor failed")
            return (Route(),)

        with patch("core.job_route_observations._fallback_descriptor_routes", side_effect=routes):
            with self.assertRaisesRegex(ValueError, "later descriptor failed"):
                collect_ensemble_routes(settings, (first, second))
        self.assertEqual(seen, ["routes:vr:a", "project:first", "project:first", "routes:vr:b"])

    def test_semantic_acquisition_and_event_precede_next_descriptor(self) -> None:
        semantics = ModelStemSemantics(
            "vr:a", StemProcessingContext.FULL_MIX, "", (), StemReviewStatus.RAW, ""
        )
        first = ModelDescriptor("vr:a", "vr", "a", "A", stem_semantics=semantics)
        second = dataclasses.replace(first, id="vr:b")
        seen = []

        def project(*args: Any, **kwargs: Any):
            seen.append("acquire")
            if len(seen) > 1:
                raise ValueError("later semantic failure")
            return StemSemanticProjection(None, None, None, None, "raw", "full_mix", ())

        with (
            patch("core.job_diagnostics.stem_semantics_projection", side_effect=project),
            patch(
                "core.debug_log.log_event", side_effect=lambda *args, **kwargs: seen.append("event")
            ),
        ):
            with self.assertRaisesRegex(ValueError, "later semantic failure"):
                stem_semantics_diagnostics((first, second))
        self.assertEqual(seen, ["acquire", "event", "acquire"])
