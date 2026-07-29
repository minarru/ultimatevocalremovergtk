import json
import os
import pickle
import tempfile
import unittest
from unittest import mock

from bundled.constants import DEFAULT_DATA
from core.settings import Settings


class SettingsJsonTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            model = Settings.defaults()
            model.path = path
            model.set("export_path", "/tmp/out")
            model.save(path)
            loaded = Settings.load(path)
            self.assertEqual(loaded.get("export_path"), "/tmp/out")
            self.assertTrue(os.path.isfile(path))

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not-json{")
            loaded = Settings.load(path)
            self.assertEqual(loaded.get("save_format"), DEFAULT_DATA["save_format"])

    def test_unknown_keys_stripped_on_json_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            payload = Settings.defaults().to_json_dict()
            payload["evil_injected_key"] = "x"
            payload["process"]["evil_too"] = 1
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            loaded = Settings.load(path)
            self.assertNotIn("evil_injected_key", loaded.to_json_dict())
            self.assertNotIn("evil_too", loaded.to_json_dict()["process"])

    def test_atomic_save_uses_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            model = Settings.defaults()
            model.path = path
            model.set("user_code", "abc")
            model.save()
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(os.path.isfile(f"{path}.tmp"))

    def test_pickle_import_writes_json_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkl_path = os.path.join(tmp, "data.pkl")
            payload = dict(DEFAULT_DATA)
            payload["export_path"] = "/imported"
            payload["ensemble_main_stem"] = "Vocals/Instrumental"
            with open(pkl_path, "wb") as handle:
                pickle.dump(payload, handle)
            with mock.patch("core.settings.io.SETTINGS_PICKLE_FILE", pkl_path), mock.patch(
                "core.settings.io.SETTINGS_PICKLE_BAK", pkl_path + ".bak"
            ), mock.patch(
                "core.settings.io.SETTINGS_JSON_FILE", os.path.join(tmp, "settings.json")
            ):
                loaded = Settings.load()
            self.assertEqual(loaded.get("export_path"), "/imported")
            self.assertEqual(loaded.get("ensemble_main_stem"), "Vocals/Instrumental")
            self.assertTrue(os.path.isfile(os.path.join(tmp, "settings.json")))
            self.assertTrue(os.path.isfile(pkl_path + ".bak"))
            self.assertFalse(os.path.isfile(pkl_path))

    def test_is_autocast_first_load_applies_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.pkl")
            payload = {k: v for k, v in DEFAULT_DATA.items() if k != "is_autocast"}
            with open(path, "wb") as handle:
                pickle.dump(payload, handle)
            with mock.patch(
                "engines.amp_runtime.recommend_autocast", return_value=True
            ) as recommend:
                loaded = Settings.load(path)
            recommend.assert_called_once()
            self.assertTrue(loaded.get("is_autocast"))

    def test_is_autocast_keeps_stored_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.pkl")
            payload = dict(DEFAULT_DATA)
            payload["is_autocast"] = False
            with open(path, "wb") as handle:
                pickle.dump(payload, handle)
            with mock.patch(
                "engines.amp_runtime.recommend_autocast", return_value=True
            ) as recommend:
                loaded = Settings.load(path)
            recommend.assert_not_called()
            self.assertFalse(loaded.get("is_autocast"))

class TrySaveSettingsTests(unittest.TestCase):
    def test_returns_message_instead_of_raising(self):
        from ui.context import AppContext

        context = object.__new__(AppContext)
        context.settings = Settings.defaults()
        with mock.patch.object(
            context.settings, "save", side_effect=OSError("Read-only file system")
        ):
            message = AppContext.try_save_settings(context, trigger="test")
        self.assertIsInstance(message, str)
        assert message is not None
        self.assertIn("Couldn't save settings", message)


if __name__ == "__main__":
    unittest.main()
