"""Schema v3 settings coerce: sentinels, closed enums, ensemble.type."""

import unittest

from bundled.constants import AUTO_SELECT, DEF_OPT, MAX_MIN
from core.settings import SETTINGS_SCHEMA_VERSION, Settings
from core.settings.coerce import (
    as_chunks,
    coerce_ensemble_type,
    coerce_field,
    setting_for_combo,
)
from core.types import ProcessMethod, SaveFormat
from core.types.settings_enums import (
    ColorScheme,
    MdxDenoiseOption,
    WavType,
)


class SchemaVersionTests(unittest.TestCase):
    def test_defaults_are_v3(self) -> None:
        self.assertEqual(SETTINGS_SCHEMA_VERSION, 3)
        self.assertEqual(Settings.defaults().schema_version, 3)


class SentinelCoerceTests(unittest.TestCase):
    def test_default_auto_become_none(self) -> None:
        self.assertIsNone(coerce_field("vr", "batch_size", DEF_OPT))
        self.assertIsNone(coerce_field("vr", "batch_size", "Default"))
        self.assertIsNone(coerce_field("mdx", "compensate", AUTO_SELECT))
        self.assertIsNone(coerce_field("mdx", "overlap_mdx", DEF_OPT))
        self.assertIsNone(coerce_field("process", "device", "Default"))
        self.assertIsNone(coerce_field("demucs", "segment", None))

    def test_numeric_optional_values(self) -> None:
        self.assertEqual(coerce_field("vr", "batch_size", "4"), 4)
        self.assertEqual(coerce_field("mdx", "overlap_mdx", 0.75), 0.75)
        self.assertEqual(coerce_field("mdx", "compensate", "1.035"), 1.035)
        self.assertEqual(coerce_field("demucs", "segment", "50"), 50)

    def test_chunks(self) -> None:
        self.assertIsNone(as_chunks("Auto"))
        self.assertEqual(as_chunks("Full"), "full")
        self.assertEqual(as_chunks("20"), 20)
        self.assertEqual(coerce_field("mdx", "chunks", "Full"), "full")

    def test_combo_display_maps_none(self) -> None:
        self.assertEqual(setting_for_combo("batch_size", None), DEF_OPT)
        self.assertEqual(setting_for_combo("chunks", "full"), "Full")
        self.assertEqual(setting_for_combo("compensate", None), AUTO_SELECT)


class EnumCoerceTests(unittest.TestCase):
    def test_accepts_labels(self) -> None:
        self.assertEqual(coerce_field("process", "wav_type", "PCM_24"), WavType.PCM_24)
        self.assertEqual(
            coerce_field("mdx", "denoise_option", "Standard"),
            MdxDenoiseOption.STANDARD,
        )
        self.assertEqual(
            coerce_field("ui", "color_scheme", "dark"), ColorScheme.DARK
        )

    def test_unknown_fails_soft_to_default(self) -> None:
        self.assertEqual(
            coerce_field("process", "method", "not-a-method"), ProcessMethod.MDX
        )
        self.assertEqual(
            coerce_field("process", "save_format", "AIFF"), SaveFormat.WAV
        )
        self.assertEqual(
            coerce_field("process", "wav_type", "bogus"), WavType.PCM_16
        )


class EnsembleTypeCoerceTests(unittest.TestCase):
    def test_dual_stem_pair(self) -> None:
        self.assertEqual(
            coerce_ensemble_type("Average/Min Spec"), "Average/Min Spec"
        )
        self.assertEqual(coerce_field("ensemble", "type", "Max Spec/Min Spec"), MAX_MIN)

    def test_single_atom_preserved(self) -> None:
        self.assertEqual(coerce_ensemble_type("Max Spec"), "Max Spec")

    def test_unknown_atoms_fall_back(self) -> None:
        self.assertEqual(coerce_ensemble_type("Nope/Nope"), MAX_MIN)


class JsonRoundTripTests(unittest.TestCase):
    def test_null_sentinels_round_trip(self) -> None:
        settings = Settings.defaults()
        settings.vr.batch_size = None
        settings.mdx.chunks = "full"
        settings.process.semitone_shift = 1.5
        payload = settings.to_json_dict()
        self.assertIsNone(payload["vr"]["batch_size"])
        self.assertEqual(payload["mdx"]["chunks"], "full")
        self.assertEqual(payload["process"]["semitone_shift"], 1.5)
        restored = Settings.from_json_dict(payload)
        self.assertIsNone(restored.vr.batch_size)
        self.assertEqual(restored.mdx.chunks, "full")
        self.assertEqual(restored.process.semitone_shift, 1.5)

    def test_legacy_default_string_loads_as_none(self) -> None:
        settings = Settings.from_json_dict(
            {
                "vr": {"batch_size": "Default"},
                "mdx": {"overlap_mdx": "Default", "chunks": "Auto"},
                "process": {"device": "Default", "semitone_shift": "2"},
            }
        )
        self.assertIsNone(settings.vr.batch_size)
        self.assertIsNone(settings.mdx.overlap_mdx)
        self.assertIsNone(settings.mdx.chunks)
        self.assertIsNone(settings.process.device)
        self.assertEqual(settings.process.semitone_shift, 2.0)


if __name__ == "__main__":
    unittest.main()
