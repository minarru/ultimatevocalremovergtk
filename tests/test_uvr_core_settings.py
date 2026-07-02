import os
import pickle
import tempfile
import unittest

from data.constants import DEFAULT_DATA
from uvr_core.settings import SettingsModel


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


if __name__ == "__main__":
    unittest.main()
