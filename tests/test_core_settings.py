import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bundled.constants import DEFAULT_DATA
from core.settings import SETTINGS_SCHEMA_VERSION, Settings
from core.types.settings_enums import DiagnosticLevel


class SettingsJsonTests(unittest.TestCase):
    def test_schema_v5_defaults_include_diagnostic_policy(self):
        settings = Settings.defaults()

        self.assertEqual(SETTINGS_SCHEMA_VERSION, 5)
        self.assertEqual(settings.ensemble.main_stem, "")
        self.assertEqual(settings.diagnostics.level, DiagnosticLevel.ERRORS)
        self.assertFalse(settings.diagnostics.include_sensitive)
        self.assertEqual(
            settings.to_json_dict()["diagnostics"],
            {"level": "errors", "include_sensitive": False},
        )

    def test_pre_v5_payload_resets_ensemble_pair_once(self):
        payload = Settings.defaults().to_json_dict()
        payload["schema_version"] = 3
        payload.pop("diagnostics")

        loaded = Settings.from_json_dict(payload)

        self.assertEqual(loaded.schema_version, 5)
        self.assertEqual(loaded.ensemble.main_stem, "")
        self.assertEqual(len(loaded.validation_warnings), 1)
        self.assertIn("ensemble.main_stem", loaded.validation_warnings[0])
        loaded.validate_model_references()
        self.assertEqual(len(loaded.validation_warnings), 1)
        self.assertEqual(loaded.diagnostics.level, DiagnosticLevel.ERRORS)
        self.assertFalse(loaded.diagnostics.include_sensitive)

    def test_invalid_diagnostic_values_coerce_to_safe_defaults(self):
        loaded = Settings.from_json_dict(
            {
                "schema_version": 5,
                "diagnostics": {
                    "level": "everything",
                    "include_sensitive": "no",
                },
            }
        )

        self.assertEqual(loaded.diagnostics.level, DiagnosticLevel.ERRORS)
        self.assertFalse(loaded.diagnostics.include_sensitive)

    def test_diagnostic_settings_round_trip_but_stay_out_of_profiles(self):
        settings = Settings.defaults()
        settings.diagnostics.level = DiagnosticLevel.TRACE
        settings.diagnostics.include_sensitive = True

        restored = Settings.from_json_dict(settings.to_json_dict())

        self.assertEqual(restored.diagnostics.level, DiagnosticLevel.TRACE)
        self.assertTrue(restored.diagnostics.include_sensitive)
        self.assertNotIn("diagnostic_level", settings.to_dict())
        self.assertNotIn("include_sensitive", settings.to_dict())

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

    def test_corrupt_file_is_recorded_at_the_default_error_level(self):
        from core import debug_log

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            log_path = Path(tmp) / "uvr.log"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not-json{")
            debug_log.configure(level="errors", log_file=str(log_path))
            self.addCleanup(debug_log.configure, level="errors", log_file="")

            Settings.load(path)

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertIn("event=settings_load_failed", diagnostic)
            self.assertIn("level=ERROR", diagnostic)
            self.assertNotIn(path, diagnostic)

    def test_corrupt_file_is_preserved_not_overwritten(self):
        """A settings.json we cannot parse must survive as a .bad sidecar.

        Otherwise the fallback-to-defaults path lets the next save silently
        replace the user's entire configuration.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("not-json{")

            loaded = Settings.load(path)
            loaded.set("export_path", "/tmp/out")
            loaded.save(path)

            self.assertTrue(os.path.isfile(f"{path}.bad"))
            with open(f"{path}.bad", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "not-json{")

    def test_repeated_corruption_keeps_earlier_preserved_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            for marker in ("first{", "second{"):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(marker)
                Settings.load(path)

            with open(f"{path}.bad", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "first{")
            with open(f"{path}.bad.2", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "second{")

    def test_long_file_chunk_seconds_keeps_fractional_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            model = Settings.defaults()
            model.path = path
            model.process.long_file_chunk_seconds = 90.5
            model.save(path)
            self.assertEqual(Settings.load(path).process.long_file_chunk_seconds, 90.5)

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
            model.set("export_path", "/tmp/export")
            model.save()
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(os.path.isfile(f"{path}.tmp"))
            self.assertEqual(Settings.load(path).process.export_path, "/tmp/export")

    def test_pickle_import_writes_json_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkl_path = os.path.join(tmp, "data.pkl")
            payload = dict(DEFAULT_DATA)
            payload["export_path"] = "/imported"
            payload["ensemble_main_stem"] = "Vocals/Instrumental"
            with open(pkl_path, "wb") as handle:
                pickle.dump(payload, handle)
            with (
                mock.patch("core.settings.io.SETTINGS_PICKLE_FILE", pkl_path),
                mock.patch("core.settings.io.SETTINGS_PICKLE_BAK", pkl_path + ".bak"),
                mock.patch(
                    "core.settings.io.SETTINGS_JSON_FILE", os.path.join(tmp, "settings.json")
                ),
            ):
                loaded = Settings.load()
            self.assertEqual(loaded.get("export_path"), "/imported")
            # Hard cutover: legacy display strings are not migrated.
            self.assertEqual(loaded.get("ensemble_main_stem"), "")
            self.assertEqual(loaded.ensemble.main_stem, "")
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
