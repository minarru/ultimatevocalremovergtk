"""_build_meta enriches empty stems from the catalogue YAML stem cache."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any
from unittest import mock

from core import catalog_sources
from core import catalogue_stem_cache as csc
from core.catalogue_stem_cache import StemCacheHit
from core.model_display import clear_display_cache

_CATALOGUE_OFF = {
    "UVR_DISABLE_POLITREES": "1",
    "UVR_DISABLE_MVSEPLESS": "1",
}

_YAML_URL = "https://example.test/model.yaml"
_YAML_URL_QS = "https://example.test/model.yaml?v=2"


def _with_supplements(supplements: Any) -> Any:
    return mock.patch.object(
        catalog_sources, "_supplemental_sources", return_value=supplements
    )


class YamlConfigUrlTests(unittest.TestCase):
    def test_returns_http_yaml_url_without_query(self) -> None:
        files = {
            "model.ckpt": "https://example.test/model.ckpt",
            "model.yaml": _YAML_URL_QS,
        }
        self.assertEqual(catalog_sources._yaml_config_url(files), _YAML_URL)

    def test_returns_none_without_http_yaml(self) -> None:
        self.assertIsNone(
            catalog_sources._yaml_config_url({"model.ckpt": "https://example.test/x"})
        )


class CatalogStemMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = mock.patch.dict(os.environ, _CATALOGUE_OFF, clear=False)
        self._env.start()
        # Positive stem-cache cases need the feature on; tearDown restores.
        os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None)
        # Curated Apollo extras ship http YAML URLs; keep merges under test only.
        self._apollo = mock.patch.object(
            catalog_sources, "apollo_download_list", return_value={}
        )
        self._apollo.start()
        clear_display_cache()

    def tearDown(self) -> None:
        clear_display_cache()
        self._apollo.stop()
        self._env.stop()

    def test_cache_hit_fills_empty_stems(self) -> None:
        hit = StemCacheHit(
            stems=("Vocals", "other"),
            target_instrument="Vocals",
            ok=True,
        )
        supplements = (
            {},
            {"M": {"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL}},
            {},
            {},
        )
        with _with_supplements(supplements):
            with mock.patch(
                "core.catalogue_stem_cache.lookup_stems", return_value=hit
            ) as lookup:
                with mock.patch(
                    "core.catalogue_stem_cache.enqueue_missing"
                ) as enqueue:
                    with mock.patch(
                        "core.catalogue_stem_cache.ensure_worker_started"
                    ) as ensure:
                        merged = catalog_sources.merged_catalogues(
                            vr={}, mdx={}, demucs={}
                        )
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, ["Vocals", "other"])
        self.assertEqual(meta.target_instrument, "Vocals")
        lookup.assert_called()
        enqueue.assert_not_called()
        ensure.assert_not_called()

    def test_miss_records_pending_yaml_without_starting_worker(self) -> None:
        supplements = (
            {},
            {"M": {"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL_QS}},
            {},
            {},
        )
        with _with_supplements(supplements):
            with mock.patch(
                "core.catalogue_stem_cache.lookup_stems", return_value=None
            ):
                with mock.patch(
                    "core.catalogue_stem_cache.enqueue_missing"
                ) as enqueue:
                    with mock.patch(
                        "core.catalogue_stem_cache.ensure_worker_started"
                    ) as ensure:
                        merged = catalog_sources.merged_catalogues(
                            vr={}, mdx={}, demucs={}
                        )
        self.assertEqual(merged.pending_yaml, (_YAML_URL,))
        enqueue.assert_not_called()
        ensure.assert_not_called()

    def test_existing_stems_skip_cache_and_enqueue(self) -> None:
        supplements = (
            {},
            {"M": {"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL}},
            {},
            {
                "M": {
                    "stems": ["Drums", "Bass"],
                    "target_instrument": "Drums",
                    "intent": "drums",
                }
            },
        )
        with _with_supplements(supplements):
            with mock.patch(
                "core.catalogue_stem_cache.lookup_stems"
            ) as lookup:
                with mock.patch(
                    "core.catalogue_stem_cache.enqueue_missing"
                ) as enqueue:
                    with mock.patch(
                        "core.catalogue_stem_cache.ensure_worker_started"
                    ) as ensure:
                        merged = catalog_sources.merged_catalogues(
                            vr={}, mdx={}, demucs={}
                        )
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, ["Drums", "Bass"])
        self.assertEqual(meta.target_instrument, "Drums")
        lookup.assert_not_called()
        enqueue.assert_not_called()
        ensure.assert_not_called()

    def test_disabled_catalogue_stems_skips_enqueue(self) -> None:
        supplements = (
            {},
            {"M": {"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL}},
            {},
            {},
        )
        with mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}):
            with _with_supplements(supplements):
                with mock.patch(
                    "core.catalogue_stem_cache.lookup_stems", return_value=None
                ):
                    with mock.patch(
                        "core.catalogue_stem_cache.enqueue_missing"
                    ) as enqueue:
                        with mock.patch(
                            "core.catalogue_stem_cache.ensure_worker_started"
                        ) as ensure:
                            merged = catalog_sources.merged_catalogues(
                                vr={}, mdx={}, demucs={}
                            )
        self.assertEqual(merged.pending_yaml, ())
        enqueue.assert_not_called()
        ensure.assert_not_called()

    def test_failed_cache_hit_does_not_re_enqueue(self) -> None:
        supplements = (
            {},
            {"M": {"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL}},
            {},
            {},
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "catalogue_stem_cache.json")
            with mock.patch.object(csc, "_cache_path", return_value=cache_path):
                csc.clear_catalogue_stem_cache()
                csc.remember_stems(_YAML_URL, [], None, ok=False)
                with _with_supplements(supplements):
                    with mock.patch(
                        "core.catalogue_stem_cache.enqueue_missing"
                    ) as enqueue:
                        with mock.patch(
                            "core.catalogue_stem_cache.ensure_worker_started"
                        ) as ensure:
                            merged = catalog_sources.merged_catalogues(
                                vr={}, mdx={}, demucs={}
                            )
                csc.clear_catalogue_stem_cache()
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, [])
        self.assertIsNone(meta.target_instrument)
        self.assertEqual(merged.pending_yaml, ())
        enqueue.assert_not_called()
        ensure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
