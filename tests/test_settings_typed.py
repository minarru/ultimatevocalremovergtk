import json
import os
import tempfile
import unittest

from bundled.constants import CHOOSE_STEM_PAIR, VOCAL_PAIR
from core.settings import SETTINGS_SCHEMA_VERSION, Settings
from core.types import Stem


class TypedSettingsTests(unittest.TestCase):
    def test_defaults_round_trip_json(self):
        settings = Settings.defaults()
        payload = settings.to_json_dict()
        restored = Settings.from_json_dict(payload)
        self.assertEqual(restored.schema_version, SETTINGS_SCHEMA_VERSION)
        self.assertEqual(restored.process.method, settings.process.method)
        self.assertEqual(restored.process.save_format, settings.process.save_format)
        self.assertEqual(restored.ensemble.type, settings.ensemble.type)
        self.assertEqual(json.loads(json.dumps(payload)), payload)

    def test_flat_get_set_gpu_conversion(self):
        settings = Settings.defaults()
        self.assertFalse(settings.get("is_gpu_conversion"))
        settings.set("is_gpu_conversion", True)
        self.assertTrue(settings.process.use_gpu)
        self.assertTrue(settings.get("is_gpu_conversion"))

    def test_ensemble_main_stem_persists_via_set_get(self):
        settings = Settings.defaults()
        settings.set("ensemble_main_stem", VOCAL_PAIR)
        self.assertEqual(settings.get("ensemble_main_stem"), VOCAL_PAIR)
        self.assertEqual(settings.ensemble.main_stem, VOCAL_PAIR)
        flat = settings.to_dict()
        self.assertEqual(flat["ensemble_main_stem"], VOCAL_PAIR)

    def test_from_json_dict_backfills_missing_sections(self):
        partial = {"process": {"export_path": "/tmp/out"}}
        settings = Settings.from_json_dict(partial)
        self.assertEqual(settings.process.export_path, "/tmp/out")
        self.assertEqual(settings.ensemble.main_stem, CHOOSE_STEM_PAIR)
        self.assertFalse(settings.process.use_gpu)

    def test_stem_enum_matches_label(self):
        self.assertEqual(Stem.VOCALS, "Vocals")
        self.assertEqual(Stem.VOCALS.value, "Vocals")

    def test_save_and_load_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            settings = Settings.defaults()
            settings.set("export_path", "/tmp/export")
            settings.save(path)
            loaded = Settings.load(path)
            self.assertEqual(loaded.get("export_path"), "/tmp/export")


if __name__ == "__main__":
    unittest.main()
