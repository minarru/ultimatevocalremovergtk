import json
import os
import tempfile
import unittest

from core.settings import SETTINGS_SCHEMA_VERSION, Settings
from core.settings.coerce import coerce_field
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
        settings.set("ensemble_main_stem", "pair.vocals_instrumental")
        self.assertEqual(settings.get("ensemble_main_stem"), "pair.vocals_instrumental")
        self.assertIsInstance(settings.ensemble.main_stem, str)
        self.assertEqual(settings.ensemble.main_stem, "pair.vocals_instrumental")
        flat = settings.to_dict()
        self.assertEqual(flat["ensemble_main_stem"], "pair.vocals_instrumental")
        payload = settings.to_json_dict()
        self.assertEqual(payload["ensemble"]["main_stem"], "pair.vocals_instrumental")

    def test_from_json_dict_backfills_missing_sections(self):
        partial = {"process": {"export_path": "/tmp/out"}}
        settings = Settings.from_json_dict(partial)
        self.assertEqual(settings.process.export_path, "/tmp/out")
        self.assertEqual(settings.ensemble.main_stem, "")
        self.assertFalse(settings.process.use_gpu)

    def test_legacy_vip_code_is_ignored_and_not_reserialized(self) -> None:
        payload = Settings.defaults().to_json_dict()
        payload["process"]["user_code"] = "old-secret"
        restored = Settings.from_json_dict(payload)
        self.assertFalse(hasattr(restored.process, "user_code"))
        self.assertNotIn("user_code", restored.to_json_dict()["process"])
        self.assertIsNone(restored.get("user_code"))

    def test_legacy_demucs_chunk_controls_are_ignored_and_not_reserialized(self) -> None:
        payload = Settings.defaults().to_json_dict()
        payload["demucs"].update(
            {
                "chunks_demucs": 7,
                "margin_demucs": 22050,
                "is_chunk_demucs": True,
            },
        )

        restored = Settings.from_json_dict(payload)

        serialized = restored.to_json_dict()["demucs"]
        self.assertNotIn("chunks_demucs", serialized)
        self.assertNotIn("margin_demucs", serialized)
        self.assertNotIn("is_chunk_demucs", serialized)

    def test_coerce_field_legacy_display_becomes_choose(self):
        self.assertEqual(
            coerce_field("ensemble", "main_stem", "Vocals/Instrumental"),
            "",
        )
        self.assertEqual(
            coerce_field("ensemble", "main_stem", "karaoke"),
            "",
        )

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
