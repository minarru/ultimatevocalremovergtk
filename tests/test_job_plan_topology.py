from __future__ import annotations

import tempfile
import unittest
from unittest.mock import Mock, patch

from bundled.constants import (
    BASS_STEM,
    DRUM_STEM,
    NO_BASS_STEM,
    NO_DRUM_STEM,
    NO_OTHER_STEM,
    OTHER_STEM,
    VOCAL_STEM,
)
from core.job_plan import JobResolver, JobSpec, ModelDescriptor, planned_output_stems
from core.model_identity import ModelArtifacts
from core.settings import Settings
from core.stems import EnsemblePair, FOCUS_SECONDARY
from core.types import ProcessMethod


def _desc(stem: str, secondary: str = "Instrumental") -> ModelDescriptor:
    return ModelDescriptor("mdx:a", "mdx", "a", "A", primary_stem=stem, secondary_stem=secondary)


class PlannedOutputStemTests(unittest.TestCase):
    def test_separate_uses_descriptor_stems(self) -> None:
        settings = Settings.defaults()
        stems = planned_output_stems(settings, (_desc("Vocals"),), command="separate")
        self.assertEqual(stems, (("Vocals", False), ("Instrumental", False)))

    def test_ensemble_pair_ignores_first_member_stems(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        stems = planned_output_stems(
            settings, (_desc("Drums", "Bass"), _desc("Vocals")), command="ensemble",
        )
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, (VOCAL_STEM, "Instrumental"))
        self.assertFalse(any(conditional for _stem, conditional in stems))

    def test_four_stem_ensemble_is_the_standard_four(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.FOUR_STEM
        stems = planned_output_stems(settings, (_desc("Vocals"),), command="ensemble")
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, (BASS_STEM, DRUM_STEM, OTHER_STEM, VOCAL_STEM))

    def test_four_stem_focus_filters_final_output(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.FOUR_STEM
        settings.process.stem_focus = BASS_STEM
        stems = planned_output_stems(
            settings, (_desc("Vocals"), _desc("Vocals")), command="ensemble"
        )
        self.assertEqual(stems, ((BASS_STEM, False),))

    def test_multi_stem_keeps_only_routes_with_two_contributors(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.MULTI_STEM
        stems = planned_output_stems(
            settings,
            (
                _desc("Vocals", "Bass"),
                _desc("Vocals", "Drums"),
                _desc("Bass", "Other"),
            ),
            command="ensemble",
        )
        labels = {stem for stem, _conditional in stems}
        self.assertEqual(labels, {"Vocals", "Bass"})
        self.assertFalse(any(conditional for _stem, conditional in stems))

    def test_multi_stem_explicit_single_contributor_is_an_error(self) -> None:
        from core.job_plan import _stem_focus_diagnostics

        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.MULTI_STEM
        settings.process.stem_focus = DRUM_STEM
        descriptors = (
            _desc("Vocals", "Drums"),
            _desc("Vocals", "Bass"),
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
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.VOCALS.value
        settings.ensemble.main_stem = EnsemblePair.KARAOKE
        stems = planned_output_stems(
            settings, (_desc("Vocals"), _desc("Vocals")), command="ensemble",
        )
        self.assertEqual(stems, ((LEAD_VOCAL_STEM_LABEL, False),))

    def test_ensemble_instrumental_focus_does_not_pick_other_pair(self) -> None:
        from bundled.constants import OTHER_STEM
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
        settings.ensemble.main_stem = EnsemblePair.OTHER
        stems = planned_output_stems(
            settings, (_desc("Other", "No Other"),), command="ensemble",
        )
        # Unmatched inherited focus falls back to the pair's complete inventory.
        self.assertEqual(stems, ((OTHER_STEM, False), (NO_OTHER_STEM, False)))

    def test_complement_pair_secondary_only_plans_the_derived_half(self) -> None:
        for pair, primary, complement in (
            (EnsemblePair.OTHER, OTHER_STEM, NO_OTHER_STEM),
            (EnsemblePair.DRUMS, DRUM_STEM, NO_DRUM_STEM),
            (EnsemblePair.BASS, BASS_STEM, NO_BASS_STEM),
        ):
            with self.subTest(pair=pair):
                settings = Settings.defaults()
                settings.ensemble.main_stem = pair
                settings.process.stem_focus = FOCUS_SECONDARY
                stems = planned_output_stems(
                    settings, (_desc(primary, complement),), command="ensemble"
                )
                self.assertEqual(stems, ((complement, False),))

    def test_separate_four_stem_other_is_not_instrumental_focus(self) -> None:
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
        desc = ModelDescriptor(
            "mdx:a", "mdx", "a", "A",
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
            "mdx:a", "mdx", "a", "A",
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
            derived_stem_route(
                "No bass", label="No bass", conditional=True
            ),
            derived_stem_route(StemBucket.INSTRUMENTAL),
        )
        desc = ModelDescriptor(
            "mdx:a", "mdx", "a", "A",
            primary_stem="bass", secondary_stem="No bass", stem_count=4,
            routes=routes,
        )
        planned = JobResolver(Mock())._plan_inputs(
            settings,
            JobSpec("separate", settings, ("/tmp/song.wav",), "/tmp/out"),
            (desc,),
        )
        self.assertEqual(
            [(output.stem, output.conditional) for output in planned[0].outputs],
            [("Bass", False), ("No bass", True)],
        )

    def test_resolver_plan_outputs_use_ensemble_pair(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        settings.ensemble.selected_models = ["mdx:a", "mdx:b"]
        resolver = JobResolver(Mock())
        spec = JobSpec("ensemble", settings, ("/tmp/song.wav",), "/tmp/out")
        # Bypass assemble: feed descriptors through _plan_inputs.
        planned = resolver._plan_inputs(
            settings, spec, (_desc("Drums", "Bass"), _desc("Vocals")),
        )
        self.assertEqual(
            [output.stem for output in planned[0].outputs],
            [VOCAL_STEM, "Instrumental"],
        )

    def test_karaoke_planned_filename_uses_runtime_tag(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = EnsemblePair.KARAOKE
        resolver = JobResolver(Mock())
        spec = JobSpec("ensemble", settings, ("/tmp/song.wav",), "/tmp/out")
        planned = resolver._plan_inputs(
            settings, spec, (_desc("Vocals"), _desc("Vocals")),
        )
        self.assertEqual(planned[0].outputs[0].stem, "Lead_Vocals")
        self.assertIn("(Lead_Vocals)", planned[0].outputs[0].path)

    def test_adhoc_ensemble_sentinel_label_is_ensembled(self) -> None:
        from bundled.constants import CHOOSE_ENSEMBLE_OPTION

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.chosen_ensemble = CHOOSE_ENSEMBLE_OPTION
        settings.ensemble.append_ensemble_name = True
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        resolver = JobResolver(Mock())
        spec = JobSpec("ensemble", settings, ("/tmp/song.wav",), "/tmp/out")
        planned = resolver._plan_inputs(
            settings, spec, (_desc("Vocals"), _desc("Vocals")),
        )
        self.assertEqual(planned[0].naming.ensemble_label, "Ensembled")
        self.assertNotIn("Choose Option", planned[0].naming.track_base)


class MdxCOfflinePlanningTests(unittest.TestCase):
    def test_ensure_mdx_c_config_offline_does_not_fetch(self) -> None:
        from core.mdx_config_fetch import ensure_mdx_c_config

        with patch("core.mdx_config_fetch._fetch_url_to_file") as fetch:
            ok = ensure_mdx_c_config(
                "definitely-missing-uvr-test.yaml", allow_network=False
            )
        self.assertFalse(ok)
        fetch.assert_not_called()

    def test_dependency_map_uses_exact_canonical_id(self) -> None:
        from core.job_plan import JobResolver
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
        resolver = JobResolver(Mock())
        resolver.identities = Mock()
        resolver.identities.lookup.return_value = record
        self.assertEqual(
            resolver._dependency_map(settings, "separate"),
            {"mdx.model": record},
        )
        resolver.identities.lookup.assert_called_once_with(record.id)

    def test_job_assemble_honors_mdx_c_network_policy(self) -> None:
        from core.access_policy import current_access_policy
        from core.job_plan import JobResolver
        from core.model_identity import ModelRecord
        from core.settings import Settings

        seen: list[bool] = []

        def fake_assemble(*_args: object, **_kwargs: object) -> list[object]:
            seen.append(current_access_policy().allow_network)
            return []

        resolver = JobResolver(Mock())
        record = ModelRecord(
            id='mdx:test',
            family='mdx',
            basename='test',
            display='Test',
            backend_name='test',
            artifacts=ModelArtifacts('test.ckpt'),
            installed=True,
        )
        with patch("core.job_plan.assemble_model", side_effect=fake_assemble):
            resolver._assemble(Settings.defaults(), "separate", [record], allow_network=True)
        self.assertEqual(seen, [True])

        seen.clear()
        with patch("core.job_plan.assemble_model", side_effect=fake_assemble):
            resolver._assemble(Settings.defaults(), "separate", [record], allow_network=False)
        self.assertEqual(seen, [False])

    def test_resolve_unavailable_model_status_is_configuration_diagnostic(self) -> None:
        from core.job_plan import JobResolver, ValidationLevel
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
        resolver = JobResolver(Mock(inventory_generation=0))
        resolver._dependency_map = Mock(  # type: ignore[method-assign]
            return_value={"mdx.model": record}
        )

        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            spec = JobSpec("separate", settings, (handle.name,), "/tmp/out")
            with patch.object(resolver, "_assemble", return_value=[unavailable]):
                resolved = resolver.resolve(spec, ValidationLevel.MODEL)

        config_diags = [
            item for item in resolved.diagnostics if item.code == "model.configuration"
        ]
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
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        settings.process.stem_focus = FOCUS_SECONDARY
        stems = planned_output_stems(
            settings, (_desc("Vocals"), _desc("Vocals")), command="ensemble"
        )
        self.assertEqual(stems, (("Instrumental", False),))

    def test_four_stem_ensemble_ignores_positional_sentinel(self) -> None:
        from core.stems import FOCUS_PRIMARY

        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.FOUR_STEM
        settings.process.stem_focus = FOCUS_PRIMARY
        stems = planned_output_stems(settings, (_desc("Vocals"),), command="ensemble")
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, (BASS_STEM, DRUM_STEM, OTHER_STEM, VOCAL_STEM))


if __name__ == "__main__":
    unittest.main()
