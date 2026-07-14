import os
import tempfile
import time
import unittest

from core.paths import ENSEMBLE_TEMP_MAX_AGE_SECONDS, cleanup_stale_ensemble_temps


class EnsembleTempCleanupTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_path = None

    def tearDown(self):
        import core.paths as paths_module

        if self._old_path is not None:
            paths_module.ENSEMBLE_TEMP_PATH = self._old_path
        self._tmpdir.cleanup()

    def _use_temp_root(self):
        import core.paths as paths_module

        self._old_path = paths_module.ENSEMBLE_TEMP_PATH
        paths_module.ENSEMBLE_TEMP_PATH = self._tmpdir.name

    def _make_dir(self, name: str, age_seconds: int) -> str:
        path = os.path.join(self._tmpdir.name, name)
        os.makedirs(path)
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))
        return path

    def test_removes_folders_older_than_one_week(self):
        self._use_temp_root()
        stale = self._make_dir("OldEnsemble_Outputs_1", ENSEMBLE_TEMP_MAX_AGE_SECONDS + 60)
        recent = self._make_dir("NewEnsemble_Outputs_2", 60)

        removed = cleanup_stale_ensemble_temps(enabled=True)

        self.assertEqual(removed, 1)
        self.assertFalse(os.path.isdir(stale))
        self.assertTrue(os.path.isdir(recent))

    def test_skips_cleanup_when_disabled(self):
        self._use_temp_root()
        stale = self._make_dir("OldEnsemble_Outputs_3", ENSEMBLE_TEMP_MAX_AGE_SECONDS + 60)

        removed = cleanup_stale_ensemble_temps(enabled=False)

        self.assertEqual(removed, 0)
        self.assertTrue(os.path.isdir(stale))

    def test_ignores_files_and_missing_root(self):
        self._use_temp_root()
        file_path = os.path.join(self._tmpdir.name, "leftover.wav")
        with open(file_path, "w", encoding="utf-8") as handle:
            handle.write("x")
        old_mtime = time.time() - ENSEMBLE_TEMP_MAX_AGE_SECONDS - 60
        os.utime(file_path, (old_mtime, old_mtime))

        removed = cleanup_stale_ensemble_temps(enabled=True)

        self.assertEqual(removed, 0)
        self.assertTrue(os.path.isfile(file_path))

        import core.paths as paths_module

        paths_module.ENSEMBLE_TEMP_PATH = os.path.join(self._tmpdir.name, "missing")
        self.assertEqual(cleanup_stale_ensemble_temps(enabled=True), 0)


if __name__ == "__main__":
    unittest.main()
