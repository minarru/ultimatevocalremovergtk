import json
import os
import tempfile
import unittest
from unittest import mock

from core import download_sizes, paths


class CachePathMigrationTests(unittest.TestCase):
    def test_migrate_moves_legacy_data_dir_file(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with tempfile.TemporaryDirectory() as cache_dir:
                legacy = os.path.join(data_dir, "download_size_cache.json")
                with open(legacy, "w", encoding="utf-8") as handle:
                    json.dump({"ok": 1}, handle)
                dest = os.path.join(cache_dir, "download_size_cache.json")

                with mock.patch.object(paths, "DATA_DIR", data_dir), mock.patch.object(
                    paths, "BASE_PATH", data_dir
                ), mock.patch.object(paths, "CACHE_DIR", cache_dir):
                    result = paths.migrate_cache_file("download_size_cache.json", dest)

                self.assertEqual(result, dest)
                self.assertTrue(os.path.isfile(dest))
                self.assertFalse(os.path.isfile(legacy))
                with open(dest, encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle), {"ok": 1})

    def test_download_sizes_writes_under_cache_path(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            cache_file = os.path.join(cache_dir, "download_size_cache.json")
            with mock.patch.object(download_sizes, "_cache_path", return_value=cache_file):
                download_sizes._cache_put("https://example.test/a.bin", 123)
            self.assertTrue(os.path.isfile(cache_file))
            with open(cache_file, encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["https://example.test/a.bin"]["size"], 123)


if __name__ == "__main__":
    unittest.main()
