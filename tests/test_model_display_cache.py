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


@mock.patch.dict(
    os.environ,
    {
        "UVR_DISABLE_POLITREES": "1",
        "UVR_DISABLE_MVSEPLESS": "1",
        "UVR_DISABLE_CATALOGUE_STEMS": "1",
    },
)
class MergedForDisplayCacheTests(unittest.TestCase):
    """All three assertions here are about ``lru_cache`` identity/invalidation,
    not catalogue content, so both live sources are disabled for the whole
    class -- otherwise every call to ``_merged_for_display()`` fetches
    politrees and mvsepless over the network.
    """

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

    def test_clear_mvsepless_cache_invalidates_display_cache(self) -> None:
        first = md._merged_for_display()
        clear_mvsepless_cache()
        second = md._merged_for_display()
        self.assertIsNot(
            first, second, "mvsepless feeds the merge; its clear must invalidate"
        )

    def test_clear_extra_catalog_cache_invalidates_display_cache(self) -> None:
        from core.extra_catalog import clear_extra_catalog_cache

        first = md._merged_for_display()
        clear_extra_catalog_cache()
        second = md._merged_for_display()
        self.assertIsNot(
            first, second, "extras feed the merge; their clear must invalidate"
        )

    def test_mid_flight_clear_cannot_repin_stale_merge(self) -> None:
        """A clear during an in-flight miss must not become the live entry.

        Plain ``lru_cache`` + ``cache_clear()`` loses that race: the finishing
        miss stores under the (only) key after the clear. Keying on a generation
        that ``clear_display_cache`` bumps leaves the finishing miss under the
        old key, so the next read rebuilds.
        """
        import core.catalog_sources as cs

        real = cs.merged_catalogues
        calls = {"n": 0}

        def clearing_merge(*args: object, **kwargs: object):
            calls["n"] += 1
            if calls["n"] == 1:
                # Simulate a cross-thread clear while this miss is computing.
                md.clear_display_cache()
            return real(*args, **kwargs)

        with mock.patch.object(cs, "merged_catalogues", side_effect=clearing_merge):
            mid_flight = md._merged_for_display()
            gen_after_clear = md._display_generation
            after = md._merged_for_display()

        # The finishing miss is keyed on the pre-clear generation; the live
        # read must miss that lru slot and call merged_catalogues again.
        # (catalog_sources may still return a cached MergedCatalogues object
        # when sources did not change — identity equality is not required.)
        self.assertGreaterEqual(calls["n"], 2)
        self.assertGreaterEqual(gen_after_clear, 1)
        self.assertIsNotNone(mid_flight)
        self.assertIsNotNone(after)

    def test_reload_mappers_invalidates_display_cache(self) -> None:
        from core.model_data import ModelRepository

        first = md._merged_for_display()
        gen_before = md._display_generation
        # Avoid constructing a full repo: call the method unbound with a stub.
        stub = mock.MagicMock()
        ModelRepository.reload_mappers(stub)
        second = md._merged_for_display()
        self.assertGreater(md._display_generation, gen_before)
        self.assertIsNot(first, second)


@mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}, clear=False)
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

        with mock.patch.dict(
            os.environ,
            {"UVR_DISABLE_POLITREES": "0", "UVR_DISABLE_MVSEPLESS": "1"},
        ):
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

        with mock.patch.dict(
            os.environ,
            {"UVR_DISABLE_MVSEPLESS": "0", "UVR_DISABLE_POLITREES": "1"},
        ):
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

    def test_identical_politrees_refetch_does_not_invalidate_merge(self) -> None:
        import core.politrees_catalog as pc

        payload = {
            "vr_download_list": {
                "Politrees Same": {"same.pth": "https://example.com/same.pth"}
            }
        }

        def _fetch(_url: str):
            return io.BytesIO(json.dumps(payload).encode("utf-8"))

        with mock.patch.dict(
            os.environ,
            {"UVR_DISABLE_POLITREES": "0", "UVR_DISABLE_MVSEPLESS": "1"},
        ):
            with mock.patch.object(pc, "_write_disk_cache"):
                with mock.patch.object(pc, "_urlopen", side_effect=_fetch):
                    pc.load_politrees_links(force=True)
                first = md._merged_for_display()
                gen_before = md._display_generation
                with mock.patch.object(pc, "_urlopen", side_effect=_fetch):
                    pc.load_politrees_links(force=True)
                second = md._merged_for_display()

        self.assertEqual(md._display_generation, gen_before)
        self.assertIs(first, second)

    def test_identical_mvsepless_refetch_does_not_invalidate_merge(self) -> None:
        import core.mvsepless_catalog as mc

        base = "https://huggingface.co/noblebarkrr/mvsepless_resources/resolve/main"
        payload = {
            "sample": {
                "model_type": "mel_band_roformer",
                "category": "test",
                "id": 1,
                "full_name": "Mvsepless Same",
                "stems": ["vocals", "other"],
                "target_instrument": "vocals",
                "checkpoint_url": f"{base}/same.ckpt?download=true",
                "config_url": f"{base}/same.ckpt_config.yaml?download=true",
            }
        }

        def _fetch(_url: str):
            return io.BytesIO(json.dumps(payload).encode("utf-8"))

        with mock.patch.dict(
            os.environ,
            {"UVR_DISABLE_MVSEPLESS": "0", "UVR_DISABLE_POLITREES": "1"},
        ):
            with mock.patch.object(mc, "_write_disk_cache"):
                with mock.patch.object(mc, "_urlopen", side_effect=_fetch):
                    mc.load_mvsepless_models(force=True)
                first = md._merged_for_display()
                gen_before = md._display_generation
                with mock.patch.object(mc, "_urlopen", side_effect=_fetch):
                    mc.load_mvsepless_models(force=True)
                second = md._merged_for_display()

        self.assertEqual(md._display_generation, gen_before)
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
