"""_merged_for_display must be memoized and explicitly invalidatable.

Rebuilding it per call made format_tag_title ~9 ms, so populating one
secondary-model expander cost ~800 ms of main-thread time.
"""

from __future__ import annotations

import io
import json
import os
import unittest
from unittest import mock

import core.model_display as md
from core.mvsepless_catalog import clear_mvsepless_cache
from core.politrees_catalog import clear_politrees_cache


class MergedForDisplayCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        md.clear_display_cache()

    def tearDown(self) -> None:
        md.clear_display_cache()

    def test_repeated_calls_reuse_one_merge(self) -> None:
        import core.catalog_sources as cs

        real = cs.merged_catalogues
        with mock.patch.object(cs, "merged_catalogues", side_effect=real) as spy:
            first = md._merged_for_display()
            second = md._merged_for_display()
        self.assertIs(first, second)
        self.assertEqual(spy.call_count, 1)

    def test_clear_display_cache_forces_rebuild(self) -> None:
        first = md._merged_for_display()
        md.clear_display_cache()
        second = md._merged_for_display()
        self.assertIsNot(first, second)

    def test_clear_politrees_cache_invalidates_display_cache(self) -> None:
        from core.politrees_catalog import clear_politrees_cache

        first = md._merged_for_display()
        clear_politrees_cache()
        second = md._merged_for_display()
        self.assertIsNot(
            first, second, "politrees feeds _display_base; its cache must invalidate"
        )


class CatalogueRefreshInvalidatesDisplayCacheTests(unittest.TestCase):
    """A politrees/mvsepless data refresh must be reflected, not just an
    explicit clear_politrees_cache()/clear_mvsepless_cache() call.

    load_politrees_links() and load_mvsepless_models() both replace their
    module-level cached data directly -- on a TTL rollover, or a first fetch
    that failed followed by one that succeeds -- without ever routing through
    clear_politrees_cache()/clear_mvsepless_cache(). Before this fix, that left
    _merged_for_display() pinned to whatever it saw on its first call, for the
    life of the process, even after fresh data arrived.
    """

    def setUp(self) -> None:
        md.clear_display_cache()
        clear_politrees_cache()
        clear_mvsepless_cache()

    def tearDown(self) -> None:
        md.clear_display_cache()
        clear_politrees_cache()
        clear_mvsepless_cache()

    def test_politrees_data_refresh_is_reflected_without_explicit_clear(self) -> None:
        import core.politrees_catalog as pc

        def _payload(label: str, filename: str) -> dict:
            return {"vr_download_list": {label: {filename: f"https://example.com/{filename}"}}}

        def _fetch(payload: dict):
            return lambda url: io.BytesIO(json.dumps(payload).encode("utf-8"))

        with mock.patch.dict(os.environ, {"UVR_DISABLE_POLITREES": "0"}):
            with mock.patch.object(pc, "_write_disk_cache"):
                with mock.patch.object(
                    pc,
                    "_urlopen",
                    side_effect=_fetch(_payload("Politrees Regression A", "regress-a.pth")),
                ):
                    pc.load_politrees_links(force=True)
                first = md._merged_for_display()
                self.assertIn("Politrees Regression A", first.vr)

                # Simulate a TTL rollover / retried fetch: this replaces the
                # cached data straight from load_politrees_links(), the exact
                # path that used to leave the memoized merge stale.
                with mock.patch.object(
                    pc,
                    "_urlopen",
                    side_effect=_fetch(_payload("Politrees Regression B", "regress-b.pth")),
                ):
                    pc.load_politrees_links(force=True)
                second = md._merged_for_display()

        self.assertIsNot(first, second)
        self.assertIn("Politrees Regression B", second.vr)
        self.assertNotIn(
            "Politrees Regression A",
            second.vr,
            "stale merge: refreshed politrees data was not reflected",
        )

    def test_mvsepless_data_refresh_is_reflected_without_explicit_clear(self) -> None:
        import core.mvsepless_catalog as mc

        base = "https://huggingface.co/noblebarkrr/mvsepless_resources/resolve/main"

        def _payload(full_name: str, ckpt: str) -> dict:
            return {
                "sample": {
                    "model_type": "mel_band_roformer",
                    "category": "test",
                    "id": 1,
                    "full_name": full_name,
                    "stems": ["vocals", "other"],
                    "target_instrument": "vocals",
                    "checkpoint_url": f"{base}/{ckpt}?download=true",
                    "config_url": f"{base}/{ckpt}_config.yaml?download=true",
                }
            }

        def _fetch(payload: dict):
            return lambda url: io.BytesIO(json.dumps(payload).encode("utf-8"))

        with mock.patch.dict(os.environ, {"UVR_DISABLE_MVSEPLESS": "0"}):
            with mock.patch.object(mc, "_write_disk_cache"):
                with mock.patch.object(
                    mc,
                    "_urlopen",
                    side_effect=_fetch(_payload("Mvsepless Regression A", "regress-a.ckpt")),
                ):
                    mc.load_mvsepless_models(force=True)
                first = md._merged_for_display()
                self.assertIn("Mvsepless Regression A", first.mdx)

                with mock.patch.object(
                    mc,
                    "_urlopen",
                    side_effect=_fetch(_payload("Mvsepless Regression B", "regress-b.ckpt")),
                ):
                    mc.load_mvsepless_models(force=True)
                second = md._merged_for_display()

        self.assertIsNot(first, second)
        self.assertIn("Mvsepless Regression B", second.mdx)
        self.assertNotIn(
            "Mvsepless Regression A",
            second.mdx,
            "stale merge: refreshed mvsepless data was not reflected",
        )


if __name__ == "__main__":
    unittest.main()
