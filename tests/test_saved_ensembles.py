import json
import os
import tempfile
import unittest
from unittest.mock import patch

from core import ensemble_service, paths


class SavedEnsemblePersistenceTests(unittest.TestCase):
    def test_names_are_canonicalized_and_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            paths, "ENSEMBLE_CACHE_DIR", tmp
        ):
            path = ensemble_service.save_ensemble(" My Mix ", "Vocals", "max", ["a", "b"])
            self.assertEqual(os.path.basename(path), "My_Mix.json")
            self.assertEqual(ensemble_service.list_saved_ensembles(), ["My_Mix"])
            loaded = ensemble_service.load_ensemble("My Mix")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["selected_models"], ["a", "b"])
            self.assertTrue(ensemble_service.delete_ensemble("My Mix"))
            self.assertEqual(ensemble_service.list_saved_ensembles(), [])

    def test_invalid_names_cannot_escape_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            paths, "ENSEMBLE_CACHE_DIR", os.path.join(tmp, "ensembles")
        ):
            for name in ("../outside", os.path.join(tmp, "outside"), "bad.json", ""):
                with self.assertRaises(ValueError):
                    ensemble_service.save_ensemble(name, "Vocals", "max", [])
            self.assertFalse(os.path.exists(os.path.join(tmp, "outside.json")))

    def test_listing_ignores_unsafe_legacy_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            paths, "ENSEMBLE_CACHE_DIR", tmp
        ):
            with open(os.path.join(tmp, "Good_Name.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            with open(os.path.join(tmp, "bad.name.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            self.assertEqual(ensemble_service.list_saved_ensembles(), ["Good_Name"])


if __name__ == "__main__":
    unittest.main()
