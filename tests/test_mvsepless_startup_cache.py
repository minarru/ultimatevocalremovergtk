"""A fresh on-disk mvsepless cache must not cost a startup network round trip.

load_mvsepless_models used to fetch first and only fall back to disk on failure,
so window construction blocked on HTTP even with a valid cache on disk -- the
identical pre-Task-3 shape core.politrees_catalog.load_politrees_links had before
its own disk-TTL fast path was added.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from unittest import mock

import core.mvsepless_catalog as mc


class MvseplessStartupCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self._tmp.name, "mvsepless_models.json")
        self._patch = mock.patch.object(mc, "_cache_path", return_value=self.cache_path)
        self._patch.start()
        # The suite may be run with UVR_DISABLE_MVSEPLESS=1 ambient; these
        # tests exercise load_mvsepless_models's disk-cache path specifically
        # and need mvsepless_enabled() to read True regardless of that.
        # Politrees is unrelated to what this class tests, so it stays
        # disabled here -- otherwise _merged_for_display() (exercised below)
        # fetches it live.
        self._env_patch = mock.patch.dict(
            os.environ,
            {"UVR_DISABLE_MVSEPLESS": "0", "UVR_DISABLE_POLITREES": "1"},
        )
        self._env_patch.start()
        mc.clear_mvsepless_cache()

    def tearDown(self) -> None:
        self._env_patch.stop()
        self._patch.stop()
        mc.clear_mvsepless_cache()
        self._tmp.cleanup()

    def _write_cache(self, fetched_at: float) -> None:
        payload = {"fetched_at": fetched_at, "data": {"mdx_download_list": {"M": "m.onnx"}}}
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_fresh_disk_cache_skips_the_network(self) -> None:
        self._write_cache(time.time())
        with mock.patch.object(
            mc, "_urlopen", side_effect=AssertionError("network hit despite fresh cache")
        ), mock.patch.object(mc, "_start_background_refresh") as refresh:
            data = mc.load_mvsepless_models()
        self.assertIsNotNone(data)
        assert data is not None
        self.assertIn("mdx_download_list", data)
        refresh.assert_called_once()

    def test_stale_disk_cache_still_fetches(self) -> None:
        self._write_cache(time.time() - (mc._MVSEPLESS_CACHE_TTL_SECONDS + 60))
        with mock.patch.object(mc, "_urlopen", side_effect=OSError("offline")):
            data = mc.load_mvsepless_models()
        # Falls back to the stale disk copy rather than returning nothing.
        self.assertIsNotNone(data)

    def test_force_bypasses_the_disk_cache(self) -> None:
        self._write_cache(time.time())
        with mock.patch.object(mc, "_urlopen", side_effect=OSError("offline")) as opener:
            mc.load_mvsepless_models(force=True)
        opener.assert_called_once()

    def test_disk_cache_fast_path_invalidates_display_cache(self) -> None:
        """The fast path replaces ``_cached_models`` from disk, same as the
        network path -- if it skipped ``clear_display_cache()``, a merge
        computed earlier in the process (before mvsepless data existed, or
        with stale data) would stay pinned for the life of the process.
        """
        import io

        import core.model_display as md

        def _fetch(payload: dict):
            return lambda url: io.BytesIO(json.dumps(payload).encode("utf-8"))

        raw_entry = {
            "model_type": "mdx23c",
            "full_name": "Mvsepless Regression A",
            "checkpoint_url": "https://example.com/a.ckpt",
            "config_url": "https://example.com/a.yaml",
            "category": "Вокал",
            "stems": ["vocals", "instrumental"],
        }
        with mock.patch.object(mc, "_write_disk_cache"):
            with mock.patch.object(
                mc,
                "_urlopen",
                side_effect=_fetch({"entry-a": raw_entry}),
            ):
                mc.load_mvsepless_models(force=True)
        md.clear_display_cache()
        first = md._merged_for_display()
        self.assertIn("Mvsepless Regression A", first.mdx)

        # Simulate a fresh in-process cache miss (e.g. a new process)
        # with a *different* payload sitting on disk within TTL -- the
        # fast path under test. Bypass clear_mvsepless_cache() itself,
        # which would trivially invalidate the display cache regardless
        # of whether the fast path does its own invalidation.
        mc._cached_models = None
        mc._cached_loaded_at = 0.0
        self._write_cache(time.time())
        with mock.patch.object(
            mc,
            "_urlopen",
            side_effect=AssertionError("network hit despite fresh cache"),
        ), mock.patch.object(mc, "_start_background_refresh"):
            mc.load_mvsepless_models()

        second = md._merged_for_display()

        self.assertIsNot(
            first,
            second,
            "disk-cache fast path must invalidate the memoized display merge",
        )

    def test_failed_fetch_does_not_reset_the_disk_ttl(self) -> None:
        old = time.time() - 3600  # one hour old
        self._write_cache(old)
        with mock.patch.object(mc, "_urlopen", side_effect=OSError("offline")):
            mc.load_mvsepless_models(force=True)
        with open(self.cache_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertAlmostEqual(
            payload["fetched_at"],
            old,
            delta=1.0,
            msg="a failed fetch rewrote fetched_at, making stale data look fresh",
        )


if __name__ == "__main__":
    unittest.main()
