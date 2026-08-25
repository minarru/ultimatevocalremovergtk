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
    return mock.patch.object(catalog_sources, "_supplemental_sources", return_value=supplements)


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
        self._apollo = mock.patch.object(catalog_sources, "apollo_download_list", return_value={})
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
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit) as lookup:
                with mock.patch("core.catalogue_stem_cache.enqueue_missing") as enqueue:
                    with mock.patch("core.catalogue_stem_cache.ensure_worker_started") as ensure:
                        merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, ["Vocals", "other"])
        self.assertEqual(meta.target_instrument, "Vocals")
        lookup.assert_called()
        enqueue.assert_not_called()
        ensure.assert_not_called()

    def test_stem_cache_miss_does_not_start_worker(self) -> None:
        supplements = (
            {},
            {"M": {"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL_QS}},
            {},
            {},
        )
        with _with_supplements(supplements):
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=None):
                with mock.patch("core.catalogue_stem_cache.enqueue_missing") as enqueue:
                    with mock.patch("core.catalogue_stem_cache.ensure_worker_started") as ensure:
                        merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertEqual(merged.meta["M"].stems, [])
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
            with mock.patch("core.catalogue_stem_cache.lookup_stems") as lookup:
                with mock.patch("core.catalogue_stem_cache.enqueue_missing") as enqueue:
                    with mock.patch("core.catalogue_stem_cache.ensure_worker_started") as ensure:
                        merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
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
                with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=None):
                    with mock.patch("core.catalogue_stem_cache.enqueue_missing") as enqueue:
                        with mock.patch(
                            "core.catalogue_stem_cache.ensure_worker_started"
                        ) as ensure:
                            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertEqual(merged.meta["M"].stems, [])
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
                    with mock.patch("core.catalogue_stem_cache.enqueue_missing") as enqueue:
                        with mock.patch(
                            "core.catalogue_stem_cache.ensure_worker_started"
                        ) as ensure:
                            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
                csc.clear_catalogue_stem_cache()
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, [])
        self.assertIsNone(meta.target_instrument)
        enqueue.assert_not_called()
        ensure.assert_not_called()


class SemanticProjectionTests(unittest.TestCase):
    """Consumer data comes from the exact manifest projection, never aliases."""

    def test_projection_keeps_backend_values_and_canonical_route_presentation(self) -> None:
        from core.model_stem_semantics import (
            resolve_catalogue_stem_semantics,
            stem_semantics_projection,
        )

        semantics = resolve_catalogue_stem_semantics(
            "mdx:bs_neo_inst_beta",
            native_stems=("vocals", "other"),
            backend_primary="other",
            backend_target="other",
        )
        payload = stem_semantics_projection(
            semantics, backend_primary="other", backend_target="other"
        ).as_dict()

        self.assertEqual(
            {
                key: payload[key]
                for key in (
                    "backend_primary_stem",
                    "backend_target_stem",
                    "logical_primary_role",
                    "stem_semantics_status",
                    "stem_context",
                )
            },
            {
                "backend_primary_stem": "other",
                "backend_target_stem": "other",
                "logical_primary_role": "mix.instrumental",
                "stem_semantics_status": "reviewed",
                "stem_context": "full_mix",
            },
        )
        self.assertEqual(
            payload["stem_routes"][0],
            {
                "native": "other",
                "role": "mix.instrumental",
                "display": "Instrumental",
                "filename_tag": "Instrumental",
                "production": "native",
                "logical_primary": True,
            },
        )

    def test_projection_covers_reviewed_waived_and_raw_statuses(self) -> None:
        from core.model_stem_semantics import (
            resolve_catalogue_stem_semantics,
            stem_semantics_projection,
        )
        from core.stem_roles import StemProcessingContext

        cases = (
            (
                "reviewed",
                "mdx:bs_neo_inst_beta",
                ("vocals", "other"),
                StemProcessingContext.FULL_MIX,
                "reviewed",
                "mix.instrumental",
                ("mix.instrumental", "vocal.vocals"),
            ),
            (
                "waived",
                "mdx:Kim_Inst",
                (),
                StemProcessingContext.FULL_MIX,
                "waived",
                None,
                (),
            ),
            (
                "raw unknown",
                "mdx:not_in_the_manifest",
                ("other",),
                StemProcessingContext.FULL_MIX,
                "raw",
                None,
                (),
            ),
            (
                "signature mismatch",
                "mdx:bs_neo_inst_beta",
                ("other",),
                StemProcessingContext.FULL_MIX,
                "raw",
                None,
                (),
            ),
            (
                "normal karaoke",
                "mdx:bs_karaoke_anvuew",
                ("Vocals", "Instrumental"),
                StemProcessingContext.FULL_MIX,
                "reviewed",
                "vocal.lead",
                ("vocal.lead", "mix.instrumental_with_backing_vocals"),
            ),
            (
                "vocal splitter",
                "mdx:bs_karaoke_anvuew",
                ("Vocals", "Instrumental"),
                StemProcessingContext.VOCAL_SPLIT,
                "reviewed",
                "vocal.lead",
                ("vocal.lead", "vocal.backing"),
            ),
            (
                "BVE",
                "vr:UVR-BVE-4B_SN-44100-1",
                ("Vocals", "Instrumental"),
                StemProcessingContext.VOCAL_SPLIT,
                "reviewed",
                "vocal.backing",
                ("vocal.backing", "vocal.lead"),
            ),
            (
                "spatial",
                "mdx:bs_mid_side1_gilliaaan",
                ("center", "wide"),
                StemProcessingContext.FULL_MIX,
                "reviewed",
                "spatial.center",
                ("spatial.center", "spatial.side"),
            ),
            (
                "effect removal",
                "mdx:MDX23C-De-Reverb-aufr33-jarredou",
                ("dry", "No dry"),
                StemProcessingContext.FULL_MIX,
                "reviewed",
                "effect.reverb",
                ("effect.reverb", "effect.reverb.removed"),
            ),
            (
                "multi stem",
                "demucs:demucs",
                ("drums", "bass", "other", "vocals"),
                StemProcessingContext.FULL_MIX,
                "reviewed",
                "instrument.drums",
                (
                    "instrument.drums",
                    "instrument.bass",
                    "residual.other",
                    "vocal.vocals",
                ),
            ),
        )
        for (
            name,
            model_id,
            native_stems,
            context,
            status,
            logical_primary,
            roles,
        ) in cases:
            with self.subTest(name=name):
                semantics = resolve_catalogue_stem_semantics(
                    model_id,
                    native_stems=native_stems,
                    context=context,
                )
                projection = stem_semantics_projection(semantics)
                self.assertEqual(projection.status, status)
                self.assertEqual(projection.context, context.value)
                self.assertEqual(projection.logical_primary_role, logical_primary)
                self.assertEqual(projection.canonical_roles, roles)

        mismatch = resolve_catalogue_stem_semantics("mdx:bs_neo_inst_beta", native_stems=("other",))
        self.assertIn("signature-mismatch", mismatch.warning)


if __name__ == "__main__":
    unittest.main()
