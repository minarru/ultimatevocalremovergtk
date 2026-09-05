from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bundled.constants import (
    BASS_STEM,
    DRUM_STEM,
    VOCAL_STEM,
)
from core.export_naming import OutputNamingContext
from core.job_plan import JobSpec, ModelDescriptor, planned_output_stems
from core.job_projection import project_input, select_output_routes
from core.model_identity import ModelArtifacts
from core.settings import Settings
from core.stem_roles import StemId, StemRoleId
from core.stems import FOCUS_PRIMARY, FOCUS_SECONDARY, StemLiteral, StemRoute
from core.types import ProcessMethod
from tests.planning_fixtures import resolver_with_ports


def _desc(stem: str, secondary: str = "Instrumental", identifier: str = "mdx:a") -> ModelDescriptor:
    roles = {
        "Vocals": StemRoleId("vocal.vocals"),
        "Instrumental": StemRoleId("mix.instrumental"),
        "Bass": StemRoleId("instrument.bass"),
        "Drums": StemRoleId("instrument.drums"),
        "Other": StemRoleId("residual.other"),
    }
    routes = tuple(
        StemRoute(
            native=StemId(name),
            role=roles.get(name, StemLiteral(name)),
            label=name,
            filename_tag=name,
        )
        for name in (stem, secondary)
    )
    return ModelDescriptor(
        identifier,
        "mdx",
        "a",
        "A",
        primary_stem=stem,
        secondary_stem=secondary,
        routes=routes,
    )


def _four_desc(identifier: str) -> ModelDescriptor:
    return ModelDescriptor(
        identifier,
        "mdx",
        identifier.removeprefix("mdx:"),
        identifier,
        routes=(
            StemRoute(StemId("bass"), StemRoleId("instrument.bass"), "Bass", "Bass"),
            StemRoute(StemId("drums"), StemRoleId("instrument.drums"), "Drums", "Drums"),
            StemRoute(StemId("other"), StemRoleId("residual.other"), "Residual", "Residual"),
            StemRoute(StemId("vocals"), StemRoleId("vocal.vocals"), "Vocals", "Vocals"),
        ),
    )


def _giant_shaped_routes(*, vocal_split: bool) -> tuple[StemRoute, ...]:
    routes = [
        StemRoute(
            native=StemId("Lead"),
            role=StemRoleId("vocal.lead"),
            label="Lead Vocals",
            filename_tag="Lead_Vocals",
            logical_secondary=True,
        ),
        StemRoute(
            native=StemId("Backing"),
            role=StemRoleId("vocal.backing"),
            label="Backing Vocals",
            filename_tag="Backing_Vocals",
            logical_primary=vocal_split,
        ),
        StemRoute(
            native=StemId("Instrumental"),
            role=StemRoleId("mix.instrumental"),
            label="Instrumental",
            filename_tag="Instrumental",
        ),
    ]
    if not vocal_split:
        routes.append(
            StemRoute(
                native=None,
                role=StemRoleId("mix.instrumental_with_backing_vocals"),
                label="Instrumental with Backing Vocals",
                filename_tag="Instrumental_with_Backing_Vocals",
                logical_primary=True,
            )
        )
    return tuple(routes)


