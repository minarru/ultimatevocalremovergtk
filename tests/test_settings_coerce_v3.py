"""Schema v3 settings coerce: sentinels, closed enums, ensemble.type."""

import unittest

from bundled.constants import AUTO_SELECT, DEF_OPT, MAX_MIN
from core.settings import SETTINGS_SCHEMA_VERSION, Settings
from core.settings.coerce import (
    as_chunks,
    coerce_ensemble_type,
    coerce_field,
    enum_value,
    setting_for_combo,
)
from core.types import ProcessMethod, SaveFormat
from core.types.settings_enums import (
    ColorScheme,
    MdxDenoiseOption,
    OpusBitrate,
    WavType,
)


class SchemaVersionTests(unittest.TestCase):
    def test_defaults_use_current_schema(self) -> None:
        self.assertEqual(SETTINGS_SCHEMA_VERSION, 5)
        self.assertEqual(Settings.defaults().schema_version, 5)

    def test_older_payload_is_stamped_current(self) -> None:
        """Loading coerces to v3, so the stamp must say v3 — not the file's."""
        settings = Settings.from_json_dict({"schema_version": 1, "vr": {}})
        self.assertEqual(settings.schema_version, SETTINGS_SCHEMA_VERSION)
        self.assertEqual(settings.to_json_dict()["schema_version"], SETTINGS_SCHEMA_VERSION)

    def test_missing_version_is_stamped_current(self) -> None:
        self.assertEqual(Settings.from_json_dict({}).schema_version, SETTINGS_SCHEMA_VERSION)


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
        self.assertEqual(coerce_field("ui", "color_scheme", "dark"), ColorScheme.DARK)
        self.assertEqual(coerce_field("process", "save_format", "OPUS"), SaveFormat.OPUS)
        self.assertEqual(coerce_field("process", "opus_bitrate", "128k"), OpusBitrate.K128)

    def test_unknown_fails_soft_to_default(self) -> None:
        self.assertEqual(coerce_field("process", "method", "not-a-method"), ProcessMethod.MDX)
        self.assertEqual(coerce_field("process", "save_format", "AIFF"), SaveFormat.FLAC)
        self.assertEqual(coerce_field("process", "wav_type", "bogus"), WavType.PCM_16)
        self.assertEqual(coerce_field("process", "opus_bitrate", "bogus"), OpusBitrate.K192)


class EnumValueTests(unittest.TestCase):
    """``str(member)`` yields ``ClassName.MEMBER``; ``enum_value`` must not."""

    def test_unwraps_settings_enums(self) -> None:
        self.assertEqual(enum_value(WavType.PCM_24), "PCM_24")
        self.assertEqual(enum_value(ColorScheme.DARK), "dark")
        self.assertEqual(enum_value(OpusBitrate.K192), "192k")
        self.assertEqual(enum_value("pair.karaoke"), "pair.karaoke")

    def test_passes_through_non_enums(self) -> None:
        self.assertEqual(enum_value("Median Spec"), "Median Spec")
        self.assertEqual(enum_value(8), 8)
        self.assertIsNone(enum_value(None))


class EnsemblePairCoerceTests(unittest.TestCase):
    def test_current_namespaced_pair_round_trips(self) -> None:
        settings = Settings.from_json_dict(
            {"schema_version": 5, "ensemble": {"main_stem": "pair.karaoke"}}
        )
        self.assertEqual(settings.ensemble.main_stem, "pair.karaoke")
        self.assertEqual(settings.to_json_dict()["ensemble"]["main_stem"], "pair.karaoke")

    def test_unknown_current_pair_is_cleared_with_warning(self) -> None:
        settings = Settings.from_json_dict(
            {"schema_version": 5, "ensemble": {"main_stem": "pair.not_real"}}
        )
        self.assertEqual(settings.ensemble.main_stem, "")
        self.assertEqual(len(settings.validation_warnings), 1)
        self.assertIn("ensemble.main_stem", settings.validation_warnings[0])

    def test_padded_current_pair_is_rejected_without_normalization(self) -> None:
        settings = Settings.from_json_dict(
            {"schema_version": 5, "ensemble": {"main_stem": " pair.karaoke "}}
        )
        self.assertEqual(settings.ensemble.main_stem, "")
        self.assertEqual(len(settings.validation_warnings), 1)
        self.assertIn("ensemble.main_stem", settings.validation_warnings[0])


class EnsembleTypeCoerceTests(unittest.TestCase):
    def test_dual_stem_pair(self) -> None:
        self.assertEqual(coerce_ensemble_type("Average/Min Spec"), "Average/Min Spec")
        self.assertEqual(coerce_field("ensemble", "type", "Max Spec/Min Spec"), MAX_MIN)

    def test_single_atom_preserved(self) -> None:
        self.assertEqual(coerce_ensemble_type("Max Spec"), "Max Spec")

    def test_unknown_atoms_fall_back(self) -> None:
        self.assertEqual(coerce_ensemble_type("Nope/Nope"), MAX_MIN)

    def test_stem_focus_aliases_vocals(self) -> None:
        from core.stems import StemBucket

        self.assertEqual(coerce_field("process", "stem_focus", "vocals"), StemBucket.VOCALS.value)
        self.assertEqual(coerce_field("process", "stem_focus", "Vocals"), StemBucket.VOCALS.value)
        self.assertEqual(coerce_field("process", "stem_focus", ""), "")

    def test_stem_focus_keeps_positional_sentinels(self) -> None:
        from core.stems import FOCUS_PRIMARY, FOCUS_SECONDARY

        self.assertEqual(coerce_field("process", "stem_focus", "primary"), FOCUS_PRIMARY)
        self.assertEqual(coerce_field("process", "stem_focus", "Secondary"), FOCUS_SECONDARY)


class ExclusiveFlagMigrationTests(unittest.TestCase):
    def test_process_primary_flag_becomes_sentinel(self) -> None:
        from core.stems import FOCUS_PRIMARY

        settings = Settings.from_json_dict(
            {
                "process": {
                    "stem_focus": "",
                    "primary_stem_only": True,
                    "secondary_stem_only": False,
                }
            }
        )
        self.assertEqual(settings.process.stem_focus, FOCUS_PRIMARY)
        self.assertNotIn("primary_stem_only", settings.to_json_dict()["process"])

    def test_demucs_flags_migrate_when_process_flags_are_off(self) -> None:
        from core.stems import FOCUS_SECONDARY

        settings = Settings.from_json_dict(
            {
                "process": {"stem_focus": ""},
                "demucs": {
                    "is_primary_stem_only": False,
                    "is_secondary_stem_only": True,
                },
            }
        )
        self.assertEqual(settings.process.stem_focus, FOCUS_SECONDARY)
        self.assertNotIn("is_secondary_stem_only", settings.to_json_dict()["demucs"])

    def test_existing_focus_is_kept(self) -> None:
        from core.stems import StemBucket

        settings = Settings.from_json_dict(
            {
                "process": {
                    "stem_focus": "vocals",
                    "primary_stem_only": True,
                }
            }
        )
        self.assertEqual(settings.process.stem_focus, StemBucket.VOCALS.value)

    def test_xor_only_both_flags_do_not_invent_a_sentinel(self) -> None:
        settings = Settings.from_json_dict(
            {
                "process": {
                    "stem_focus": "",
                    "primary_stem_only": True,
                    "secondary_stem_only": True,
                }
            }
        )
        self.assertEqual(settings.process.stem_focus, "")


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
