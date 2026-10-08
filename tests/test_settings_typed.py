import json
import os
import tempfile
import unittest

from core.settings import SETTINGS_SCHEMA_VERSION, Settings
from core.settings.coerce import coerce_field, coerce_json_dict
from core.types import SaveFormat, Stem
from core.types.settings_enums import FlacBitDepth, OpusBitrate


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

    def test_log_auto_open_defaults_off_and_round_trips(self):
        settings = Settings.from_json_dict({"ui": {}})
        self.assertFalse(settings.ui.auto_expand_log)
        settings.ui.auto_expand_log = True
        restored = Settings.from_json_dict(json.loads(json.dumps(settings.to_json_dict())))
        self.assertTrue(restored.ui.auto_expand_log)
        self.assertFalse(coerce_field("ui", "auto_expand_log", "false"))

    def test_listening_window_defaults_off_and_round_trips(self):
        settings = Settings.from_json_dict({"ui": {}})
        self.assertFalse(settings.ui.listening_in_window)
        settings.ui.listening_in_window = True
        restored = Settings.from_json_dict(json.loads(json.dumps(settings.to_json_dict())))
        self.assertTrue(restored.ui.listening_in_window)
        self.assertFalse(coerce_field("ui", "listening_in_window", "false"))

    def test_stale_compare_window_key_is_dropped(self):
        settings = Settings.from_json_dict(coerce_json_dict({"ui": {"compare_in_window": True}}))
        self.assertFalse(settings.ui.listening_in_window)
        self.assertNotIn("compare_in_window", settings.to_json_dict()["ui"])

    def test_sample_starts_default_empty_and_round_trip(self):
        settings = Settings.from_json_dict({"process": {}})
        self.assertEqual(settings.process.sample_starts, {})
        settings.process.sample_starts = {"/in/a.wav": 75.0}
        restored = Settings.from_json_dict(json.loads(json.dumps(settings.to_json_dict())))
        self.assertEqual(restored.process.sample_starts, {"/in/a.wav": 75.0})

    def test_sample_starts_coercion_drops_invalid_entries(self):
        raw = {
            "/a.wav": 75,
            "/b.wav": -1,
            "/c.wav": "x",
            "/d.wav": float("nan"),
            3: 1.0,
            "/e.wav": 0,
        }
        self.assertEqual(coerce_field("process", "sample_starts", raw), {"/a.wav": 75.0})
        self.assertEqual(coerce_field("process", "sample_starts", "oops"), {})

    def test_sample_lengths_round_trip_and_coerce_like_starts(self):
        settings = Settings.from_json_dict({"process": {}})
        self.assertEqual(settings.process.sample_lengths, {})
        settings.process.sample_lengths = {"/in/a.wav": 45.0}
        restored = Settings.from_json_dict(json.loads(json.dumps(settings.to_json_dict())))
        self.assertEqual(restored.process.sample_lengths, {"/in/a.wav": 45.0})
        raw = {"/a.wav": 45, "/b.wav": 0, "/c.wav": "x"}
        self.assertEqual(coerce_field("process", "sample_lengths", raw), {"/a.wav": 45.0})
        flat = Settings.from_flat({"model_sample_lengths": {"/a.wav": 12}})
        self.assertEqual(flat.process.sample_lengths, {"/a.wav": 12.0})

    def test_export_defaults_to_flac_16bit(self):
        settings = Settings.defaults()
        self.assertIs(settings.process.save_format, SaveFormat.FLAC)
        self.assertIs(settings.process.flac_bit_depth, FlacBitDepth.BIT_16)
        payload = settings.to_json_dict()["process"]
        self.assertEqual(payload["save_format"], "FLAC")
        self.assertEqual(payload["flac_bit_depth"], "16-bit")
        restored = Settings.from_json_dict({"process": {}})
        self.assertIs(restored.process.save_format, SaveFormat.FLAC)
        self.assertIs(restored.process.flac_bit_depth, FlacBitDepth.BIT_16)

    def test_opus_bitrate_defaults_to_192k(self):
        settings = Settings.defaults()
        self.assertIs(settings.process.opus_bitrate, OpusBitrate.K192)
        self.assertEqual(settings.to_json_dict()["process"]["opus_bitrate"], "192k")
        restored = Settings.from_json_dict({"process": {}})
        self.assertIs(restored.process.opus_bitrate, OpusBitrate.K192)

    def test_flat_opus_bit_set_round_trips(self):
        settings = Settings.from_flat({"opus_bit_set": "128k"})
        self.assertIs(settings.process.opus_bitrate, OpusBitrate.K128)
        self.assertEqual(settings.get("opus_bit_set"), "128k")

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