class PlannedOutputStemTests(unittest.TestCase):
    def test_plan_json_carries_raw_backend_and_exact_semantic_route_fields(self) -> None:
        from core.job_plan import ResolvedJob, ValidationLevel
        from core.model_stem_semantics import resolve_catalogue_stem_semantics

        settings = Settings.defaults()
        semantics = resolve_catalogue_stem_semantics(
            "mdx:bs_neo_inst_beta",
            native_stems=("other",),
            backend_primary="other",
            backend_target="other",
        )
        plan = ResolvedJob(
            command="separate",
            settings=settings,
            inputs=(),
            models=(
                ModelDescriptor(
                    "mdx:bs_neo_inst_beta",
                    "mdx",
                    "bs_neo_inst_beta",
                    "Beta",
                    primary_stem="other",
                    secondary_stem="vocals",
                    backend_target_stem="other",
                    stem_semantics=semantics,
                ),
            ),
            provenance={},
            diagnostics=(),
            validation_level=ValidationLevel.MODEL,
            inventory_generation=0,
            settings_fingerprint="fixture",
            device="cpu",
        ).to_dict()

        model = plan["models"][0]
        self.assertEqual(
            {
                key
                for key in model
                if key
                in {
                    "backend_primary_stem",
                    "backend_target_stem",
                    "logical_primary_role",
                    "logical_secondary_role",
                    "stem_semantics_status",
                    "stem_context",
                    "stem_routes",
                    "canonical_roles",
                    "stem_semantics_evidence",
                }
            },
            {
                "backend_primary_stem",
                "backend_target_stem",
                "logical_primary_role",
                "logical_secondary_role",
                "stem_semantics_status",
                "stem_context",
                "stem_routes",
            },
        )
        self.assertEqual(model["backend_primary_stem"], "other")
        self.assertEqual(model["backend_target_stem"], "other")
        self.assertEqual(model["logical_primary_role"], "mix.instrumental")
        self.assertIsNone(model["logical_secondary_role"])
        self.assertEqual(model["stem_semantics_status"], "reviewed")
        self.assertEqual(model["stem_context"], "full_mix")
        self.assertIsNone(model["stem_routes"][0]["native"])
        self.assertEqual(model["stem_routes"][0]["display"], "Vocals")
        self.assertEqual(model["stem_routes"][0]["production"], "derived")
        self.assertEqual(model["stem_routes"][0]["complement_of"], "mix.instrumental")
        self.assertEqual(model["stem_routes"][1]["native"], "other")
        self.assertTrue(model["stem_routes"][1]["logical_primary"])
        self.assertFalse(model["stem_routes"][1]["logical_secondary"])

    def test_raw_semantic_fallback_is_an_actionable_plan_warning(self) -> None:
        from core.job_plan import ResolvedJob, ValidationLevel
        from core.model_stem_semantics import resolve_catalogue_stem_semantics

        settings = Settings.defaults()
        semantics = resolve_catalogue_stem_semantics(
            "mdx:bs_neo_inst_beta", native_stems=("vocals", "other")
        )
        plan = ResolvedJob(
            command="separate",
            settings=settings,
            inputs=(),
            models=(
                ModelDescriptor(
                    "mdx:bs_neo_inst_beta",
                    "mdx",
                    "bs_neo_inst_beta",
                    "Beta",
                    primary_stem="other",
                    stem_semantics=semantics,
                ),
            ),
            provenance={},
            diagnostics=(),
            validation_level=ValidationLevel.MODEL,
            inventory_generation=0,
            settings_fingerprint="fixture",
            device="cpu",
        ).to_dict()

        self.assertEqual(plan["models"][0]["stem_semantics_status"], "raw")
        self.assertIn("signature-mismatch", plan["models"][0]["stem_semantics_warning"])

    def test_stem_semantic_diagnostics_log_reviewed_and_fallback_context(self) -> None:
        from core.job_diagnostics import stem_semantics_diagnostics as _stem_semantics_diagnostics
        from core.model_stem_semantics import resolve_catalogue_stem_semantics

        reviewed = ModelDescriptor(
            "mdx:bs_neo_inst_beta",
            "mdx",
            "bs_neo_inst_beta",
            "Beta",
            primary_stem="other",
            backend_target_stem="other",
            stem_semantics=resolve_catalogue_stem_semantics(
                "mdx:bs_neo_inst_beta",
                native_stems=("other",),
                backend_primary="other",
                backend_target="other",
            ),
        )
        mismatch = ModelDescriptor(
            "mdx:bs_neo_inst_beta",
            "mdx",
            "bs_neo_inst_beta",
            "Beta",
            primary_stem="other",
            stem_semantics=resolve_catalogue_stem_semantics(
                "mdx:bs_neo_inst_beta", native_stems=("vocals", "other")
            ),
        )

        with patch("core.debug_log.log_event") as event:
            diagnostics = _stem_semantics_diagnostics((reviewed, mismatch))

        self.assertEqual(diagnostics[0].code, "stems.semantics_signature_mismatch")
        calls = {call.args[1]: call.kwargs for call in event.call_args_list}
        self.assertEqual(calls["stem_semantics_routing"]["label"], "Instrumental")
        self.assertEqual(calls["stem_semantics_routing"]["role"], "mix.instrumental")
        self.assertEqual(calls["stem_semantics_routing"]["native"], "other")
        self.assertEqual(calls["stem_semantics_routing"]["context"], "full_mix")
        self.assertEqual(calls["stem_semantics_routing"]["status"], "reviewed")
        self.assertEqual(calls["stem_semantics_signature_mismatch"]["level"], "warning")

    def test_pair_selection_requires_two_distinct_reviewed_members(self) -> None:
        from core.job_diagnostics import ensemble_pair_diagnostics as _ensemble_pair_diagnostics

        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        only_one = (_desc("Vocals", "Instrumental", "mdx:one"),)
        diagnostics = _ensemble_pair_diagnostics(settings, only_one, command="ensemble")

        self.assertEqual(diagnostics[0].code, "ensemble.pair_repick")
        self.assertIn("two distinct", diagnostics[0].message)

    def test_pair_selection_rejects_an_incomplete_additional_member(self) -> None:
        from core.job_diagnostics import ensemble_pair_diagnostics as _ensemble_pair_diagnostics

        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        diagnostics = _ensemble_pair_diagnostics(
            settings,
            (
                _desc("Vocals", "Instrumental", "mdx:complete-a"),
                _desc("Vocals", "Instrumental", "mdx:complete-b"),
                _four_desc("demucs:partial-four-stem"),
            ),
            command="ensemble",
        )

        self.assertEqual(diagnostics[0].code, "ensemble.pair_repick")
        self.assertIn("Every selected member", diagnostics[0].message)

    def test_unknown_pair_selection_requests_an_explicit_repick(self) -> None:
        from core.job_diagnostics import ensemble_pair_diagnostics as _ensemble_pair_diagnostics

        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.nearby_but_wrong"
        diagnostics = _ensemble_pair_diagnostics(
            settings,
            (_desc("Vocals", "Instrumental", "mdx:one"),),
            command="ensemble",
        )

        self.assertEqual(diagnostics[0].code, "ensemble.pair_repick")
        self.assertIn("Choose a reviewed", diagnostics[0].message)

    def test_positional_primary_uses_logical_primary_not_backend_primary(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = "primary"
        descriptor = ModelDescriptor(
            "demucs:UVR_Demucs_Model_1",
            "demucs",
            "UVR_Demucs_Model_1",
            "UVR Demucs Model 1",
            primary_stem="Vocals",
            secondary_stem="Instrumental",
            routes=(
                StemRoute(
                    native=StemId("Vocals"),
                    role=StemRoleId("vocal.vocals"),
                    label="Vocals",
                    filename_tag="Vocals",
                    logical_secondary=True,
                ),
                StemRoute(
                    native=StemId("Instrumental"),
                    role=StemRoleId("mix.instrumental"),
                    label="Instrumental",
                    filename_tag="Instrumental",
                    logical_primary=True,
                ),
            ),
        )

        self.assertEqual(
            planned_output_stems(settings, (descriptor,), command="separate"),
            (("Instrumental", False),),
        )

        settings.process.stem_focus = "secondary"
        self.assertEqual(
            planned_output_stems(settings, (descriptor,), command="separate"),
            (("Vocals", False),),
        )

    def test_absent_logical_secondary_preserves_backend_position(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = FOCUS_SECONDARY
        descriptor = ModelDescriptor(
            "mdx:fixture",
            "mdx",
            "fixture",
            "No semantic secondary",
            primary_stem="Vocals",
            secondary_stem="Instrumental",
            routes=(
                StemRoute(
                    native=StemId("Vocals"),
                    role=StemRoleId("vocal.vocals"),
                    label="Vocals",
                    filename_tag="Vocals",
                ),
                StemRoute(
                    native=StemId("Instrumental"),
                    role=StemRoleId("mix.instrumental"),
                    label="Instrumental",
                    filename_tag="Instrumental",
                    logical_primary=True,
                ),
            ),
        )

        self.assertEqual(
            planned_output_stems(settings, (descriptor,), command="separate"),
            (("Instrumental", False),),
        )

    def test_positional_secondary_uses_explicit_role_across_four_and_three_routes(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = FOCUS_SECONDARY

        for vocal_split in (False, True):
            routes = _giant_shaped_routes(vocal_split=vocal_split)
            descriptor = ModelDescriptor(
                "mdx:fixture",
                "mdx",
                "fixture",
                "Giant-shaped fixture",
                primary_stem="Backing",
                secondary_stem="Instrumental",
                routes=routes,
            )

            with self.subTest(route_count=len(routes)):
                self.assertEqual(
                    planned_output_stems(settings, (descriptor,), command="separate"),
                    (("Lead Vocals", False),),
                )

    def test_separate_uses_descriptor_stems(self) -> None:
        settings = Settings.defaults()
        stems = planned_output_stems(settings, (_desc("Vocals"),), command="separate")
        self.assertEqual(stems, (("Vocals", False), ("Instrumental", False)))

    def test_ensemble_pair_ignores_first_member_stems(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        stems = planned_output_stems(
            settings,
            (_desc("Drums", "Bass"), _desc("Vocals")),
            command="ensemble",
        )
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, (VOCAL_STEM, "Instrumental"))
        self.assertFalse(any(conditional for _stem, conditional in stems))

    def test_four_stem_ensemble_is_the_standard_four(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.four_stem"
        stems = planned_output_stems(
            settings, (_four_desc("mdx:one"), _four_desc("mdx:two")), command="ensemble"
        )
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, (BASS_STEM, DRUM_STEM, "Residual", VOCAL_STEM))

    def test_four_stem_focus_filters_final_output(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.four_stem"
        settings.process.stem_focus = "instrument.bass"
        stems = planned_output_stems(
            settings, (_four_desc("mdx:one"), _four_desc("mdx:two")), command="ensemble"
        )
        self.assertEqual(stems, ((BASS_STEM, False),))

    def test_stem_mode_planner_keeps_positional_members_and_filters_semantic_final(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.four_stem"
        descriptors = (_four_desc("mdx:one"), _four_desc("mdx:two"))

        settings.process.stem_focus = "instrument.bass"
        self.assertEqual(
            planned_output_stems(settings, descriptors, command="ensemble"),
            ((BASS_STEM, False),),
        )

        for focus in (FOCUS_PRIMARY, FOCUS_SECONDARY):
            with self.subTest(focus=focus):
                settings.process.stem_focus = focus
                labels = tuple(
                    label
                    for label, _conditional in planned_output_stems(
                        settings, descriptors, command="ensemble"
                    )
                )
                self.assertEqual(labels, (BASS_STEM, DRUM_STEM, "Residual", VOCAL_STEM))

    def test_multi_stem_keeps_only_routes_with_two_contributors(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.multi_stem"
        stems = planned_output_stems(
            settings,
            (
                _desc("Vocals", "Bass", "mdx:one"),
                _desc("Vocals", "Drums", "mdx:two"),
                _desc("Bass", "Other", "mdx:three"),
            ),
            command="ensemble",
        )
        labels = {stem for stem, _conditional in stems}
        self.assertEqual(labels, {"Vocals", "Bass"})
        self.assertFalse(any(conditional for _stem, conditional in stems))

    def test_multi_stem_groups_reviewed_removal_roles_not_no_stem_spelling(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.multi_stem"
        role = StemRoleId("instrument.bass.removed")
        descriptors = (
            ModelDescriptor(
                "mdx:one",
                "mdx",
                "one",
                "One",
                routes=(StemRoute(StemId("No Bass"), role, "Bass Removed", "Bass_Removed"),),
            ),
            ModelDescriptor(
                "mdx:two",
                "mdx",
                "two",
                "Two",
                routes=(StemRoute(StemId("Bass Removed"), role, "Bass Removed", "Bass_Removed"),),
            ),
        )

        self.assertEqual(
            planned_output_stems(settings, descriptors, command="ensemble"),
            (("Bass Removed", False),),
        )

    def test_multi_stem_explicit_single_contributor_is_an_error(self) -> None:
        from core.job_diagnostics import assess_stem_focus as _stem_focus_diagnostics

        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.multi_stem"
        settings.process.stem_focus = "instrument.drums"
        descriptors = (
            _desc("Vocals", "Drums", "mdx:one"),
            _desc("Vocals", "Bass", "mdx:two"),
        )
        diagnostics = _stem_focus_diagnostics(
            settings,
            [],
            descriptors,
            {"process.stem_focus": "cli"},
            command="ensemble",
        )
        self.assertEqual(diagnostics[0].code, "stems.focus_insufficient_members")
        self.assertEqual(diagnostics[0].severity, "error")

    def test_ensemble_vocals_focus_plans_only_the_vocal_half(self) -> None:
        from bundled.constants import LEAD_VOCAL_STEM_LABEL

        settings = Settings.defaults()
        settings.process.stem_focus = "vocal.lead"
        settings.ensemble.main_stem = "pair.karaoke"
        stems = planned_output_stems(
            settings,
            (_desc("Vocals", identifier="mdx:one"), _desc("Vocals", identifier="mdx:two")),
            command="ensemble",
        )
        self.assertEqual(stems, ((LEAD_VOCAL_STEM_LABEL, False),))

    def test_ensemble_instrumental_focus_does_not_pick_other_pair(self) -> None:
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
        settings.ensemble.main_stem = "pair.center_side"
        stems = planned_output_stems(
            settings,
            (_desc("Other", "No Other"),),
            command="ensemble",
        )
        # Unmatched inherited focus falls back to the pair's complete inventory.
        self.assertEqual(stems, (("Center", False), ("Side", False)))

    def test_pair_secondary_only_plans_the_second_reviewed_role(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.center_side"
        settings.process.stem_focus = FOCUS_SECONDARY
        stems = planned_output_stems(settings, (_desc("Center", "Side"),), command="ensemble")
        self.assertEqual(stems, (("Side", False),))

    def test_separate_four_stem_other_is_not_instrumental_focus(self) -> None:
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
        desc = ModelDescriptor(
            "mdx:a",
            "mdx",
            "a",
            "A",
            primary_stem="Vocals",
            secondary_stem="other",
            stem_count=4,
        )
        stems = planned_output_stems(settings, (desc,), command="separate")
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, ("Vocals", "Other"))

    def test_separate_two_stem_other_matches_instrumental_focus(self) -> None:
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
        desc = ModelDescriptor(
            "mdx:a",
            "mdx",
            "a",
            "A",
            primary_stem="Vocals",
            secondary_stem="other",
            stem_count=2,
        )
        stems = planned_output_stems(settings, (desc,), command="separate")
        self.assertEqual(stems, (("Instrumental", False),))

    def test_multi_stem_include_complement_is_planned_conditionally(self) -> None:
        from core.stems import StemBucket, derived_stem_route, native_stem_route

        class _Model:
            primary_stem = "bass"
            secondary_stem = "No bass"
            mdx_model_stems = ["drums", "bass", "other", "vocals"]
            demucs_source_list: list[str] = []
            mdx_stem_count = 4
            demucs_stem_count = 0
            is_karaoke = False
            is_bv_model = False
            is_vocal_split_model = False

        settings = Settings.defaults()
        settings.process.stem_focus = BASS_STEM
        settings.mdx.is_mdx_include_stem_complement = True
        model = _Model()
        routes = tuple(native_stem_route(model, stem) for stem in model.mdx_model_stems) + (
            derived_stem_route("No bass", label="No bass", conditional=True),
            derived_stem_route(StemBucket.INSTRUMENTAL),
        )
        desc = ModelDescriptor(
            "mdx:a",
            "mdx",
            "a",
            "A",
            primary_stem="bass",
            secondary_stem="No bass",
            stem_count=4,
            routes=routes,
        )
        selected = select_output_routes(settings, (desc,), command="separate")
        planned = project_input("/tmp/song.wav", OutputNamingContext(
            "/tmp/song.wav", "song", "song", "/tmp/out", "wav"), selected.routes, command="separate")
        self.assertEqual(
            [(output.stem, output.conditional) for output in planned.outputs],
            [("Bass", False), ("No bass", True)],
        )

    def test_resolver_plan_outputs_use_ensemble_pair(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        settings.ensemble.selected_models = ["mdx:a", "mdx:b"]
        selected = select_output_routes(settings, (_desc("Drums", "Bass"), _desc("Vocals")), command="ensemble")
        planned = project_input("/tmp/song.wav", OutputNamingContext(
            "/tmp/song.wav", "song", "song", "/tmp/out", "wav"), selected.routes, command="ensemble")
        self.assertEqual(
            [output.stem for output in planned.outputs],
            [VOCAL_STEM, "Instrumental"],
        )

    def test_karaoke_planned_filename_uses_runtime_tag(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = "pair.karaoke"
        selected = select_output_routes(settings, (_desc("Vocals"), _desc("Vocals")), command="ensemble")
        planned = project_input("/tmp/song.wav", OutputNamingContext(
            "/tmp/song.wav", "song", "song", "/tmp/out", "wav"), selected.routes, command="ensemble")
        self.assertEqual(
            [output.stem for output in planned.outputs],
            ["Instrumental_with_Backing_Vocals", "Lead_Vocals"],
        )
        self.assertIn("(Instrumental_with_Backing_Vocals)", planned.outputs[0].path)

    def test_adhoc_ensemble_sentinel_label_is_ensembled(self) -> None:
        from bundled.constants import CHOOSE_ENSEMBLE_OPTION

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.chosen_ensemble = CHOOSE_ENSEMBLE_OPTION
        settings.ensemble.append_ensemble_name = True
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        resolver = resolver_with_ports(Mock())
        spec = JobSpec("ensemble", settings, ("/tmp/song.wav",), "/tmp/out")
        planned = resolver.plan_inputs(
            settings,
            spec,
            (_desc("Vocals"), _desc("Vocals")),
        )
        self.assertEqual(planned[0].naming.ensemble_label, "Ensembled")
        self.assertNotIn("Choose Option", planned[0].naming.track_base)


class MdxCOfflinePlanningTests(unittest.TestCase):
    def test_ensure_mdx_c_config_offline_does_not_fetch(self) -> None:
        from core.mdx_config_fetch import ensure_mdx_c_config

        with patch("core.mdx_config_fetch._fetch_url_to_file") as fetch:
            ok = ensure_mdx_c_config("definitely-missing-uvr-test.yaml", allow_network=False)
        self.assertFalse(ok)
        fetch.assert_not_called()

    def test_dependency_map_uses_exact_canonical_id(self) -> None:
        from core.model_identity import ModelRecord
        from core.settings import Settings
        from core.types import ProcessMethod

        record = ModelRecord(
            id='mdx:UVR-MDX-NET-Inst_HQ_4',
            family='mdx',
            basename='UVR-MDX-NET-Inst_HQ_4',
            display='MDX-Net — UVR-MDX-NET Inst HQ 4',
            backend_name='UVR-MDX-NET-Inst_HQ_4',
            artifacts=ModelArtifacts('UVR-MDX-NET-Inst_HQ_4.ckpt'),
            installed=True,
        )
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = record.id
        resolver = resolver_with_ports(Mock())
        resolver.identities.lookup = Mock()
        resolver.identities.lookup.return_value = record
        self.assertEqual(
            resolver.dependencies.dependencies(settings, "separate"),
            {"mdx.model": record},
        )
        resolver.identities.lookup.assert_called_once_with(record.id)

    def test_job_assemble_honors_mdx_c_network_policy(self) -> None:
        from core.access_policy import current_access_policy
        from core.model_identity import ModelRecord
        from core.settings import Settings

        seen: list[tuple[bool, bool]] = []

        def fake_assemble(*_args: object, **_kwargs: object) -> list[object]:
            seen.append((current_access_policy().allow_network, current_access_policy().allow_metadata_writes))
            return []

        resolver = resolver_with_ports(Mock())
        record = ModelRecord(
            id='mdx:test',
            family='mdx',
            basename='test',
            display='Test',
            backend_name='test',
            artifacts=ModelArtifacts('test.ckpt'),
            installed=True,
        )
        with patch("core.job_materialization.assemble_model", side_effect=fake_assemble):
            resolver.materializer.assemble(Settings.defaults(), "separate", [record], allow_network=True, model_dependencies=None)
        self.assertEqual(seen, [(True, True)])

        seen.clear()
        with patch("core.job_materialization.assemble_model", side_effect=fake_assemble):
            resolver.materializer.assemble(Settings.defaults(), "separate", [record], allow_network=False, model_dependencies=None)
        self.assertEqual(seen, [(False, False)])

    def test_resolve_unavailable_model_status_is_configuration_diagnostic(self) -> None:
        from core.job_plan import ValidationLevel
        from core.model_identity import ModelRecord

        settings = Settings.defaults()
        settings.mdx.model = "mdx:broken"
        record = ModelRecord(
            id='mdx:broken',
            family='mdx',
            basename='broken',
            display='Broken',
            backend_name='broken',
            artifacts=ModelArtifacts('broken.ckpt'),
            installed=True,
        )
        unavailable = Mock(
            model_status=False,
            compensate=None,
            model_path="",
            model_hash_dir="",
            primary_stem="Vocals",
            secondary_stem="Instrumental",
        )
        resolver = resolver_with_ports(Mock(inventory_generation=0))
        resolver.identities.lookup = Mock(return_value=record)

        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            spec = JobSpec("separate", settings, (handle.name,), "/tmp/out")
            with patch.object(resolver.materializer, "assemble", return_value=[unavailable]):
                resolved = resolver.resolve(spec, ValidationLevel.MODEL)

        config_diags = [item for item in resolved.diagnostics if item.code == "model.configuration"]
        self.assertEqual(len(config_diags), 1)
        self.assertEqual(config_diags[0].severity, "error")
        self.assertFalse(resolved.ok)

    def test_positional_sentinel_plans_primary_stem(self) -> None:
        from core.stems import FOCUS_PRIMARY

        settings = Settings.defaults()
        settings.process.stem_focus = FOCUS_PRIMARY
        stems = planned_output_stems(
            settings, (_desc("Vocals", "Instrumental"),), command="separate"
        )
        self.assertEqual(stems, ((VOCAL_STEM, False),))

    def test_positional_sentinel_plans_dual_stem_ensemble_half(self) -> None:
        from core.stems import FOCUS_SECONDARY

        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        settings.process.stem_focus = FOCUS_SECONDARY
        stems = planned_output_stems(
            settings, (_four_desc("mdx:one"), _four_desc("mdx:two")), command="ensemble"
        )
        self.assertEqual(stems, (("Instrumental", False),))

    def test_four_stem_ensemble_ignores_positional_sentinel(self) -> None:
        from core.stems import FOCUS_PRIMARY

        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.four_stem"
        settings.process.stem_focus = FOCUS_PRIMARY
        stems = planned_output_stems(
            settings, (_four_desc("mdx:one"), _four_desc("mdx:two")), command="ensemble"
        )
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, (BASS_STEM, DRUM_STEM, "Residual", VOCAL_STEM))


class PlanningDiagnosticsTests(unittest.TestCase):
    def test_resolve_records_counts_without_input_paths(self) -> None:
        from core import debug_log
        from core.job_plan import ValidationLevel

        settings = Settings.defaults()
        resolver = resolver_with_ports(Mock(inventory_generation=3))
        with (
            tempfile.NamedTemporaryFile(suffix=".wav") as source,
            tempfile.TemporaryDirectory() as tmp,
        ):
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))
            self.addCleanup(debug_log.configure, level="errors", log_file="")
            resolver.resolve(
                JobSpec("separate", settings, (source.name,), tmp),
                ValidationLevel.CONFIG,
            )

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertIn("event=plan_resolved", diagnostic)
            self.assertIn("input_count=1", diagnostic)
            self.assertNotIn(source.name, diagnostic)


if __name__ == "__main__":
    unittest.main()
