"""_build_meta enriches empty stems from the catalogue YAML stem cache."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any
from unittest import mock

from core import catalog_sources
from core import catalogue_stem_cache as csc
from core.catalogue_stem_cache import StemCacheError, StemCacheHit
from core.catalogue_types import CatalogueEvidenceState
from core.mdx_runtime_contract import MdxConfigEvidence
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
        from core.model_manifest.runtime import bundled_catalogue_config_evidence

        def exact_fixture(model_id: str, config_yaml: str) -> MdxConfigEvidence | None:
            if (
                model_id == "mdx:mbr_guitar_becruily"
                and config_yaml.casefold() == "mbr_guitar_becruily_config.yaml"
            ):
                return MdxConfigEvidence(
                    training_instruments=("Guitar", "Other"),
                    target_instrument="Guitar",
                    content_sha256=(
                        "3438f5eef8881dfadd26f7c1b9481b9fcfa99de9e8be24b90e50ca63de7b7581"
                    ),
                    sources=(f"fixture:{config_yaml}",),
                )
            return bundled_catalogue_config_evidence(model_id, config_yaml)

        self._bundled_evidence = mock.patch(
            "core.model_manifest.runtime.bundled_catalogue_config_evidence",
            side_effect=exact_fixture,
        )
        self._bundled_evidence.start()
        clear_display_cache()

    def tearDown(self) -> None:
        clear_display_cache()
        self._bundled_evidence.stop()
        self._apollo.stop()
        self._env.stop()

    def test_cache_hit_fills_empty_stems(self) -> None:
        hit = StemCacheHit(
            stems=("Vocals", "other"),
            target_instrument="Vocals",
            ok=True,
            content_sha256="a" * 64,
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
        self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.READY)
        lookup.assert_called()
        enqueue.assert_not_called()
        ensure.assert_not_called()

    def test_exact_mdx_c_cache_evidence_projects_reviewed_semantics(self) -> None:
        digest = "723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d"
        hit = StemCacheHit(
            stems=("Instrumental", "Vocals"),
            target_instrument="Instrumental",
            ok=True,
            content_sha256=digest,
        )
        supplements = (
            {},
            {
                "Reviewed": {
                    "melband_roformer_inst_v1.ckpt": "https://example.test/model.ckpt",
                    "config_melbandroformer_inst.yaml": _YAML_URL,
                }
            },
            {},
            {},
        )

        with _with_supplements(supplements):
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
                merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        projection = merged.meta["Reviewed"].stem_semantics
        self.assertEqual(projection.status, "reviewed")
        self.assertEqual(
            tuple(route.native for route in projection.routes if route.native is not None),
            ("Instrumental",),
        )

    def test_live_dereverb_mdx23c_two_native_signature_stays_reviewed(self) -> None:
        label = "MDX23C Model: MDX23C DeReverb by aufr33 & jarredou"
        config_url = (
            "https://raw.githubusercontent.com/Politrees/UVR_resources/refs/heads/"
            "main/UVR_resources/configs/MDX23C/config_dereverb_mdx23c.yaml"
        )
        digest = "a0cf11216913ab8941afb96fa7ab333390d1740b4a74a5d2f4b81ca8a218c756"
        hit = StemCacheHit(
            stems=("dry", "No dry"),
            target_instrument=None,
            ok=True,
            content_sha256=digest,
        )

        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            meta = catalog_sources._build_meta(
                {
                    label: {
                        "MDX23C-De-Reverb-aufr33-jarredou.ckpt": (
                            "https://example.test/MDX23C-De-Reverb-aufr33-jarredou.ckpt"
                        ),
                        "config_dereverb_mdx23c.yaml": config_url,
                    }
                },
                "MDX-Net",
                {},
                {},
            )[label]

        self.assertEqual(meta.config_sha256, digest)
        self.assertEqual(meta.stems, ["dry", "No dry"])
        self.assertIsNone(meta.target_instrument)
        self.assertEqual(
            meta.stem_semantics.status,
            "reviewed",
            meta.catalogue_evidence_warning,
        )
        self.assertEqual(meta.catalogue_evidence_warning, "")
        self.assertEqual(
            [
                (route.native, route.role, route.production, route.complement_of)
                for route in meta.stem_semantics.routes
            ],
            [
                ("dry", "effect.reverb.removed", "native", None),
                ("No dry", "effect.reverb", "native", None),
            ],
        )

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
        self.assertEqual(
            merged.meta["M"].catalogue_evidence_status,
            CatalogueEvidenceState.PENDING,
        )
        enqueue.assert_not_called()
        ensure.assert_not_called()

    def test_live_exact_config_replaces_existing_summary_stems(self) -> None:
        digest = "a" * 64
        hit = StemCacheHit(
            stems=("Different", "Inventory"),
            target_instrument="Different",
            ok=True,
            content_sha256=digest,
        )
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
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit) as lookup:
                with mock.patch("core.catalogue_stem_cache.enqueue_missing") as enqueue:
                    with mock.patch("core.catalogue_stem_cache.ensure_worker_started") as ensure:
                        merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, ["Different", "Inventory"])
        self.assertEqual(meta.target_instrument, "Different")
        self.assertEqual(meta.config_sha256, digest)
        lookup.assert_called_once_with(_YAML_URL)
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
        self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.UNAVAILABLE)
        self.assertIn("YAML validation failed", meta.catalogue_evidence_warning)
        enqueue.assert_not_called()
        ensure.assert_not_called()

    def test_live_exact_config_overrides_bundled_and_mismatch_is_model_specific(self) -> None:
        label = "Mel-Band Roformer Instrumental by Becruily [mbr_guitar_becruily]"
        hit = StemCacheHit(
            stems=("Bass", "Other"),
            target_instrument="Bass",
            ok=True,
            content_sha256="f" * 64,
        )
        supplements = (
            {},
            {
                label: {
                    "mbr_guitar_becruily.ckpt": "https://example.test/model.ckpt",
                    "mbr_guitar_becruily_config.yaml": _YAML_URL,
                }
            },
            {},
            {label: {"stems": ["Instrumental"], "target_instrument": "Instrumental"}},
        )
        with _with_supplements(supplements):
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
                merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        meta = merged.meta[label]
        self.assertEqual(meta.stems, ["Bass", "Other"])
        self.assertEqual(meta.target_instrument, "Bass")
        self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.READY)
        self.assertEqual(meta.stem_semantics.status, "raw")
        self.assertIn("mdx:mbr_guitar_becruily", meta.catalogue_evidence_warning)
        self.assertIn("mismatch", meta.catalogue_evidence_warning)

    def test_stale_live_evidence_retains_reviewed_routes_and_warning(self) -> None:
        label = "Mel-Band Roformer Instrumental by Becruily [mbr_guitar_becruily]"
        hit = StemCacheHit(
            stems=("Guitar", "Other"),
            target_instrument="Guitar",
            ok=True,
            content_sha256="3438f5eef8881dfadd26f7c1b9481b9fcfa99de9e8be24b90e50ca63de7b7581",
            last_error=StemCacheError("network", "temporary outage", 1.0),
            stale=True,
            warning="temporary outage",
        )
        supplements = (
            {},
            {
                label: {
                    "mbr_guitar_becruily.ckpt": "https://example.test/model.ckpt",
                    "mbr_guitar_becruily_config.yaml": _YAML_URL,
                }
            },
            {},
            {},
        )
        with _with_supplements(supplements):
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
                merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        meta = merged.meta[label]
        self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.STALE)
        self.assertEqual(meta.catalogue_evidence_warning, "temporary outage")
        self.assertEqual(meta.stem_semantics.status, "reviewed")
        self.assertEqual(meta.stem_semantics.routes[0].native, "Guitar")

    def test_same_semantics_digest_drift_stays_reviewed_for_ordinary_catalogue_evidence(
        self,
    ) -> None:
        label = "Mel-Band Roformer Instrumental by Becruily [mbr_guitar_becruily]"
        hit = StemCacheHit(
            stems=("Guitar", "Other"),
            target_instrument="Guitar",
            ok=True,
            content_sha256="f" * 64,
        )
        supplements = (
            {},
            {
                label: {
                    "mbr_guitar_becruily.ckpt": "https://example.test/model.ckpt",
                    "mbr_guitar_becruily_config.yaml": _YAML_URL,
                }
            },
            {},
            {},
        )
        with _with_supplements(supplements):
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
                merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        meta = merged.meta[label]
        self.assertEqual(meta.stem_semantics.status, "reviewed")
        self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.READY)
        self.assertIn("digest-drift", meta.catalogue_evidence_warning)

    def test_live_training_field_drift_is_raw_before_target_only_projection(self) -> None:
        label = "Mel-Band Roformer Instrumental by Becruily [mbr_guitar_becruily]"
        hit = StemCacheHit(
            stems=("Guitar", "Piano"),
            target_instrument="Guitar",
            ok=True,
            content_sha256="f" * 64,
        )
        supplements = (
            {},
            {
                label: {
                    "mbr_guitar_becruily.ckpt": "https://example.test/model.ckpt",
                    "mbr_guitar_becruily_config.yaml": _YAML_URL,
                }
            },
            {},
            {},
        )
        with _with_supplements(supplements):
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
                merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        meta = merged.meta[label]
        self.assertEqual(meta.stems, ["Guitar", "Piano"])
        self.assertEqual(meta.target_instrument, "Guitar")
        self.assertEqual(meta.stem_semantics.status, "raw")
        self.assertIn("catalogue-evidence-mismatch", meta.catalogue_evidence_warning)
        self.assertIn("training.instruments", meta.catalogue_evidence_warning)

    def test_ordinary_config_basename_drift_with_exact_fields_stays_reviewed(self) -> None:
        label = "Mel-Band Roformer Instrumental by Becruily [mbr_guitar_becruily]"
        hit = StemCacheHit(
            stems=("Guitar", "Other"),
            target_instrument="Guitar",
            ok=True,
            content_sha256="3438f5eef8881dfadd26f7c1b9481b9fcfa99de9e8be24b90e50ca63de7b7581",
        )
        supplements = (
            {},
            {
                label: {
                    "mbr_guitar_becruily.ckpt": "https://example.test/model.ckpt",
                    "renamed_live_config.yaml": _YAML_URL,
                }
            },
            {},
            {},
        )
        with _with_supplements(supplements):
            with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
                merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        meta = merged.meta[label]
        self.assertEqual(meta.stem_semantics.status, "reviewed")
        self.assertEqual(meta.catalogue_evidence_warning, "")
        self.assertEqual(meta.stems, ["Guitar", "Other"])


class SemanticProjectionTests(unittest.TestCase):
    """Consumer data comes from the exact manifest projection, never aliases."""

    def test_projection_keeps_backend_values_and_canonical_route_presentation(self) -> None:
        from core.model_stem_semantics import (
            resolve_catalogue_stem_semantics,
            stem_semantics_projection,
        )

        semantics = resolve_catalogue_stem_semantics(
            "mdx:bs_neo_inst_beta",
            native_stems=("other",),
            backend_primary="other",
            backend_target="other",
        )
        payload = stem_semantics_projection(
            semantics, backend_primary="other", backend_target="other"
        ).as_dict()

        self.assertEqual(
            set(payload),
            {
                "backend_primary_stem",
                "backend_target_stem",
                "logical_primary_role",
                "logical_secondary_role",
                "stem_semantics_status",
                "stem_context",
                "stem_routes",
            },
        )
        self.assertEqual(
            {
                key: payload[key]
                for key in (
                    "backend_primary_stem",
                    "backend_target_stem",
                    "logical_primary_role",
                    "logical_secondary_role",
                    "stem_semantics_status",
                    "stem_context",
                )
            },
            {
                "backend_primary_stem": "other",
                "backend_target_stem": "other",
                "logical_primary_role": "mix.instrumental",
                "logical_secondary_role": None,
                "stem_semantics_status": "reviewed",
                "stem_context": "full_mix",
            },
        )
        self.assertEqual(
            payload["stem_routes"][0],
            {
                "native": None,
                "role": "vocal.vocals",
                "display": "Vocals",
                "filename_tag": "Vocals",
                "production": "derived",
                "logical_primary": False,
                "logical_secondary": False,
                "complement_of": "mix.instrumental",
                "selected_by_default": True,
            },
        )
        self.assertEqual(
            payload["stem_routes"][1],
            {
                "native": "other",
                "role": "mix.instrumental",
                "display": "Instrumental",
                "filename_tag": "Instrumental",
                "production": "native",
                "logical_primary": True,
                "logical_secondary": False,
                "selected_by_default": True,
            },
        )

    def test_projection_preserves_an_explicit_false_output_default(self) -> None:
        from core.model_stem_semantics import stem_semantics_projection
        from core.stem_roles import (
            ModelStemSemantics,
            SemanticStemOutput,
            StemId,
            StemProcessingContext,
            StemProduction,
            StemReviewStatus,
            StemRoleId,
        )

        semantics = ModelStemSemantics(
            model_id="mdx:fixture",
            context=StemProcessingContext.FULL_MIX,
            intent="instrumental",
            outputs=(
                SemanticStemOutput(
                    native=StemId("Other"),
                    role=StemRoleId("mix.instrumental"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                    selected_by_default=False,
                ),
            ),
            status=StemReviewStatus.REVIEWED,
            evidence="fixture",
        )

        route = stem_semantics_projection(semantics).as_dict()["stem_routes"][0]

        self.assertIs(route["selected_by_default"], False)

    def test_projection_exposes_only_the_explicit_logical_secondary(self) -> None:
        from core.model_stem_semantics import stem_semantics_projection
        from core.stem_roles import (
            ModelStemSemantics,
            SemanticStemOutput,
            StemId,
            StemProcessingContext,
            StemProduction,
            StemReviewStatus,
            StemRoleId,
        )

        secondary_role = StemRoleId("vocal.lead")
        semantics = ModelStemSemantics(
            model_id="mdx:fixture",
            context=StemProcessingContext.FULL_MIX,
            intent="karaoke",
            outputs=(
                SemanticStemOutput(
                    native=StemId("Lead"),
                    role=secondary_role,
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                    logical_secondary=True,
                ),
                SemanticStemOutput(
                    native=StemId("Backing"),
                    role=StemRoleId("vocal.backing"),
                    production=StemProduction.NATIVE,
                    backend_primary=True,
                    logical_primary=True,
                ),
            ),
            status=StemReviewStatus.REVIEWED,
            evidence="fixture",
            logical_secondary_role=secondary_role,
        )

        payload = stem_semantics_projection(semantics).as_dict()

        self.assertEqual(payload["logical_secondary_role"], "vocal.lead")
        self.assertEqual(
            [route["logical_secondary"] for route in payload["stem_routes"]],
            [True, False],
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
                ("other",),
                StemProcessingContext.FULL_MIX,
                "reviewed",
                "mix.instrumental",
                ("vocal.vocals", "mix.instrumental"),
            ),
            (
                "waived",
                "apollo:apollo_edm_by_essid",
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
                ("vocals", "other"),
                StemProcessingContext.FULL_MIX,
                "raw",
                None,
                (),
            ),
            (
                "normal karaoke",
                "mdx:bs_karaoke_anvuew",
                ("Vocals",),
                StemProcessingContext.FULL_MIX,
                "reviewed",
                "mix.instrumental_with_backing_vocals",
                ("vocal.lead", "mix.instrumental_with_backing_vocals"),
            ),
            (
                "vocal splitter",
                "mdx:bs_karaoke_anvuew",
                ("Vocals",),
                StemProcessingContext.VOCAL_SPLIT,
                "reviewed",
                "vocal.backing",
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
                ("center",),
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
                "effect.reverb.removed",
                ("effect.reverb.removed", "effect.reverb"),
            ),
            (
                "multi stem",
                "demucs:demucs",
                ("drums", "bass", "other", "vocals"),
                StemProcessingContext.FULL_MIX,
                "reviewed",
                "vocal.vocals",
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

        mismatch = resolve_catalogue_stem_semantics(
            "mdx:bs_neo_inst_beta", native_stems=("vocals", "other")
        )
        self.assertIn("signature-mismatch", mismatch.warning)


if __name__ == "__main__":
    unittest.main()
