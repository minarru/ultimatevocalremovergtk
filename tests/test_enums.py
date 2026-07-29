import json
import unittest

from bundled.constants import (
    ALL_STEMS,
    APOLLO_ARCH_TYPE,
    AUDIO_AVERAGE,
    BASS_STEM,
    CHUNK_MIN,
    DEMUCS_ARCH_TYPE,
    DRUM_STEM,
    ENSEMBLE_MODE,
    FLAC,
    GUITAR_STEM,
    HYBRID_SPEC,
    INST_STEM,
    MAX_MAG_AVG_PHASE,
    MAX_SPEC,
    MDX_ARCH_TYPE,
    MEDIAN_SPEC,
    MIN_SPEC,
    MP3,
    OTHER_STEM,
    PIANO_STEM,
    SOFT_SPEC,
    VOCAL_STEM,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
    WAV,
)
from core.settings import Settings
from core.types import EnsembleAlgorithm, ProcessMethod, SaveFormat, Stem


class EnumParityTests(unittest.TestCase):
    def test_process_methods_match_bundled_labels(self):
        self.assertEqual(ProcessMethod.VR.value, VR_ARCH_PM)
        self.assertEqual(ProcessMethod.VR_ARCH.value, VR_ARCH_TYPE)
        self.assertEqual(ProcessMethod.MDX.value, MDX_ARCH_TYPE)
        self.assertEqual(ProcessMethod.DEMUCS.value, DEMUCS_ARCH_TYPE)
        self.assertEqual(ProcessMethod.ENSEMBLE.value, ENSEMBLE_MODE)
        self.assertEqual(ProcessMethod.APOLLO.value, APOLLO_ARCH_TYPE)

    def test_stems_match_bundled_labels(self):
        self.assertEqual(
            [item.value for item in Stem],
            [
                VOCAL_STEM,
                INST_STEM,
                OTHER_STEM,
                BASS_STEM,
                DRUM_STEM,
                GUITAR_STEM,
                PIANO_STEM,
                ALL_STEMS,
            ],
        )

    def test_save_formats_match_bundled_labels(self):
        self.assertEqual(
            [item.value for item in SaveFormat],
            [WAV, FLAC, MP3],
        )

    def test_ensemble_algorithms_match_bundled_labels(self):
        self.assertEqual(
            [item.value for item in EnsembleAlgorithm],
            [
                MAX_SPEC,
                MIN_SPEC,
                AUDIO_AVERAGE,
                MEDIAN_SPEC,
                SOFT_SPEC,
                MAX_MAG_AVG_PHASE,
                HYBRID_SPEC,
                CHUNK_MIN,
            ],
        )


class EnumSettingsRoundTripTests(unittest.TestCase):
    def test_strings_are_coerced_to_enums_and_json_stays_strings(self):
        settings = Settings.from_json_dict(
            {"process": {"method": MDX_ARCH_TYPE, "save_format": FLAC}}
        )

        self.assertIs(settings.process.method, ProcessMethod.MDX)
        self.assertIs(settings.process.save_format, SaveFormat.FLAC)

        payload = settings.to_json_dict()
        self.assertEqual(payload["process"]["method"], MDX_ARCH_TYPE)
        self.assertEqual(payload["process"]["save_format"], FLAC)
        self.assertIs(type(payload["process"]["method"]), str)
        self.assertIs(type(payload["process"]["save_format"]), str)
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_compound_ensemble_type_remains_a_string(self):
        settings = Settings.from_json_dict(
            {"ensemble": {"type": f"{MAX_SPEC}/{MIN_SPEC}"}}
        )
        self.assertIs(type(settings.ensemble.type), str)

    def test_flat_bridge_preserves_enum_field_types(self):
        settings = Settings.defaults()
        settings.set("chosen_process_method", VR_ARCH_PM)
        settings.set("save_format", MP3)
        self.assertIs(settings.process.method, ProcessMethod.VR)
        self.assertIs(settings.process.save_format, SaveFormat.MP3)


if __name__ == "__main__":
    unittest.main()
