"""Unit tests for the catalogue YAML stem cache (Task 2: disk + lookup)."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock

import core.catalogue_stem_cache as csc


class CatalogueStemCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self._tmp.name, "catalogue_stem_cache.json")
        self._path_patch = mock.patch.object(csc, "_cache_path", return_value=self.cache_path)
        self._path_patch.start()
        csc.clear_catalogue_stem_cache()

    def tearDown(self) -> None:
        csc.clear_catalogue_stem_cache()
        self._path_patch.stop()
        self._tmp.cleanup()

    def test_parse_stems_from_yaml_bytes(self) -> None:
        yaml_bytes = b"""
training:
  instruments:
    - Vocals
    - other
  target_instrument: Vocals
"""
        stems, target = csc.parse_stems_from_yaml_bytes(yaml_bytes)
        self.assertEqual(stems, ["Vocals", "other"])
        self.assertEqual(target, "Vocals")

    def test_remember_and_lookup_round_trip(self) -> None:
        url = "https://example.test/config.yaml?v=1"
        csc.remember_stems(url, ["Vocals", "other"], "Vocals", ok=True)
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.stems, ("Vocals", "other"))
        self.assertEqual(hit.target_instrument, "Vocals")
        self.assertTrue(hit.ok)
        # Query string stripped for cache key.
        hit2 = csc.lookup_stems("https://example.test/config.yaml")
        self.assertIsNotNone(hit2)
        assert hit2 is not None
        self.assertEqual(hit2.stems, ("Vocals", "other"))
        self.assertTrue(os.path.isfile(self.cache_path))
        with open(self.cache_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        key = csc.normalize_config_url(url)
        self.assertIn(key, payload["entries"])

    def test_failed_entry_returned_within_failure_ttl(self) -> None:
        url = "https://example.test/missing.yaml"
        csc.remember_stems(url, [], None, ok=False)
        hit = csc.lookup_stems(url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertFalse(hit.ok)
        self.assertEqual(hit.stems, ())
        self.assertIsNone(hit.target_instrument)

    def test_catalogue_stems_disabled_by_env(self) -> None:
        url = "https://example.test/config.yaml"
        csc.remember_stems(url, ["Vocals"], None, ok=True)
        with mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}):
            self.assertFalse(csc.catalogue_stems_enabled())
            self.assertIsNone(csc.lookup_stems(url))

    def test_expired_success_entry_returns_none(self) -> None:
        stale_url = "https://example.test/old.yaml"
        fresh_url = "https://example.test/fresh.yaml"
        stale_key = csc.normalize_config_url(stale_url)
        fresh_key = csc.normalize_config_url(fresh_url)
        stale_at = 1_000_000.0
        now = stale_at + csc._SUCCESS_TTL_SECONDS + 1
        payload = {
            "fetched_at": now,
            "entries": {
                stale_key: {
                    "stems": ["Vocals"],
                    "target_instrument": None,
                    "fetched_at": stale_at,
                    "ok": True,
                },
                fresh_key: {
                    "stems": ["other"],
                    "target_instrument": None,
                    "fetched_at": now - 3600,
                    "ok": True,
                },
            },
        }
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        csc._memory_entries = None
        with mock.patch.object(csc.time, "time", return_value=now):
            self.assertIsNone(csc.lookup_stems(stale_url))
            hit = csc.lookup_stems(fresh_url)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.stems, ("other",))
        self.assertTrue(hit.ok)


if __name__ == "__main__":
    unittest.main()
