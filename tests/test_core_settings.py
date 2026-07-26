import os
import pickle
import tempfile
import unittest
from unittest import mock

from bundled.constants import DEFAULT_DATA
from core.settings import SettingsModel


class SettingsModelTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.pkl")
            model = SettingsModel()
            model.set("export_path", "/tmp/out")
            model.save(path)
            loaded = SettingsModel.load(path)
            self.assertEqual(loaded.get("export_path"), "/tmp/out")

    def test_corrupt_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.pkl")
            with open(path, "wb") as handle:
                handle.write(b"not-a-pickle")
            loaded = SettingsModel.load(path)
            self.assertEqual(loaded.get("save_format"), DEFAULT_DATA["save_format"])

    def test_unknown_keys_stripped_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.pkl")
            payload = dict(DEFAULT_DATA)
            payload["evil_injected_key"] = "x"
            with open(path, "wb") as handle:
                pickle.dump(payload, handle)
            loaded = SettingsModel.load(path)
            self.assertNotIn("evil_injected_key", loaded.to_dict())

    def test_atomic_save_uses_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.pkl")
            model = SettingsModel(path=path)
            model.set("user_code", "abc")
            model.save()
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(os.path.isfile(f"{path}.tmp"))

    def test_is_autocast_first_load_applies_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "data.pkl")
            payload = {k: v for k, v in DEFAULT_DATA.items() if k != "is_autocast"}
            with open(path, "wb") as handle:
                pickle.dump(payload, handle)
            with mock.patch(
                "engines.amp_runtime.recommend_autocast", return_value=True
            ) as recommend:
                loaded = SettingsModel.load(path)
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
                loaded = SettingsModel.load(path)
            recommend.assert_not_called()
            self.assertFalse(loaded.get("is_autocast"))


if __name__ == "__main__":
    unittest.main()
