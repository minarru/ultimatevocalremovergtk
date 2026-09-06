"""Plan-time enrichment must not crash on a Demucs model."""

import unittest
from unittest.mock import Mock

from bundled.constants import DEF_OPT
from core.job_projection import project_native_settings
from core.model_identity import ModelArtifacts, ModelRecord
from core.settings import Settings


def _record(family: str) -> ModelRecord:
    return ModelRecord(
        id=f"{family}:m",
        family=family,
        basename="m",
        display="M",
        backend_name="m",
        artifacts=ModelArtifacts("m.ckpt" if family == "mdx" else "m.pth"),
        installed=True,
    )


class DemucsSegmentEnrichmentTests(unittest.TestCase):
    """ModelConfig.segment renders the *setting* into the legacy engine label.

    It is not model-native metadata, so plan-time enrichment must not read it
    back and coerce it. When the setting is unset it is always ``'Default'``,
    which int() cannot parse -- every Demucs run died at plan time.
    """

    def _model(self, segment: object) -> Mock:
        return Mock(segment=segment, compensate=None, model_hash_dir="")

    def test_a_demucs_model_does_not_crash_plan_time(self) -> None:
        settings = Settings.defaults()
        settings.demucs.segment = None
        result = project_native_settings(
            settings, {}, [_record('demucs')], [self._model(DEF_OPT)], ["model-catalog"]
        )
        settings = result.settings

    def test_the_segment_setting_is_left_unset(self) -> None:
        settings = Settings.defaults()
        settings.demucs.segment = None
        result = project_native_settings(
            settings, {}, [_record('demucs')], [self._model(DEF_OPT)], ["model-catalog"]
        )
        settings = result.settings

        self.assertIsNone(settings.demucs.segment)

    def test_no_segment_provenance_is_claimed(self) -> None:
        provenance: dict = {}
        settings = Settings.defaults()
        settings.demucs.segment = None
        result = project_native_settings(
            settings, provenance, [_record('demucs')], [self._model(DEF_OPT)], ["model-catalog"]
        )
        settings = result.settings
        provenance = dict(result.provenance)
        self.assertNotIn("demucs.segment", provenance)

    def test_an_explicit_segment_survives(self) -> None:
        settings = Settings.defaults()
        settings.demucs.segment = 10
        result = project_native_settings(
            settings, {}, [_record('demucs')], [self._model('10')], ["model-catalog"]
        )
        settings = result.settings

        self.assertEqual(settings.demucs.segment, 10)

    def test_a_numeric_model_segment_is_still_not_read_back(self) -> None:
        """Even parseable, it is the setting echoed back, not metadata."""
        settings = Settings.defaults()
        settings.demucs.segment = None
        result = project_native_settings(
            settings, {}, [_record('demucs')], [self._model('15')], ["model-catalog"]
        )
        settings = result.settings

        self.assertIsNone(settings.demucs.segment)


class MdxCompensateEnrichmentTests(unittest.TestCase):
    """The neighbouring branch reads real metadata and must keep working."""

    def test_compensate_is_materialized_from_the_model(self) -> None:
        settings = Settings.defaults()
        settings.mdx.compensate = None
        provenance: dict = {}
        result = project_native_settings(
            settings,
            provenance,
            [_record('mdx')],
            [Mock(compensate=1.035, model_hash_dir='')],
            ["model-catalog"],
        )
        settings = result.settings
        provenance = dict(result.provenance)
        self.assertEqual(settings.mdx.compensate, 1.035)
        self.assertIn("mdx.compensate", provenance)

    def test_an_explicit_compensate_is_not_overwritten(self) -> None:
        settings = Settings.defaults()
        settings.mdx.compensate = 1.0
        result = project_native_settings(
            settings,
            {},
            [_record('mdx')],
            [Mock(compensate=1.035, model_hash_dir='')],
            ["model-catalog"],
        )
        settings = result.settings

        self.assertEqual(settings.mdx.compensate, 1.0)


if __name__ == "__main__":
    unittest.main()
