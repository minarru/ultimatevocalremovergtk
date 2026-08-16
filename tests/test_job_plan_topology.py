from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from bundled.constants import BASS_STEM, DRUM_STEM, OTHER_STEM, VOCAL_STEM
from core.job_plan import JobResolver, JobSpec, ModelDescriptor, planned_output_stems
from core.settings import Settings
from core.stems import EnsemblePair
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

    def test_multi_stem_marks_union_conditional_when_members_differ(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.MULTI_STEM
        stems = planned_output_stems(
            settings,
            (_desc("Vocals", "Instrumental"), _desc("Drums", "Bass")),
            command="ensemble",
        )
        self.assertTrue(any(conditional for _stem, conditional in stems))
        labels = {stem for stem, _conditional in stems}
        self.assertTrue({"Vocals", "Instrumental", "Drums", "Bass"} <= labels)

    def test_resolver_plan_outputs_use_ensemble_pair(self) -> None:
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        settings.ensemble.selected_models = ["mdx:a", "mdx:b"]
        resolver = JobResolver(Mock())
        resolver._identity_records = Mock(return_value=[])  # type: ignore[method-assign]
        spec = JobSpec("ensemble", settings, ("/tmp/song.wav",), "/tmp/out")
        # Bypass assemble: feed descriptors through _plan_inputs.
        planned = resolver._plan_inputs(
            settings, spec, (_desc("Drums", "Bass"), _desc("Vocals")),
        )
        self.assertEqual(
            [output.stem for output in planned[0].outputs],
            [VOCAL_STEM, "Instrumental"],
        )


class MdxCOfflinePlanningTests(unittest.TestCase):
    def test_ensure_mdx_c_config_offline_does_not_fetch(self) -> None:
        from core.mdx_config_fetch import ensure_mdx_c_config

        with patch("core.mdx_config_fetch._fetch_url_to_file") as fetch:
            ok = ensure_mdx_c_config(
                "definitely-missing-uvr-test.yaml", allow_network=False
            )
        self.assertFalse(ok)
        fetch.assert_not_called()

    def test_job_assemble_disables_mdx_c_network(self) -> None:
        from core.job_plan import JobResolver
        from core.mdx_config_fetch import _ALLOW_NETWORK
        from core.model_identity import ModelRecord
        from core.settings import Settings

        seen: list[bool] = []

        def fake_assemble(*_args: object, **_kwargs: object) -> list[object]:
            seen.append(_ALLOW_NETWORK.get())
            return []

        resolver = JobResolver(Mock())
        record = ModelRecord(
            id="mdx:test", family="mdx", basename="test", display="Test"
        )
        with patch("core.job_plan.assemble_model", side_effect=fake_assemble):
            resolver._assemble(Settings.defaults(), "separate", [record])
        self.assertEqual(seen, [False])


if __name__ == "__main__":
    unittest.main()
