import json
import os
import sys
import unittest
import urllib.error
from typing import Any, Mapping, Optional, cast
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import generate_models_catalogue as cli  # noqa: E402
from catalogue import collect as catalogue  # noqa: E402
from catalogue import render  # noqa: E402
from catalogue.stem_audit import (  # noqa: E402
    STEM_SEMANTICS_REFERENCE_HEADERS,
    CatalogueEvidenceCounts,
    NativeToRoleAmbiguity,
    RoleToNativeVariant,
    StemAuditDiagnostic,
    StemAuditResult,
    StemRelationshipEvidence,
    audit_catalogue_stems,
)

from core.catalogue_types import SourceId  # noqa: E402
from core.model_stem_manifest import load_stem_manifest_document  # noqa: E402
from core.stem_roles import (  # noqa: E402
    ModelStemSemantics,
    SemanticStemOutput,
    StemId,
    StemProcessingContext,
    StemProduction,
    StemReviewStatus,
    StemRoleId,
)


def _clean_stem_audit(*_args: object, **_kwargs: object) -> StemAuditResult:
    """Keep publication fixtures focused on artifact behavior, not manifest coverage."""
    return StemAuditResult(
        catalogue_model_ids=(),
        reviewed_model_ids=(),
        waived_model_ids=(),
        raw_model_ids=(),
        evidence_counts=CatalogueEvidenceCounts(148, 123, 92, ()),
        diagnostics=(),
    )


class DemucsBagArtifactTests(unittest.TestCase):
    def test_representative_weight_is_stable_across_json_key_order(self) -> None:
        entries = []
        rows = (
            {
                "mdx.yaml": "https://example.test/mdx.yaml",
                "c511e2ab-fe698775.th": "https://example.test/c511e2ab-fe698775.th",
                "7d865c68-3d5dd56b.th": "https://example.test/7d865c68-3d5dd56b.th",
            },
            {
                "7d865c68-3d5dd56b.th": "https://example.test/7d865c68-3d5dd56b.th",
                "c511e2ab-fe698775.th": "https://example.test/c511e2ab-fe698775.th",
                "mdx.yaml": "https://example.test/mdx.yaml",
            },
        )
        for payload in rows:
            entries.append(
                catalogue._parse_catalogue_entry(
                    source="test",
                    family="Demucs",
                    label="Demucs v3: mdx",
                    payload=payload,
                    ctx=catalogue.CatalogueContext(),
                    policy=catalogue.FetchPolicy(allow_network=False),
                )[0]
            )

        self.assertEqual(
            [entry.weight_file for entry in entries],
            ["c511e2ab-fe698775.th", "c511e2ab-fe698775.th"],
        )

    def test_representative_weight_totally_orders_case_equivalent_names(self) -> None:
        weights = []
        for keys in (("A.th", "a.th"), ("a.th", "A.th")):
            payload = {key: f"https://example.test/{key}" for key in keys}
            entry = catalogue._parse_catalogue_entry(
                source="test",
                family="Demucs",
                label="Demucs v3: case collision",
                payload=payload,
                ctx=catalogue.CatalogueContext(),
                policy=catalogue.FetchPolicy(allow_network=False),
            )[0]
            weights.append(entry.weight_file)

        self.assertEqual(weights, ["a.th", "a.th"])


class RuntimeStemSignatureTests(unittest.TestCase):
    def test_reviewed_collection_evidence_removes_exact_three_guess_false_positives(self) -> None:
        from core.model_stem_manifest import load_bundled_stem_semantics

        entries = [
            catalogue.ModelEntry(
                source="fixture",
                family=family,
                catalogue_label=model_id,
                weight_file=f"{model_id.partition(':')[2]}{extension}",
                instruments=["Instrumental", "Vocals"],
                primary_stem="Vocals",
                stem_count=2,
                name_intent="vocals",
                backend_focus="two_stem",
                metadata_source="community_models.txt",
                flags=["NAME says vocals but backend is not vocal-focused"],
            )
            for model_id, family, extension in (
                ("vr:3_HP-Vocal-UVR", "VR Architecture", ".pth"),
                ("vr:4_HP-Vocal-UVR", "VR Architecture", ".pth"),
                ("mdx:MDX23C_D1581", "MDX23C", ".ckpt"),
            )
        ]
        reconcile = getattr(catalogue, "reconcile_stem_semantics", None)
        self.assertIsNotNone(reconcile)
        assert reconcile is not None
        unreviewed = catalogue.ModelEntry(
            source="fixture",
            family="VR Architecture",
            catalogue_label="vr:private_HP-Vocal-UVR",
            weight_file="private_HP-Vocal-UVR.pth",
            instruments=["Instrumental", "Vocals"],
            primary_stem="Vocals",
            name_intent="vocals",
            best_result="Guessed vocal result",
            ui_export_note="UI: guessed vocal pair",
            metadata_source="community_models.txt",
            flags=["NAME says vocals but backend is not vocal-focused"],
        )

        reconcile([*entries, unreviewed], registry=load_bundled_stem_semantics())
        reviewed_semantics = [
            cast(catalogue.ReconciledStemEvidence, entry.stem_semantics) for entry in entries
        ]
        unreviewed_semantics = cast(catalogue.ReconciledStemEvidence, unreviewed.stem_semantics)

        self.assertEqual([entry.flags for entry in entries], [[], [], []])
        self.assertEqual(
            [semantics.model_id for semantics in reviewed_semantics],
            ["vr:3_HP-Vocal-UVR", "vr:4_HP-Vocal-UVR", "mdx:MDX23C_D1581"],
        )
        self.assertTrue(all(semantics.reviewed for semantics in reviewed_semantics))
        self.assertTrue(all(semantics.guessed_intent == "" for semantics in reviewed_semantics))
        self.assertFalse(unreviewed_semantics.reviewed)
        self.assertEqual(
            unreviewed.flags,
            ["NAME says vocals but backend is not vocal-focused"],
        )
        self.assertEqual(unreviewed.best_result, "Guessed vocal result")
        self.assertEqual(unreviewed.ui_export_note, "UI: guessed vocal pair")
        self.assertEqual(unreviewed_semantics.guessed_intent, "vocals")

    def test_exact_mdx_c_catalogue_evidence_requires_config_digest(self) -> None:
        digest = "451765e869b78dcb9ca9188a74da31f581b7254ff0e8b532aa76b974148de947"
        exact = catalogue.runtime_stem_reconciliation(
            "mdx:MDX23C-8KFFT-InstVoc_HQ",
            ("Vocals", "Instrumental"),
            config_yaml="model_2_stem_full_band_8k.yaml",
            config_sha256=digest,
            metadata_source="bundled_yaml:model_2_stem_full_band_8k.yaml",
        )
        missing = catalogue.runtime_stem_reconciliation(
            "mdx:MDX23C-8KFFT-InstVoc_HQ",
            ("Vocals", "Instrumental"),
            config_yaml="model_2_stem_full_band_8k.yaml",
            metadata_source="bundled_yaml:model_2_stem_full_band_8k.yaml",
        )

        self.assertTrue(exact.reviewed)
        self.assertFalse(exact.artifact_digest_verified)
        self.assertFalse(missing.reviewed)
        self.assertIn("config content SHA-256", missing.warning)

    def test_bundled_yaml_metadata_returns_exact_content_digest(self) -> None:
        instruments, target, _arch, source, digest = catalogue._load_yaml_meta(
            "model_2_stem_full_band_8k.yaml",
            allow_network=False,
        )

        self.assertEqual(instruments, ["Vocals", "Instrumental"])
        self.assertEqual(target, "")
        self.assertEqual(source, "bundled_yaml:model_2_stem_full_band_8k.yaml")
        self.assertEqual(
            digest,
            "451765e869b78dcb9ca9188a74da31f581b7254ff0e8b532aa76b974148de947",
        )

    def test_classic_karaoke_2_projects_exact_mdx_runtime_keys(self) -> None:
        self.assertEqual(
            catalogue.runtime_stem_signature(
                "mdx:UVR_MDXNET_KARA_2",
                ("other", "vocals"),
                target_instrument="other",
                metadata_source="community_models.txt",
            ),
            ("Instrumental", "Vocals"),
        )

    def test_yaml_target_projects_the_model_config_native_inventory(self) -> None:
        self.assertEqual(
            catalogue.runtime_stem_signature(
                "mdx:bs_bass_xlancer",
                ("bass", "other"),
                target_instrument="bass",
                metadata_source="bundled_yaml:bs_bass_xlancer_config.yaml",
            ),
            ("bass",),
        )
        self.assertEqual(
            catalogue.runtime_stem_signature(
                "mdx:bs_karaoke_gabox",
                ("vocals", "other"),
                target_instrument="vocals",
                metadata_source="remote_yaml:bs_karaoke_gabox_config.yaml",
            ),
            ("vocals",),
        )

    def test_community_target_hint_does_not_rewrite_runtime_inventory(self) -> None:
        self.assertEqual(
            catalogue.runtime_stem_signature(
                "mdx:community-only",
                ("Vocals", "Instrumental"),
                target_instrument="Vocals",
                metadata_source="community_models.txt",
            ),
            ("Vocals", "Instrumental"),
        )


class ReviewedResultProjectionTests(unittest.TestCase):
    """Reviewed routes, not pre-review guesses, own published result prose."""

    def _bundled_projection(self, model_id: str) -> catalogue.ReviewedResultProjection:
        from core.model_stem_manifest import (
            load_bundled_stem_semantics,
            resolve_model_stem_semantics,
        )

        registry = load_bundled_stem_semantics()
        declaration = registry.models[model_id]
        semantics = resolve_model_stem_semantics(
            model_id,
            native_stems=declaration.native_signature,
            context=StemProcessingContext.FULL_MIX,
            registry=registry,
        )
        self.assertEqual(semantics.status, StemReviewStatus.REVIEWED)
        return catalogue._reviewed_result_projection((semantics,), registry)

    def _explicit_secondary_projection(self) -> catalogue.ReviewedResultProjection:
        from core.model_stem_manifest import load_bundled_stem_semantics

        registry = load_bundled_stem_semantics()
        semantics = ModelStemSemantics(
            model_id="mdx:explicit-secondary",
            context=StemProcessingContext.FULL_MIX,
            intent="specialty_stem",
            outputs=(
                SemanticStemOutput(
                    native=StemId("backing"),
                    role=StemRoleId("vocal.backing"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                    selected_by_default=False,
                ),
                SemanticStemOutput(
                    native=StemId("drums"),
                    role=StemRoleId("instrument.drums"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                    logical_secondary=True,
                ),
                SemanticStemOutput(
                    native=StemId("side"),
                    role=StemRoleId("spatial.side"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                ),
                SemanticStemOutput(
                    native=StemId("center"),
                    role=StemRoleId("spatial.center"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=True,
                ),
            ),
            status=StemReviewStatus.REVIEWED,
            evidence="fixture",
            logical_secondary_role=StemRoleId("instrument.drums"),
        )
        return catalogue._reviewed_result_projection((semantics,), registry)

    def _pair_secondary_projection(self) -> catalogue.ReviewedResultProjection:
        from core.model_stem_manifest import load_bundled_stem_semantics

        registry = load_bundled_stem_semantics()
        semantics = ModelStemSemantics(
            model_id="mdx:pair-secondary",
            context=StemProcessingContext.FULL_MIX,
            intent="specialty_stem",
            outputs=(
                SemanticStemOutput(
                    native=StemId("drums"),
                    role=StemRoleId("instrument.drums"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                ),
                SemanticStemOutput(
                    native=StemId("side"),
                    role=StemRoleId("spatial.side"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=False,
                ),
                SemanticStemOutput(
                    native=StemId("center"),
                    role=StemRoleId("spatial.center"),
                    production=StemProduction.NATIVE,
                    backend_primary=False,
                    logical_primary=True,
                ),
            ),
            status=StemReviewStatus.REVIEWED,
            evidence="fixture",
        )
        return catalogue._reviewed_result_projection((semantics,), registry)

    def test_result_prose_orders_exact_routes_by_semantic_priority(self) -> None:
        cases = (
            (
                "ordinary karaoke complement",
                self._bundled_projection("mdx:mbr_bve_gonzaluigi"),
                "Instrumental with Backing Vocals / Lead Vocals",
                "UI: Instrumental with Backing Vocals / Lead Vocals",
            ),
            (
                "non-default derived logical primary",
                self._bundled_projection("mdx:bs_karaoke_3stem_giantailab"),
                (
                    "Instrumental with Backing Vocals "
                    "(available derived output; not selected by default), "
                    "Lead Vocals, Backing Vocals, Instrumental"
                ),
                (
                    "UI: Instrumental with Backing Vocals "
                    "(available derived output; not selected by default) / "
                    "Lead Vocals / Backing Vocals / Instrumental"
                ),
            ),
            (
                "derived drum bass logical primary",
                self._bundled_projection("mdx:model_bs_roformer_ep_937_sdr_10.5309"),
                "Drum/Bass (complement of Drum/Bass Removed)",
                "UI: Drum/Bass / Drum/Bass Removed",
            ),
            (
                "reviewed dual pair",
                self._bundled_projection("mdx:UVR_MDXNET_Main"),
                "Vocals or Instrumental — both are first-class 2-stem exports",
                "UI: Vocals / Instrumental (either stem is a valid primary export)",
            ),
            (
                "ordinary multi-stem",
                self._bundled_projection("demucs:demucs"),
                "Multi-stem: Vocals, Drums, Bass, Residual",
                "UI: Vocals / Drums / Bass / Residual subset",
            ),
            (
                "explicit logical secondary",
                self._explicit_secondary_projection(),
                "Center, Drums, Side, Backing Vocals (available output; not selected by default)",
                (
                    "UI: Center / Drums / Side / "
                    "Backing Vocals (available output; not selected by default) subset"
                ),
            ),
            (
                "reviewed pair semantic secondary",
                self._pair_secondary_projection(),
                "Center, Side, Drums",
                "UI: Center / Side / Drums subset",
            ),
        )

        for label, projection, best_result, ui_export_note in cases:
            with self.subTest(label):
                self.assertEqual(projection.best_result, best_result)
                self.assertEqual(projection.ui_export_note, ui_export_note)

    def test_raw_result_prose_remains_unchanged(self) -> None:
        from core.model_stem_manifest import load_bundled_stem_semantics

        cases = (
            (
                catalogue.ModelEntry(
                    source="fixture",
                    family="VR Architecture",
                    catalogue_label="vr:private_result_order",
                    weight_file="private_result_order.pth",
                    instruments=["vocals", "instrumental"],
                    name_intent="vocals",
                    best_result="Guessed vocals first",
                    ui_export_note="UI: guessed vocals / instrumental",
                ),
                "Guessed vocals first",
                "UI: guessed vocals / instrumental",
            ),
        )

        for entry, best_result, ui_export_note in cases:
            with self.subTest(entry.catalogue_label):
                catalogue.reconcile_stem_semantics(
                    [entry],
                    registry=load_bundled_stem_semantics(),
                )
                semantics = cast(catalogue.ReconciledStemEvidence, entry.stem_semantics)
                self.assertFalse(semantics.reviewed)
                self.assertEqual(entry.best_result, best_result)
                self.assertEqual(entry.ui_export_note, ui_export_note)

    def _entries(self) -> list[catalogue.ModelEntry]:
        from core.model_stem_manifest import load_bundled_stem_semantics

        entries = [
            catalogue.ModelEntry(
                source="mvsepless",
                family="MDX-Net",
                catalogue_label="BS Roformer Drums Duality by Gilliaaan",
                weight_file="bs_drums_gilliaaan.ckpt",
                config_yaml="bs_drums_gilliaaan_config.yaml",
                instruments=["drums", "other"],
                primary_stem="drums",
                stem_count=2,
                name_intent="dual_voc_inst",
                backend_focus="two_stem",
                best_result="User picks Vocals or Instrumental (dual 2-stem)",
                ui_export_note=(
                    "UI: Vocals / Instrumental (either stem is a valid primary export)"
                ),
                metadata_source="bundled_yaml:bs_drums_gilliaaan_config.yaml",
            ),
            catalogue.ModelEntry(
                source="Politrees",
                family="Roformer",
                catalogue_label=(
                    "Roformer Model: MelBand Roformer | Bleed Suppressor v1 by Unwa & 97chris"
                ),
                weight_file="mel_band_roformer_bleed_suppressor_v1.ckpt",
                config_yaml="config_melband_roformer_bleed_suppressor_v1.yaml",
                instruments=["Instrumental", "Bleed"],
                primary_stem="Instrumental",
                target_instrument="Instrumental",
                stem_count=2,
                name_intent="instrumental",
                backend_focus="instrumental_target",
                best_result="Instrumental (complement = Vocals)",
                ui_export_note="UI: Instrumental / Vocals",
                metadata_source=("bundled_yaml:config_melband_roformer_bleed_suppressor_v1.yaml"),
            ),
        ]

        catalogue.reconcile_stem_semantics(
            entries,
            registry=load_bundled_stem_semantics(),
        )
        return entries

    def test_markdown_uses_exact_reviewed_route_prose(self) -> None:
        rendered = render._render(self._entries())

        self.assertIn("- **Name intent:** specialty_stem", rendered)
        self.assertIn("- **Best result:** Drums, Drums Removed", rendered)
        self.assertIn("- **Save stems UI:** UI: Drums / Drums Removed subset", rendered)
        self.assertIn("- **Name intent:** special_fx", rendered)
        self.assertIn("- **Best result:** Instrumental (+ Bleed complement)", rendered)
        self.assertIn("- **Save stems UI:** UI: Instrumental / Bleed", rendered)
        self.assertNotIn("User picks Vocals or Instrumental", rendered)
        self.assertNotIn("Instrumental (complement = Vocals)", rendered)

    def test_ir_uses_exact_reviewed_route_prose(self) -> None:
        ir = catalogue.build_ir(self._entries(), report=None, unsupported_count=0)
        by_weight = {entry["weight_file"]: entry for entry in ir["entries"]}

        drums = by_weight["bs_drums_gilliaaan.ckpt"]
        self.assertEqual(drums["name_intent"], "specialty_stem")
        self.assertEqual(drums["best_result"], "Drums, Drums Removed")
        self.assertEqual(drums["ui_export_note"], "UI: Drums / Drums Removed subset")

        bleed = by_weight["mel_band_roformer_bleed_suppressor_v1.ckpt"]
        self.assertEqual(bleed["name_intent"], "special_fx")
        self.assertEqual(bleed["best_result"], "Instrumental (+ Bleed complement)")
        self.assertEqual(bleed["ui_export_note"], "UI: Instrumental / Bleed")


class UiNoteTests(unittest.TestCase):
    def test_vocals_other_note_only_for_two_stem_models(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="MelBand Roformer Kim | Inst v1 by Unwa",
            weight_file="model.ckpt",
            instruments=["other", "vocals"],
            stem_count=2,
        )
        self.assertIn("Vocals / Instrumental", catalogue._ui_note(entry))

    def test_four_stem_vocals_other_uses_subset_row_note(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="4-stems SCNet Large",
            weight_file="model.ckpt",
            instruments=["Drums", "Bass", "Other", "Vocals"],
            stem_count=4,
            name_intent="multi_stem",
        )
        self.assertEqual(catalogue._ui_note(entry), "UI: per-stem subset or focus row")

    def test_special_fx_best_result_and_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="VR Architecture",
            catalogue_label="UVR-DeNoise by FoxJoy",
            weight_file="UVR-DeNoise.pth",
            primary_stem="noise",
            name_intent="special_fx",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertIn("Noise", entry.best_result)
        self.assertTrue(entry.backend_focus.startswith("special_fx_primary:"))
        self.assertIn("complement", entry.ui_export_note)

    def test_karaoke_2_gets_karaoke_backend_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="MDX-Net ONNX",
            catalogue_label="MDX-Net Model: UVR-MDX-NET Karaoke 2",
            weight_file="UVR_MDXNET_KARA_2.onnx",
            primary_stem="Instrumental",
            name_intent="karaoke",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertTrue(entry.is_karaoke)
        self.assertEqual(entry.backend_focus, "karaoke_instrumental_primary")

    def test_specialty_stem_flags_old_vocals_mismatch(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="BandSplit Roformer | Male-Female by aufr33",
            weight_file="model.ckpt",
            instruments=["male", "female"],
            primary_stem="male",
            name_intent="vocals",
            backend_focus="two_stem",
            metadata_source="remote_yaml:test.yaml",
        )
        flags = catalogue._flag_mismatches(entry)
        self.assertTrue(any("specialty 2-stem" in flag for flag in flags))


class SourceForTests(unittest.TestCase):
    def test_mdx23c_download_list_counts_as_trvlvr(self) -> None:
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", None, trvlvr), "TRvlvr")

    def test_mdx23c_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_mdx23c_in_both_is_combined(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, trvlvr), "TRvlvr+Politrees")

    def test_unattributed_label_is_unknown_not_trvlvr(self) -> None:
        """No membership anywhere is 'not proven', not positive provenance."""
        self.assertEqual(catalogue._source_for("Unknown Model", None, {}), "unknown")

    def test_failed_upstream_payload_does_not_attribute_everything_to_trvlvr(self) -> None:
        """A source that failed to load yields {}, which must not read as TRvlvr.

        _source_payload returns {} when a source has no content, so under a cold
        cache every label would otherwise be stamped with positive TRvlvr
        provenance on the strength of a failed membership check.
        """
        politrees = {"mdx23c_download_list": {"In Politrees": "a.ckpt"}}
        self.assertEqual(catalogue._source_for("In Politrees", politrees, {}), "Politrees")
        self.assertEqual(catalogue._source_for("In Nothing", politrees, {}), "unknown")

    def test_mdx23_download_list_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_scnet_in_upstream_counts_as_trvlvr(self) -> None:
        trvlvr = {"scnet_download_list": {"SCnet: Huge": {"huge.ckpt": "https://u/huge.ckpt"}}}
        politrees = {"scnet_download_list": {"SCnet: Huge": {"huge.ckpt": "https://p/huge.ckpt"}}}
        self.assertEqual(
            catalogue._source_for("SCnet: Huge", politrees, trvlvr), "TRvlvr+Politrees"
        )

    def test_extras_only_is_extras(self) -> None:
        extras = {
            "roformer_download_list": {
                "Roformer Model: BandSplit Roformer | HyperACE": {
                    "bs_hyperace.ckpt": "https://u/bs_hyperace.ckpt"
                }
            }
        }
        self.assertEqual(
            catalogue._source_for("Roformer Model: BandSplit Roformer | HyperACE", extras=extras),
            "extras",
        )

    def test_apollo_in_extras_is_extras(self) -> None:
        extras = {
            "apollo_download_list": {
                "Apollo Model: EDM Restoration by essid": {
                    "apollo_edm_by_essid.ckpt": "https://u/apollo.ckpt"
                }
            }
        }
        self.assertEqual(
            catalogue._source_for("Apollo Model: EDM Restoration by essid", extras=extras),
            "extras",
        )

    def test_mvsepless_only_is_mvsepless(self) -> None:
        mvsepless = {
            "mdx_download_list": {"MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}}
        }
        self.assertEqual(
            catalogue._source_for("MelBand Roformer Karaoke", mvsepless=mvsepless),
            "mvsepless",
        )

    def test_upstream_and_extras_combine_in_merge_order(self) -> None:
        trvlvr = {"mdx_download_list": {"Shared": "shared.onnx"}}
        extras = {"mdx_download_list": {"Shared": {"shared.onnx": "https://u/shared.onnx"}}}
        self.assertEqual(
            catalogue._source_for("Shared", None, trvlvr, extras=extras),
            "TRvlvr+extras",
        )


def _local(source_id: SourceId, payload: dict):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, local_loader=lambda: payload)


def _disabled(source_id: SourceId):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, enabled=lambda: False)


class CollectEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator
        from core.catalogue_types import SourceId

        extras = {
            "roformer_download_list": {
                "Roformer Model: BandSplit Roformer | HyperACE": {
                    "bs_hyperace.ckpt": "https://u/bs_hyperace.ckpt"
                }
            },
            "apollo_download_list": {
                "Apollo Model: EDM Restoration by essid": {
                    "apollo_edm_by_essid.ckpt": "https://u/apollo.ckpt"
                }
            },
        }
        mvsepless = {
            "mdx_download_list": {"MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}}
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(
                    SourceId.UPSTREAM,
                    {
                        "vr_download_list": {},
                        "mdx_download_list": {},
                        "demucs_download_list": {},
                    },
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _local(SourceId.EXTRAS, extras),
                SourceId.MVSEPLESS: _local(SourceId.MVSEPLESS, mvsepless),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def test_collect_entries_uses_coordinator_sources(self) -> None:
        ctx = catalogue.CatalogueContext()
        _snapshot, entries = catalogue.collect_entries(
            ctx, allow_network=False, coordinator=self._coordinator()
        )
        by_label = {entry.catalogue_label: entry for entry in entries}
        hyperace = by_label["Roformer Model: BandSplit Roformer | HyperACE"]
        self.assertEqual(hyperace.source, "extras")
        self.assertEqual(hyperace.family, "Roformer")
        apollo = by_label["Apollo Model: EDM Restoration by essid"]
        self.assertEqual(apollo.source, "extras")
        self.assertEqual(apollo.family, "Apollo")
        karaoke = by_label["MelBand Roformer Karaoke"]
        self.assertEqual(karaoke.source, "mvsepless")


class CompactTrvlvrEvidenceTests(unittest.TestCase):
    _ROWS = (
        (
            "mdx:MDX23C-8KFFT-InstVoc_HQ",
            "mdx23c_download_list",
            "MDX23C Model: MDX23C-InstVoc HQ",
            "MDX23C-8KFFT-InstVoc_HQ.ckpt",
            "model_2_stem_full_band_8k.yaml",
            "",
            ("Vocals", "Instrumental"),
            "",
            "Vocals",
            ("Vocals", "Instrumental"),
            "451765e869b78dcb9ca9188a74da31f581b7254ff0e8b532aa76b974148de947",
        ),
        (
            "mdx:MDX23C-8KFFT-InstVoc_HQ_2",
            "mdx23c_download_vip_list",
            "MDX23C Model VIP: MDX23C-InstVoc HQ 2",
            "MDX23C-8KFFT-InstVoc_HQ_2.ckpt",
            "model_2_stem_full_band_8k.yaml",
            "",
            ("Vocals", "Instrumental"),
            "",
            "Vocals",
            ("Vocals", "Instrumental"),
            "451765e869b78dcb9ca9188a74da31f581b7254ff0e8b532aa76b974148de947",
        ),
        (
            "mdx:melband_roformer_inst_v1",
            "roformer_download_list",
            "Roformer Model: MelBand Roformer Kim | Inst V1 by Unwa",
            "melband_roformer_inst_v1.ckpt",
            "config_melbandroformer_inst.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_inst.yaml",
            ("Instrumental", "Vocals"),
            "Instrumental",
            "Instrumental",
            ("Instrumental",),
            "723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
        ),
        (
            "mdx:melband_roformer_inst_v2",
            "roformer_download_list",
            "Roformer Model: MelBand Roformer Kim | Inst V2 by Unwa",
            "melband_roformer_inst_v2.ckpt",
            "config_melbandroformer_inst_v2.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_inst_v2.yaml",
            ("Instrumental", "Vocals"),
            "Instrumental",
            "Instrumental",
            ("Instrumental",),
            "4b902a7360a930c178edb4846b30e4e326aa1219d1b2daf660d46a311e0cd50b",
        ),
        (
            "mdx:melband_roformer_instvoc_duality_v1",
            "roformer_download_list",
            "Roformer Model: MelBand Roformer Kim | InstVoc Duality V1 by Unwa",
            "melband_roformer_instvoc_duality_v1.ckpt",
            "config_melbandroformer_instvoc_duality.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_instvoc_duality.yaml",
            ("Vocals", "Instrumental"),
            "",
            "Vocals",
            ("Vocals", "Instrumental"),
            "62dbc3ecf29c7ac99df35003f8cb72da3348d646cb5e6d50e07323551c3d968f",
        ),
        (
            "mdx:melband_roformer_instvox_duality_v2",
            "roformer_download_list",
            "Roformer Model: MelBand Roformer Kim | InstVoc Duality V2 by Unwa",
            "melband_roformer_instvox_duality_v2.ckpt",
            "config_melbandroformer_instvoc_duality.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_instvoc_duality.yaml",
            ("Vocals", "Instrumental"),
            "",
            "Vocals",
            ("Vocals", "Instrumental"),
            "62dbc3ecf29c7ac99df35003f8cb72da3348d646cb5e6d50e07323551c3d968f",
        ),
        (
            "mdx:model_bs_roformer_ep_317_sdr_12.9755",
            "roformer_download_list",
            "Roformer Model: BS-Roformer-Viperx-1297",
            "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "model_bs_roformer_ep_317_sdr_12.9755.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_317_sdr_12.9755.yaml",
            ("Vocals", "Instrumental"),
            "Vocals",
            "Vocals",
            ("Vocals",),
            "2bfdd16c656bd9519aba757cc4f8834b7ede675eb1e00ec4772d74ae1c41af7f",
        ),
        (
            "mdx:model_bs_roformer_ep_368_sdr_12.9628",
            "roformer_download_list",
            "Roformer Model: BS-Roformer-Viperx-1296",
            "model_bs_roformer_ep_368_sdr_12.9628.ckpt",
            "model_bs_roformer_ep_368_sdr_12.9628.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_368_sdr_12.9628.yaml",
            ("Vocals", "Instrumental"),
            "Vocals",
            "Vocals",
            ("Vocals",),
            "aea599b3f9bd4892a9c6bf5ac7c44787d3c99f717903d16054702665d477c86b",
        ),
        (
            "mdx:model_bs_roformer_ep_937_sdr_10.5309",
            "roformer_download_list",
            "Roformer Model: BS-Roformer-Viperx-1053",
            "model_bs_roformer_ep_937_sdr_10.5309.ckpt",
            "model_bs_roformer_ep_937_sdr_10.5309.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_937_sdr_10.5309.yaml",
            ("No Drum-Bass", "Drum-Bass"),
            "No Drum-Bass",
            "No Drum-Bass",
            ("No Drum-Bass",),
            "302b6cee54adf39743b097b145ad4f64c37f3bd31b84791da32f963fb3692d04",
        ),
        (
            "mdx:model_mel_band_roformer_ep_3005_sdr_11.4360",
            "roformer_download_list",
            "Roformer Model: Mel-Roformer-Viperx-1143",
            "model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt",
            "model_mel_band_roformer_ep_3005_sdr_11.4360.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_mel_band_roformer_ep_3005_sdr_11.4360.yaml",
            ("Vocals", "Instrumental"),
            "Vocals",
            "Vocals",
            ("Vocals",),
            "d9b083b48dfdd0bd10f8a29a9c18777b0419496d938827f48a1db31bf0193aa3",
        ),
    )

    def setUp(self) -> None:
        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator

        upstream: dict[str, dict[str, object]] = {
            "vr_download_list": {},
            "demucs_download_list": {},
        }
        other_network: dict[str, object] = {}
        for (
            _model_id,
            list_key,
            label,
            checkpoint,
            config,
            config_url,
            _instruments,
            _target,
            _primary,
            _signature,
            _sha256,
        ) in self._ROWS:
            upstream.setdefault(list_key, {})[label] = {checkpoint: config}
            if config_url:
                other_network[label] = {
                    checkpoint: f"https://weights.test/{checkpoint}",
                    config: config_url,
                }
        upstream["other_network_list"] = other_network
        inst_v1 = self._ROWS[2]
        inst_v2 = self._ROWS[3]
        politrees = {
            "roformer_download_list": {
                "Later rejected Inst V1 alias": {
                    inst_v1[3]: f"https://later.test/{inst_v1[3]}",
                    "config_melband_roformer_inst.yaml": (
                        "https://later.test/config_melband_roformer_inst.yaml"
                    ),
                },
                inst_v2[2]: {
                    inst_v2[3]: f"https://later.test/{inst_v2[3]}",
                    "config_melband_roformer_inst_v2.yaml": (
                        "https://later.test/config_melband_roformer_inst_v2.yaml"
                    ),
                },
            }
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(SourceId.UPSTREAM, upstream),
                SourceId.POLITREES: _local(SourceId.POLITREES, politrees),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def test_all_ten_compact_ids_reconcile_from_exact_current_evidence(self) -> None:
        from core.model_stem_manifest import load_bundled_stem_semantics

        expected_by_config = {row[4]: row for row in self._ROWS}

        def load_yaml(
            yaml_name: str,
            yaml_url: str = "",
            *,
            policy: object,
        ) -> tuple[list[str], str, str, str, str]:
            del policy
            row = expected_by_config[yaml_name]
            self.assertEqual(yaml_url, row[5])
            metadata_source = (
                f"remote_yaml:{yaml_name}" if yaml_url else f"bundled_yaml:{yaml_name}"
            )
            return list(row[6]), row[7], "Roformer", metadata_source, row[10]

        ctx = catalogue.CatalogueContext()
        registry = load_bundled_stem_semantics()
        coordinator = self._coordinator()
        with mock.patch.object(catalogue, "_load_yaml_meta", side_effect=load_yaml):
            snapshot, entries = catalogue.collect_entries(
                ctx,
                allow_network=False,
                coordinator=coordinator,
                registry=registry,
            )

        expected_ids = {row[0] for row in self._ROWS}
        by_id = {
            model_id: entry
            for entry in entries
            if (model_id := catalogue.catalogue_projection(entry)[0]) in expected_ids
        }
        self.assertEqual(set(by_id), expected_ids)
        for row in self._ROWS:
            with self.subTest(model_id=row[0]):
                entry = by_id[row[0]]
                self.assertEqual(entry.weight_file, row[3])
                self.assertEqual(entry.config_yaml, row[4])
                self.assertEqual(entry.config_url, row[5])
                self.assertEqual(tuple(entry.instruments), row[6])
                self.assertEqual(entry.target_instrument, row[7])
                self.assertEqual(entry.primary_stem, row[8])
                self.assertEqual(entry.config_sha256, row[10])
                self.assertIsNotNone(entry.stem_semantics)
                assert entry.stem_semantics is not None
                self.assertTrue(entry.stem_semantics.reviewed)
                self.assertEqual(entry.stem_semantics.native_signature, row[9])

        self.assertNotIn("Later rejected Inst V1 alias", snapshot.mdx)
        self.assertEqual(snapshot.mdx[self._ROWS[3][2]], {self._ROWS[3][3]: self._ROWS[3][4]})
        result = audit_catalogue_stems(list(by_id.values()), ctx, registry=registry)
        compact_contract_codes = {
            "context-unreviewed",
            "native-signature",
            "pair-context-incomplete",
            "reference-route-set",
        }
        affected = tuple(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code in compact_contract_codes
            and set(diagnostic.model_ids) & expected_ids
        )
        self.assertEqual(affected, ())

    def test_non_basename_scalar_is_not_config_evidence(self) -> None:
        from core.catalogue_coordinator import CatalogueCoordinator

        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(
                    SourceId.UPSTREAM,
                    {
                        "roformer_download_list": {
                            "Roformer Model: Nested": {"nested.ckpt": "configs/nested.yaml"}
                        }
                    },
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        with mock.patch.object(catalogue, "_load_yaml_meta") as load_yaml:
            _snapshot, entries = catalogue.collect_entries(
                catalogue.CatalogueContext(),
                allow_network=False,
                coordinator=coordinator,
            )

        self.assertEqual(entries[0].config_yaml, "")
        self.assertEqual(entries[0].config_url, "")
        load_yaml.assert_not_called()

    def test_mismatched_other_network_pair_does_not_supply_a_url(self) -> None:
        from core.catalogue_coordinator import CatalogueCoordinator

        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(
                    SourceId.UPSTREAM,
                    {
                        "roformer_download_list": {
                            "Roformer Model: Mismatch": {"mismatch.ckpt": "mismatch.yaml"}
                        },
                        "other_network_list": {
                            "Roformer Model: Mismatch": {
                                "different.ckpt": "https://weights.test/different.ckpt",
                                "mismatch.yaml": "https://configs.test/mismatch.yaml",
                            }
                        },
                    },
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)

        def load_yaml(
            yaml_name: str,
            yaml_url: str = "",
            *,
            policy: object,
        ) -> tuple[list[str], str, str, str, str]:
            del policy
            self.assertEqual(yaml_name, "mismatch.yaml")
            self.assertEqual(yaml_url, "")
            return [], "", "", "unavailable", ""

        with mock.patch.object(catalogue, "_load_yaml_meta", side_effect=load_yaml):
            snapshot, entries = catalogue.collect_entries(
                catalogue.CatalogueContext(),
                allow_network=False,
                coordinator=coordinator,
            )

        self.assertEqual(entries[0].config_yaml, "mismatch.yaml")
        self.assertEqual(entries[0].config_url, "")
        self.assertEqual(set(snapshot.mdx), {"Roformer Model: Mismatch"})


class OfflinePolicyTests(unittest.TestCase):
    """--offline must be cache-only: no fetch, no writes into model config storage."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-offline-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.calls: list = []

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator

        # An MDX-C entry with a remote yaml: the path that reaches _load_yaml_meta.
        upstream = {
            "vr_download_list": {},
            "mdx_download_list": {
                "MDX23C Model: Test": {
                    "model_test.ckpt": "https://example.invalid/model_test.ckpt",
                    "model_test.yaml": "https://example.invalid/model_test.yaml",
                }
            },
            "demucs_download_list": {},
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(SourceId.UPSTREAM, upstream),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def _patches(self):
        """Record every network entry point instead of raising.

        _fetch_cached swallows URLError/OSError, so a raising stub could be
        silently absorbed and the test would pass while the socket was opened.
        """
        from unittest import mock

        def record_urlopen(request: Any, *args: Any, **kwargs: Any):
            import urllib.error

            url = getattr(request, "full_url", request)
            self.calls.append(f"_urlopen({url})")
            # A URLError is what a real offline machine raises, and _fetch_cached
            # handles it; the recorded call list is what the assertions read.
            raise urllib.error.URLError("blocked by test")

        def record_fetch_config(name: Any, url: Any, *args: Any, **kwargs: Any) -> bool:
            self.calls.append(f"fetch_mdx_config_url({name}, {url})")
            return False

        return [
            mock.patch("core.mdx_config_fetch._urlopen", record_urlopen),
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", record_fetch_config),
            mock.patch.object(catalogue, "COMMUNITY_CACHE_DIR", os.path.join(self.tmp, "cm")),
            mock.patch.object(catalogue, "YAML_CACHE_DIR", os.path.join(self.tmp, "yaml")),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(self.tmp, "ref.tsv")),
            mock.patch.object(cli, "OUTPUT_PATH", os.path.join(self.tmp, "out.md")),
            mock.patch.object(
                cli,
                "DISPLAY_REFERENCE_TSV_PATH",
                os.path.join(self.tmp, "display.tsv"),
            ),
            mock.patch.object(
                cli,
                "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                os.path.join(self.tmp, "stem.tsv"),
            ),
            mock.patch.object(
                cli.stem_audit,
                "audit_catalogue_stems",
                side_effect=_clean_stem_audit,
            ),
        ]

    def test_build_catalogue_context_offline_makes_no_network_calls(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            catalogue._build_catalogue_context(allow_network=False)
        self.assertEqual(self.calls, [])

    def test_offline_cache_miss_does_not_create_the_cache_dir(self) -> None:
        """Offline is read-only: a miss must not leave an empty cache dir behind."""
        cache_dir = os.path.join(self.tmp, "cold")
        path = catalogue._fetch_cached(
            "https://example.invalid/x.json", cache_dir, "x.json", allow_network=False
        )
        self.assertIsNone(path)
        self.assertFalse(os.path.exists(cache_dir), "offline miss created a cache dir")

    def test_load_yaml_meta_offline_does_not_fetch_or_write_config(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            result = catalogue._load_yaml_meta(
                "model_test.yaml",
                "https://example.invalid/model_test.yaml",
                allow_network=False,
            )
        self.assertEqual(self.calls, [])
        # Falls back to the name heuristic rather than fetching.
        self.assertIsInstance(result, tuple)

    def test_main_offline_degrades_without_supplemental_evidence(self) -> None:
        import contextlib
        from unittest import mock

        coordinator = self._coordinator()
        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            real = catalogue._snapshot_and_payloads
            seen = {}

            def spy(*, allow_network: bool, coordinator: Any = None, **kwargs: Any):
                seen["allow_network"] = allow_network
                return real(allow_network=allow_network, coordinator=self._co, **kwargs)

            self._co = coordinator
            stack.enter_context(mock.patch.object(catalogue, "_snapshot_and_payloads", spy))
            rc = cli.main(["--offline"])

        self.assertEqual(rc, 2)
        self.assertIs(seen["allow_network"], False)
        self.assertEqual(self.calls, [])

    def test_online_still_fetches(self) -> None:
        """The offline guard must not disable networking for normal runs."""
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            catalogue._build_catalogue_context(allow_network=True)
        self.assertTrue(self.calls, "online mode should still attempt fetches")


class CommunitySupplementAvailabilityTests(unittest.TestCase):
    """Malformed community evidence must not look like a valid empty source."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-community-evidence-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _context_from_cached_community_bytes(self, data: bytes) -> catalogue.CatalogueContext:
        from unittest import mock

        cache_dir = os.path.join(self.tmp, "cached-community")
        cache_path = catalogue._cache_path(
            cache_dir,
            catalogue._COMMUNITY_MODELS_URL,
            "models.txt",
        )
        os.makedirs(cache_dir)
        with open(cache_path, "wb") as handle:
            handle.write(data)
        with mock.patch.object(catalogue, "COMMUNITY_CACHE_DIR", cache_dir):
            return catalogue._build_catalogue_context(
                policy=catalogue.FetchPolicy(allow_network=False)
            )

    def _context_from_fetched_community_bytes(self, data: bytes) -> catalogue.CatalogueContext:
        from unittest import mock

        class _Response:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def read(self) -> bytes:
                return self.payload

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        def urlopen(url: object) -> _Response:
            if str(url) == catalogue._COMMUNITY_MODELS_URL:
                return _Response(data)
            return _Response(b"{}")

        with (
            mock.patch.object(
                catalogue,
                "COMMUNITY_CACHE_DIR",
                os.path.join(self.tmp, "fetched-community"),
            ),
            mock.patch("core.mdx_config_fetch._urlopen", side_effect=urlopen),
        ):
            return catalogue._build_catalogue_context(
                policy=catalogue.FetchPolicy(allow_cache_writes=False)
            )

    def test_valid_empty_community_bytes_remain_available_from_cache(self) -> None:
        self.assertEqual(catalogue._parse_community_models_bytes(b""), ({}, True))

        context = self._context_from_cached_community_bytes(b"")
        self.assertEqual(context.community_by_file, {})
        self.assertNotIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

    def test_supported_rows_survive_well_formed_demucs_yaml_rows(self) -> None:
        payload = (
            b"fixture.ckpt  MDX  vocals*, other  Fixture Model\n"
            b"htdemucs.yaml  Demucs  vocals, drums, bass, other  htdemucs\n"
        )
        refs, available = catalogue._parse_community_models_bytes(payload)

        self.assertTrue(available)
        self.assertEqual(set(refs), {"fixture.ckpt"})
        self.assertEqual(refs["fixture.ckpt"].friendly_name, "Fixture Model")
        context = self._context_from_cached_community_bytes(payload)
        self.assertNotIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

    def test_invalid_community_bytes_are_unavailable_from_cache(self) -> None:
        self.assertEqual(catalogue._parse_community_models_bytes(b"\xff"), ({}, False))

        context = self._context_from_cached_community_bytes(b"\xff")
        self.assertIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

    def test_malformed_community_text_is_unavailable_from_cache(self) -> None:
        malformed = b"this is not a models.txt row\n"
        self.assertEqual(catalogue._parse_community_models_bytes(malformed), ({}, False))

        context = self._context_from_cached_community_bytes(malformed)
        self.assertIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

    def test_invalid_in_memory_community_bytes_degrade_publication(self) -> None:
        import tempfile
        from unittest import mock

        context = self._context_from_fetched_community_bytes(b"\xff")
        self.assertIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

        class _Snapshot:
            unsupported: dict[str, object] = {}
            report = None

        entry = catalogue.ModelEntry(
            source="fixture",
            family="MDX23C",
            catalogue_label="Fixture",
            weight_file="fixture.ckpt",
            metadata_source="fixture",
        )
        with tempfile.TemporaryDirectory(prefix="uvr-community-degraded-") as output_dir:
            with (
                mock.patch.object(cli, "OUTPUT_PATH", os.path.join(output_dir, "catalogue.md")),
                mock.patch.object(
                    cli, "REFERENCE_TSV_PATH", os.path.join(output_dir, "intent.tsv")
                ),
                mock.patch.object(
                    cli,
                    "DISPLAY_REFERENCE_TSV_PATH",
                    os.path.join(output_dir, "display.tsv"),
                ),
                mock.patch.object(
                    cli,
                    "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                    os.path.join(output_dir, "stem.tsv"),
                ),
                mock.patch.object(catalogue, "_build_catalogue_context", return_value=context),
                mock.patch.object(
                    catalogue, "collect_entries", return_value=(_Snapshot(), [entry])
                ),
                mock.patch.object(
                    cli.stem_audit,
                    "audit_catalogue_stems",
                    side_effect=_clean_stem_audit,
                ),
            ):
                self.assertEqual(cli.main([]), 2)


class DemucsFinalizationTests(unittest.TestCase):
    """Demucs family facts must land before the single finalization pass.

    The overlay used to run *after* _finalize_entry, so ui_export_note and
    flags were derived from an entry with no instruments and no stem count.
    """

    class _Snapshot:
        def __init__(self, demucs: dict) -> None:
            self.vr: dict = {}
            self.mdx: dict = {}
            self.demucs = demucs
            self.apollo: dict = {}
            self.meta: dict = {}
            self.unsupported: dict = {}

    def _entry(self, label: str, weight: str):
        snapshot = self._Snapshot({label: weight})
        entries = catalogue._entries_from_snapshot(
            snapshot,
            ({}, {}, {}, {}),
            catalogue.CatalogueContext(),
            policy=catalogue.OFFLINE_FETCH_POLICY,
        )
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_six_stem_demucs_gets_its_export_note(self) -> None:
        entry = self._entry("Demucs v4: htdemucs_6s", "htdemucs_6s.th")
        self.assertEqual(entry.stem_count, 6)
        self.assertEqual(entry.ui_export_note, "UI: per-stem subset or focus row")

    def test_four_stem_demucs_gets_its_export_note(self) -> None:
        entry = self._entry("Demucs v4: htdemucs", "htdemucs.th")
        self.assertEqual(entry.stem_count, 4)
        self.assertEqual(entry.ui_export_note, "UI: per-stem subset or focus row")

    def test_two_stem_uvr_demucs_is_not_labelled_multi_stem(self) -> None:
        """The UVR Demucs model emits vocals+instrumental, not a multi-stem set."""
        entry = self._entry("Demucs v3: UVR Model", "UVR_Demucs_Model_1.th")
        self.assertEqual(entry.stem_count, 2)
        self.assertEqual(entry.backend_focus, "two_stem")

    def test_family_specific_best_result_prose_is_preserved(self) -> None:
        self.assertEqual(self._entry("Demucs v4: htdemucs_6s", "a.th").best_result, "6-stem Demucs")
        self.assertEqual(self._entry("Demucs v4: htdemucs", "b.th").best_result, "4-stem Demucs")
        self.assertEqual(
            self._entry("Demucs v3: UVR Model", "c.th").best_result,
            "2-stem: instrumental + vocals (user picks focus)",
        )

    def test_metadata_source_records_the_heuristic(self) -> None:
        self.assertEqual(
            self._entry("Demucs v4: htdemucs", "b.th").metadata_source, "demucs_heuristic"
        )


class CacheIdentityTests(unittest.TestCase):
    """Ephemeral downloads: keyed by URL, TTL'd, and out of the docs tree."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-cache-id-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fetched: list = []

    def _opener(self, body: bytes = b'{"ok": 1}'):
        from unittest import mock

        def record(request: Any, *args: Any, **kwargs: Any):
            url = getattr(request, "full_url", request)
            self.fetched.append(url)

            class _R:
                def read(self) -> bytes:
                    return body

                def __enter__(self) -> "_R":
                    return self

                def __exit__(self, *exc: Any) -> bool:
                    return False

            return _R()

        return mock.patch("core.mdx_config_fetch._urlopen", record)

    def test_caches_live_under_cache_dir_not_the_docs_tree(self) -> None:
        from core import paths

        for cache_dir in (
            catalogue.YAML_CACHE_DIR,
            catalogue.COMMUNITY_CACHE_DIR,
        ):
            self.assertTrue(
                cache_dir.startswith(paths.CACHE_DIR),
                f"{cache_dir} is not under CACHE_DIR",
            )
            self.assertNotIn("docs", os.path.relpath(cache_dir, paths.CACHE_DIR))

    def test_same_basename_from_different_urls_does_not_alias(self) -> None:
        """Two models can both ship a 'config.yaml'."""
        with self._opener(b"first"):
            a = catalogue._fetch_cached("https://a.invalid/x/config.yaml", self.tmp, "config.yaml")
        with self._opener(b"second"):
            b = catalogue._fetch_cached("https://b.invalid/y/config.yaml", self.tmp, "config.yaml")
        self.assertNotEqual(a, b)
        assert a is not None and b is not None
        with open(a, "rb") as handle:
            self.assertEqual(handle.read(), b"first")
        with open(b, "rb") as handle:
            self.assertEqual(handle.read(), b"second")

    def test_yaml_fetch_accepts_compact_yml_extension(self) -> None:
        with mock.patch.object(
            catalogue,
            "_fetch_cached_bytes",
            return_value=(b"training: {}", "/cache/config.yml"),
        ) as fetch:
            result = catalogue._fetch_yaml_bytes(
                "https://example.test/config.yml",
                "config.yml",
            )

        self.assertEqual(result, (b"training: {}", "/cache/config.yml"))
        fetch.assert_called_once_with(
            "https://example.test/config.yml",
            catalogue.YAML_CACHE_DIR,
            "config.yml",
            policy=catalogue.DEFAULT_FETCH_POLICY,
        )

    def test_a_fresh_cache_entry_is_not_refetched(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            catalogue._fetch_cached(url, self.tmp, "data.json")
            catalogue._fetch_cached(url, self.tmp, "data.json")
        self.assertEqual(len(self.fetched), 1)

    def test_a_stale_cache_entry_is_refetched(self) -> None:
        """A normal online run must not reuse an arbitrarily old supplement."""
        url = "https://a.invalid/data.json"
        with self._opener():
            path = catalogue._fetch_cached(url, self.tmp, "data.json")
            assert path
            os.utime(path, (0, 0))  # epoch: far older than any TTL
            catalogue._fetch_cached(url, self.tmp, "data.json")
        self.assertEqual(len(self.fetched), 2)

    def test_stale_entry_is_still_served_when_offline(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            path = catalogue._fetch_cached(url, self.tmp, "data.json")
            assert path
            os.utime(path, (0, 0))
        with self._opener():
            served = catalogue._fetch_cached(url, self.tmp, "data.json", allow_network=False)
        self.assertEqual(served, path)
        self.assertEqual(len(self.fetched), 1)

    def test_refresh_refetches_even_a_fresh_entry(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            catalogue._fetch_cached(url, self.tmp, "data.json")
            catalogue._fetch_cached(url, self.tmp, "data.json", refresh=True)
        self.assertEqual(len(self.fetched), 2)

    def test_refresh_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(cli._parse_args(["--refresh"]).refresh)
        self.assertFalse(cli._parse_args([]).refresh)


class CoordinatorRefreshTests(unittest.TestCase):
    """--refresh must FORCE-reload membership, not only yaml / models.txt."""

    def _coordinator(self) -> Any:
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        empty = MagicMock()
        empty.state.content = None
        coordinator.source.return_value = empty
        snapshot = MagicMock(name="snapshot")
        coordinator.ensure.return_value = snapshot
        coordinator.snapshot.return_value = snapshot
        return coordinator

    def test_refresh_force_loads_coordinator_sources(self) -> None:
        from core.access_policy import AccessPolicy
        from core.catalogue_types import RefreshMode

        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(allow_network=True, refresh=True, coordinator=coordinator)
        coordinator.snapshot.assert_called_once_with(
            mode=RefreshMode.FORCE,
            policy=AccessPolicy(allow_network=True, allow_metadata_writes=True),
        )
        coordinator.ensure.assert_not_called()
        coordinator.refresh.assert_not_called()

    def test_default_snapshot_does_not_force_refresh(self) -> None:
        from core.access_policy import AccessPolicy

        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(allow_network=True, refresh=False, coordinator=coordinator)
        coordinator.refresh.assert_not_called()
        coordinator.snapshot.assert_not_called()
        coordinator.ensure.assert_called_once_with(
            allow_network=True,
            policy=AccessPolicy(allow_network=True, allow_metadata_writes=True),
        )

    def test_offline_never_force_refreshes_even_when_asked(self) -> None:
        from core.access_policy import AccessPolicy

        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(allow_network=False, refresh=True, coordinator=coordinator)
        coordinator.refresh.assert_not_called()
        coordinator.snapshot.assert_not_called()
        coordinator.ensure.assert_called_once_with(
            allow_network=False,
            policy=AccessPolicy(allow_network=False, allow_metadata_writes=True),
        )

    def test_collect_entries_forwards_refresh(self) -> None:
        from unittest.mock import MagicMock, patch

        seen: dict = {}

        def spy(
            *,
            allow_network: bool,
            coordinator: Any = None,
            refresh: bool = False,
            policy: Any = None,
        ) -> Any:
            seen["refresh"] = refresh
            seen["allow_network"] = allow_network
            seen["policy"] = policy
            return MagicMock(), ({}, {}, {}, {})

        with (
            patch.object(catalogue, "_snapshot_and_payloads", spy),
            patch.object(catalogue, "_entries_from_snapshot", return_value=[]),
        ):
            catalogue.collect_entries(
                catalogue.CatalogueContext(),
                policy=catalogue.FetchPolicy(refresh=True),
            )
        self.assertTrue(seen["refresh"])
        self.assertTrue(seen["allow_network"])
        self.assertTrue(seen["policy"].allow_cache_writes)

    def test_main_refresh_forwards_to_snapshot(self) -> None:
        import contextlib
        import tempfile
        from unittest import mock

        seen: dict = {}

        def spy(
            *,
            allow_network: bool,
            coordinator: Any = None,
            refresh: bool = False,
            policy: Any = None,
        ) -> Any:
            seen["refresh"] = refresh
            seen["policy"] = policy
            return mock.MagicMock(unsupported=None, report=None), ({}, {}, {}, {})

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.md")
            with (
                mock.patch.object(cli, "OUTPUT_PATH", out),
                mock.patch.object(
                    catalogue,
                    "_build_catalogue_context",
                    lambda **k: catalogue.CatalogueContext(),
                ),
                mock.patch.object(catalogue, "_snapshot_and_payloads", spy),
                mock.patch.object(
                    cli,
                    "_publication_verdict",
                    return_value=cli.PublicationVerdict(ok=True),
                ),
                contextlib.redirect_stdout(mock.MagicMock()),
            ):
                cli.main(["--refresh"])
        self.assertTrue(seen.get("refresh"))
        self.assertTrue(seen["policy"].allow_cache_writes)


class PublicationGuardTests(unittest.TestCase):
    """A degraded snapshot must not replace a good catalogue document."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-guard-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")

    def _report(self, *, usable: bool = True, failed: tuple = ()):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(mode=RefreshMode.OFFLINE, usable=usable, failed=failed)

    def test_previous_entry_count_is_read_from_an_existing_document(self) -> None:
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **412**\n")
        self.assertEqual(cli._previous_entry_count(self.out), 412)

    def test_missing_document_has_no_previous_count(self) -> None:
        self.assertIsNone(cli._previous_entry_count(self.out))

    def test_unusable_snapshot_is_refused(self) -> None:
        verdict = cli._publication_verdict(
            entries=[], report=self._report(usable=False), previous_count=None
        )
        self.assertFalse(verdict.ok)
        self.assertIn("unusable", verdict.reason.lower())

    def test_a_large_drop_is_refused_even_when_no_source_reported_failure(self) -> None:
        """The real cold-cache case: offline sources are not refreshed, not failed.

        A run against an empty supplemental cache produced 88 entries where the
        published document had 474, with report.usable True and report.failed
        empty -- so failure state cannot be the trigger. The count is.
        """
        verdict = cli._publication_verdict(
            entries=[object()] * 88, report=self._report(), previous_count=474
        )
        self.assertFalse(verdict.ok)
        self.assertIn("474", verdict.reason)

    def test_a_small_drop_still_publishes(self) -> None:
        """Ordinary regeneration jitter must not need an override flag."""
        verdict = cli._publication_verdict(
            entries=[object()] * 398, report=self._report(), previous_count=400
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_failed_sources_are_named_in_the_refusal(self) -> None:
        from core.catalogue_types import SourceId

        verdict = cli._publication_verdict(
            entries=[object()] * 10,
            report=self._report(failed=((SourceId.UPSTREAM, "boom"),)),
            previous_count=400,
        )
        self.assertFalse(verdict.ok)
        self.assertIn("upstream", verdict.reason)

    def test_a_healthy_snapshot_publishes(self) -> None:
        verdict = cli._publication_verdict(
            entries=[object()] * 400, report=self._report(), previous_count=400
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_allow_degraded_overrides_a_refusal(self) -> None:
        verdict = cli._publication_verdict(
            entries=[],
            report=self._report(usable=False),
            previous_count=400,
            allow_degraded=True,
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_allow_degraded_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(cli._parse_args(["--allow-degraded"]).allow_degraded)
        self.assertFalse(cli._parse_args([]).allow_degraded)


class OfflineYamlCacheTests(unittest.TestCase):
    """The URL-keyed yaml cache must actually be readable, including offline."""

    _YAML = "training:\n  instruments: [vocals, other]\n  target_instrument: other\n"
    _URL = "https://example.invalid/cfg/model_test.yaml"

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-yamlcache-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.calls: list = []

    def _patches(self):
        from unittest import mock

        def record(request: Any, *args: Any, **kwargs: Any):
            self.calls.append(getattr(request, "full_url", request))
            raise urllib.error.URLError("blocked")

        return [
            mock.patch.object(catalogue, "YAML_CACHE_DIR", self.tmp),
            mock.patch("core.mdx_config_fetch._urlopen", record),
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", lambda *a, **k: False),
        ]

    def _seed_cache(self) -> str:
        path = catalogue._cache_path(self.tmp, self._URL, "model_test.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._YAML)
        return path

    def test_yaml_paths_includes_the_url_keyed_cache_entry(self) -> None:
        from unittest import mock

        runtime_path = os.path.join(self.tmp, "runtime-configs", "model_test.yaml")
        with mock.patch.object(
            catalogue.paths,
            "MDX_C_CONFIG_PATH",
            os.path.dirname(runtime_path),
        ):
            candidates = catalogue._yaml_paths("model_test.yaml", self._URL)
        expected = catalogue._cache_path(catalogue.YAML_CACHE_DIR, self._URL, "model_test.yaml")
        self.assertIn(expected, candidates)
        self.assertNotIn(runtime_path, candidates)

    def test_offline_reads_a_previously_cached_yaml(self) -> None:
        """The whole point of a cache-only offline mode."""
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            cached = self._seed_cache()
            self.assertTrue(os.path.isfile(cached))
            instruments, target, _arch, source, _digest = catalogue._load_yaml_meta(
                "model_test.yaml", self._URL, policy=catalogue.OFFLINE_FETCH_POLICY
            )

        self.assertEqual(self.calls, [], "offline must not fetch")
        self.assertEqual(sorted(instruments), ["other", "vocals"])
        self.assertEqual(target, "other")
        self.assertTrue(source.startswith("remote_yaml:"), source)

    def test_offline_without_a_cached_yaml_falls_back_without_fetching(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            catalogue._load_yaml_meta(
                "model_test.yaml", self._URL, policy=catalogue.OFFLINE_FETCH_POLICY
            )
        self.assertEqual(self.calls, [])

    def test_unparseable_cached_yaml_is_not_strict_signature_evidence(self) -> None:
        import contextlib

        path = catalogue._cache_path(self.tmp, self._URL, "model_test.yaml")
        with open(path, "wb") as handle:
            handle.write(b"training: [unterminated")
        ctx = catalogue.CatalogueContext()

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            entry = catalogue._parse_catalogue_entry(
                source="fixture",
                family="Roformer",
                label="Roformer Model: Invalid YAML",
                payload={
                    "model.ckpt": "https://example.invalid/model.ckpt",
                    "model_test.yaml": self._URL,
                },
                ctx=ctx,
                policy=catalogue.OFFLINE_FETCH_POLICY,
            )[0]

        self.assertEqual(entry.instruments, [])
        self.assertEqual(entry.target_instrument, "")
        self.assertTrue(entry.metadata_source.startswith("yaml_parse_failed:"))
        self.assertEqual(ctx.unavailable_yaml_evidence, {"model_test.yaml"})


class StrictCatalogueInputIsolationTests(unittest.TestCase):
    """Strict publication inputs must not depend on installed runtime models."""

    _YAML_NAME = "zz_runtime_conflict.yaml"
    _YAML_URL = "https://example.invalid/configs/zz_runtime_conflict.yaml"
    _WEIGHT_NAME = "zz_runtime_conflict.ckpt"
    _WEIGHT_URL = "https://example.invalid/models/zz_runtime_conflict.ckpt"
    _WARM_YAML = (
        b"training:\n"
        b"  instruments: [vocals, other]\n"
        b"  target_instrument: vocals\n"
        b"model:\n"
        b"  num_bands: 64\n"
    )
    _CONFLICTING_YAML = (
        b"training:\n"
        b"  instruments: [drums, bass]\n"
        b"  target_instrument: drums\n"
        b"model:\n"
        b"  band_specs: {}\n"
    )

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-strict-inputs-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cache_root = os.path.join(self.tmp, "generator-cache")
        self.community_cache = os.path.join(self.cache_root, "community")
        self.yaml_cache = os.path.join(self.cache_root, "yaml")

    @staticmethod
    def _write(path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def _seed_cache(self) -> None:
        rows = (
            (
                self.community_cache,
                catalogue._COMMUNITY_MODELS_URL,
                "models.txt",
                b"",
            ),
            (self.yaml_cache, self._YAML_URL, self._YAML_NAME, self._WARM_YAML),
        )
        for cache_dir, url, filename, data in rows:
            self._write(catalogue._cache_path(cache_dir, url, filename), data)

    def _strict_projection(self, runtime_root: str) -> dict[str, object]:
        from dataclasses import asdict
        from unittest import mock

        runtime_configs = os.path.join(runtime_root, "configs")
        runtime_mdx_models = os.path.join(runtime_root, "mdx-models")
        runtime_vr_models = os.path.join(runtime_root, "vr-models")

        class _Snapshot:
            vr: dict[str, object] = {}
            mdx = {
                "Roformer Model: Strict Input Fixture": {
                    self._WEIGHT_NAME: self._WEIGHT_URL,
                    self._YAML_NAME: self._YAML_URL,
                }
            }
            demucs: dict[str, object] = {}
            apollo: dict[str, object] = {}
            meta: dict[str, object] = {}
            unsupported: dict[str, object] = {}
            report = None

        upstream = {
            "vr_download_list": {},
            "mdx_download_list": _Snapshot.mdx,
            "demucs_download_list": {},
        }
        from core.model_stem_manifest import BUNDLED_MANIFEST_PATH, load_stem_manifest

        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        with (
            mock.patch.object(catalogue, "COMMUNITY_CACHE_DIR", self.community_cache),
            mock.patch.object(catalogue, "YAML_CACHE_DIR", self.yaml_cache),
            mock.patch.object(catalogue.paths, "MDX_C_CONFIG_PATH", runtime_configs),
            mock.patch.object(
                catalogue.paths,
                "MDX_HASH_JSON",
                os.path.join(runtime_root, "mdx-model-data.json"),
            ),
            mock.patch.object(
                catalogue.paths,
                "VR_HASH_JSON",
                os.path.join(runtime_root, "vr-model-data.json"),
            ),
            mock.patch.object(catalogue.paths, "MDX_MODELS_DIR", runtime_mdx_models),
            mock.patch.object(catalogue.paths, "VR_MODELS_DIR", runtime_vr_models),
        ):
            ctx = catalogue._build_catalogue_context(policy=catalogue.OFFLINE_FETCH_POLICY)
            entries = catalogue._entries_from_snapshot(
                _Snapshot(),
                (upstream, {}, {}, {}),
                ctx,
                policy=catalogue.OFFLINE_FETCH_POLICY,
            )
            catalogue.reconcile_stem_semantics(entries, registry=registry)
            audit = cli.stem_audit.audit_catalogue_stems(
                entries,
                ctx,
                registry=registry,
            )
            catalogue_text = render._render(entries, unsupported_count=0, report=None)
            bundle = cli._render_publication_bundle(
                entries,
                ctx=ctx,
                unsupported=0,
                report=None,
                catalogue_text=catalogue_text,
                document_sha256=cli._text_digest(catalogue_text),
                audit=audit,
            )
        return {
            "entries": [asdict(entry) for entry in entries],
            "catalogue": bundle.catalogue,
            "intent_reference": bundle.intent_reference,
            "display_reference": asdict(bundle.display_reference),
            "stem_reference": bundle.stem_reference,
            "ir": cli._canonical_ir_for_diff(bundle.ir),
            "diagnostics": [asdict(diagnostic) for diagnostic in audit.diagnostics],
        }

    def test_warm_cache_is_identical_across_conflicting_runtime_data_dirs(self) -> None:
        """Installed same-name YAML/weights cannot alter strict output or diagnostics."""
        clean_runtime = os.path.join(self.tmp, "runtime-clean")
        conflicting_runtime = os.path.join(self.tmp, "runtime-conflicting")
        conflicting_weight = os.path.join(conflicting_runtime, "mdx-models", self._WEIGHT_NAME)
        self._write(conflicting_weight, b"runtime model bytes")
        self._seed_cache()
        self._write(
            os.path.join(conflicting_runtime, "configs", self._YAML_NAME),
            self._CONFLICTING_YAML,
        )
        before = {}
        for directory, _subdirs, names in os.walk(conflicting_runtime):
            for name in names:
                path = os.path.join(directory, name)
                with open(path, "rb") as handle:
                    before[os.path.relpath(path, conflicting_runtime)] = handle.read()

        clean = self._strict_projection(clean_runtime)
        conflicting = self._strict_projection(conflicting_runtime)

        self.assertEqual(clean, conflicting)
        after = {}
        for directory, _subdirs, names in os.walk(conflicting_runtime):
            for name in names:
                path = os.path.join(directory, name)
                with open(path, "rb") as handle:
                    after[os.path.relpath(path, conflicting_runtime)] = handle.read()
        self.assertEqual(before, after)

    def test_cold_offline_yaml_evidence_degrades_before_structural_audit(self) -> None:
        """A full membership snapshot without required YAML is unavailable, not invalid."""
        import contextlib
        import io
        from unittest import mock

        class _Snapshot:
            vr: dict[str, object] = {}
            mdx = {
                "Roformer Model: Cold YAML Fixture": {
                    self._WEIGHT_NAME: self._WEIGHT_URL,
                    self._YAML_NAME: self._YAML_URL,
                }
            }
            demucs: dict[str, object] = {}
            apollo: dict[str, object] = {}
            meta: dict[str, object] = {}
            unsupported: dict[str, object] = {}
            report = None

        upstream = {
            "vr_download_list": {},
            "mdx_download_list": _Snapshot.mdx,
            "demucs_download_list": {},
        }
        ctx = catalogue.CatalogueContext()
        stderr = io.StringIO()
        network_calls: list[str] = []
        invalid = StemAuditResult(
            catalogue_model_ids=("mdx:zz_runtime_conflict",),
            reviewed_model_ids=(),
            waived_model_ids=(),
            raw_model_ids=("mdx:zz_runtime_conflict",),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(
                StemAuditDiagnostic(
                    code="catalogue-unreviewed",
                    model_ids=("mdx:zz_runtime_conflict",),
                    message="missing guessed signature would create structural spam",
                ),
            ),
        )

        def record_network(target: object) -> None:
            network_calls.append(str(target))
            return None

        with (
            mock.patch.object(cli, "OUTPUT_PATH", os.path.join(self.tmp, "cold.md")),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(self.tmp, "cold.tsv")),
            mock.patch.object(
                cli,
                "DISPLAY_REFERENCE_TSV_PATH",
                os.path.join(self.tmp, "cold-display.tsv"),
            ),
            mock.patch.object(
                cli,
                "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                os.path.join(self.tmp, "cold-stems.tsv"),
            ),
            mock.patch.object(catalogue, "YAML_CACHE_DIR", os.path.join(self.tmp, "cold-yaml")),
            mock.patch.object(
                catalogue.paths,
                "MDX_C_CONFIG_PATH",
                os.path.join(self.tmp, "cold-runtime-configs"),
            ),
            mock.patch.object(catalogue, "_build_catalogue_context", return_value=ctx),
            mock.patch.object(
                catalogue,
                "_snapshot_and_payloads",
                return_value=(_Snapshot(), (upstream, {}, {}, {})),
            ),
            mock.patch("core.mdx_config_fetch._urlopen", side_effect=record_network),
            mock.patch.object(
                cli.stem_audit,
                "audit_catalogue_stems",
                return_value=invalid,
            ) as audit,
            contextlib.redirect_stderr(stderr),
        ):
            rc = cli.main(["--offline"])

        self.assertEqual(rc, 2)
        self.assertEqual(network_calls, [])
        audit.assert_not_called()
        self.assertNotIn("Stem audit", stderr.getvalue())
        self.assertIn(self._YAML_NAME, ctx.unavailable_yaml_evidence)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "cold-yaml")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "cold-runtime-configs")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "cold.md")))

    def test_refresh_replaces_generator_yaml_without_writing_runtime_storage(self) -> None:
        """Refresh owns only its URL-keyed cache, never the model config store."""
        from unittest import mock

        fresh_yaml = (
            b"training:\n"
            b"  instruments: [vocals, other]\n"
            b"  target_instrument: other\n"
            b"model:\n"
            b"  num_bands: 64\n"
        )
        cache_path = catalogue._cache_path(self.yaml_cache, self._YAML_URL, self._YAML_NAME)
        self._write(cache_path, self._CONFLICTING_YAML)
        runtime_path = os.path.join(self.tmp, "runtime-configs", self._YAML_NAME)
        self._write(runtime_path, self._CONFLICTING_YAML)

        class _Response:
            def read(self) -> bytes:
                return fresh_yaml

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        calls: list[object] = []

        def urlopen(target: object) -> _Response:
            calls.append(target)
            return _Response()

        policy = catalogue.FetchPolicy(allow_network=True, refresh=True)
        with (
            mock.patch.object(catalogue, "YAML_CACHE_DIR", self.yaml_cache),
            mock.patch.object(
                catalogue.paths,
                "MDX_C_CONFIG_PATH",
                os.path.dirname(runtime_path),
            ),
            mock.patch("core.mdx_config_fetch._urlopen", side_effect=urlopen),
        ):
            instruments, target, _arch, source, _digest = catalogue._load_yaml_meta(
                self._YAML_NAME,
                self._YAML_URL,
                policy=policy,
            )
            offline = catalogue._load_yaml_meta(
                self._YAML_NAME,
                self._YAML_URL,
                policy=catalogue.OFFLINE_FETCH_POLICY,
            )

        self.assertEqual(instruments, ["vocals", "other"])
        self.assertEqual(target, "other")
        self.assertEqual(source, f"remote_yaml:{self._YAML_NAME}")
        self.assertEqual(offline[:2], (instruments, target))
        self.assertEqual(offline[3], source)
        self.assertEqual(len(calls), 1)
        with open(cache_path, "rb") as handle:
            self.assertEqual(handle.read(), fresh_yaml)
        with open(runtime_path, "rb") as handle:
            self.assertEqual(handle.read(), self._CONFLICTING_YAML)


class CacheWriteAtomicityTests(unittest.TestCase):
    def test_a_failed_cache_write_does_not_leave_a_truncated_entry(self) -> None:
        """A truncated cache file would be re-served as valid for the whole TTL."""
        import shutil
        import tempfile
        from unittest import mock

        tmp = tempfile.mkdtemp(prefix="uvr-cache-atomic-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        url = "https://a.invalid/data.json"

        body = {"data": b'{"ok": 1}'}

        def opener(request: Any, *args: Any, **kwargs: Any):
            class _R:
                def read(self) -> bytes:
                    return body["data"]

                def __enter__(self) -> "_R":
                    return self

                def __exit__(self, *exc: Any) -> bool:
                    return False

            return _R()

        with mock.patch("core.mdx_config_fetch._urlopen", opener):
            good = catalogue._fetch_cached(url, tmp, "data.json")
            assert good is not None
            # Different bytes, so overwriting in place is distinguishable from
            # a staged write that never lands.
            body["data"] = b'{"ok": 2, "and": "much longer than the original"}'
            with mock.patch("os.replace", side_effect=OSError("disk full")):
                catalogue._fetch_cached(url, tmp, "data.json", refresh=True)

        with open(good, "rb") as handle:
            self.assertEqual(handle.read(), b'{"ok": 1}')
        self.assertEqual(os.listdir(tmp), [os.path.basename(good)])


class EntryMetaProvenanceTests(unittest.TestCase):
    """Metadata that came from the snapshot must not report as unavailable."""

    def test_entry_meta_supplied_metadata_is_recorded_as_its_source(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Roformer",
            weight_file="model.ckpt",
            name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(
            entry,
            EntryMeta(
                label="Some Roformer",
                display="Some Roformer",
                arch="Roformer",
                stems=["vocals", "other"],
                target_instrument="other",
            ),
        )
        self.assertNotEqual(entry.metadata_source, "unavailable")
        self.assertIn("catalogue_meta", entry.metadata_source)

    def test_entry_meta_that_adds_nothing_leaves_the_source_alone(self) -> None:
        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Roformer",
            weight_file="model.ckpt",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(entry, None)
        self.assertEqual(entry.metadata_source, "unavailable")


class SourceAttributionCostTests(unittest.TestCase):
    def test_mvsepless_conversion_is_not_repeated_per_label(self) -> None:
        """_source_for ran a full catalogue conversion once per label (~474x)."""
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(5)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        mvsepless = {"raw": {"needs": "conversion"}}
        with mock.patch(
            "core.mvsepless_catalog.convert_mvsepless_catalog", return_value={}
        ) as convert:
            catalogue._entries_from_snapshot(
                _Snapshot(),
                ({}, {}, {}, mvsepless),
                catalogue.CatalogueContext(),
                policy=catalogue.OFFLINE_FETCH_POLICY,
            )
        self.assertLessEqual(convert.call_count, 1, "converted once per label")


class ReferenceTsvOptInTests(unittest.TestCase):
    """The TSV is a deliberate output, not a side effect of running the command."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-tsv-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tsv = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.out = os.path.join(self.tmp, "models-catalogue.md")
        self.display = os.path.join(self.tmp, "model_display_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")

    def _community(self):
        return {
            "model.ckpt": catalogue.CommunityRef(
                filename="model.ckpt",
                arch="Roformer",
                primary_stem="Vocals",
                stems_text="vocals, other",
                friendly_name="Some Model",
                intent="vocals",
            )
        }

    def _run(self, argv: list, *, entries: int = 1) -> int:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(entries)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        ctx = catalogue.CatalogueContext(community_by_file=self._community())
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", self.tsv))
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.out))
            stack.enter_context(mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display))
            stack.enter_context(
                mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem)
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=_clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context", lambda **k: ctx)
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue,
                    "_snapshot_and_payloads",
                    lambda **k: (_Snapshot(), ({}, {}, {}, {})),
                )
            )
            return cli.main(argv)

    def test_a_default_run_writes_the_tsv(self) -> None:
        self.assertEqual(self._run([]), 0)
        self.assertTrue(os.path.isfile(self.out))
        self.assertTrue(os.path.isfile(self.tsv))

    def test_write_tsv_writes_it(self) -> None:
        self.assertEqual(self._run(["--write-tsv"]), 0)
        self.assertTrue(os.path.isfile(self.tsv))
        with open(self.tsv, encoding="utf-8") as handle:
            self.assertIn("model.ckpt", handle.read())

    def test_a_refused_run_does_not_write_the_tsv(self) -> None:
        """A run that refuses to publish must not mutate the other artifact either."""
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **400**\n")
        self.assertEqual(self._run(["--write-tsv"], entries=1), 2)
        self.assertFalse(os.path.exists(self.tsv), "refused run still wrote the TSV")

    def test_write_tsv_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(cli._parse_args(["--write-tsv"]).write_tsv)
        self.assertFalse(cli._parse_args([]).write_tsv)


class DisplayReferenceRenderTests(unittest.TestCase):
    """The presentation reference is deterministic data, not prose scraping."""

    def test_canonical_id_family_allowlist_covers_every_current_family(self) -> None:
        expected_prefixes = {
            "VR Architecture": "vr",
            "Demucs": "demucs",
            "Apollo": "apollo",
            "MDX-Net": "mdx",
            "MDX-Net ONNX": "mdx",
            "MDX23C": "mdx",
            "Roformer": "mdx",
            "SCNet": "mdx",
            "Bandit": "mdx",
        }

        for family, expected_prefix in expected_prefixes.items():
            with self.subTest(family=family):
                entry = catalogue.ModelEntry(
                    source="test",
                    family=family,
                    catalogue_label=f"{family}: Model",
                    weight_file="model.ckpt",
                )
                self.assertEqual(
                    render._canonical_model_id(entry),
                    f"{expected_prefix}:model",
                )

    def test_canonical_id_rejects_an_unknown_family_instead_of_minting_mdx(self) -> None:
        entry = catalogue.ModelEntry(
            source="test",
            family="MDXNet",
            catalogue_label="Misspelled MDX family",
            weight_file="model.ckpt",
        )

        with self.assertRaisesRegex(
            ValueError,
            "unsupported catalogue family 'MDXNet'.*Misspelled MDX family",
        ):
            render._canonical_model_id(entry)

    def test_renders_execution_source_display_and_quality_flags(self) -> None:
        entries = [
            catalogue.ModelEntry(
                source="TRvlvr",
                family="VR Architecture",
                catalogue_label="VR Arch Single Model v5: 5_HP-Karaoke-UVR",
                weight_file="5_HP-Karaoke-UVR.pth",
            ),
            catalogue.ModelEntry(
                source="mvsepless",
                family="SCNet",
                catalogue_label="SCnet: 4-stems Huge SCNet Bleedless by Aname",
                weight_file="huge_scnet_4stems_bleedless.ckpt",
                arch="SCNet",
            ),
        ]

        rendered = render.presentation_reference_tsv(entries)

        self.assertEqual(
            rendered.splitlines()[0],
            "family\texecution_arch\tsource\tcatalogue_generation\t"
            "catalogue_label\tcanonical_id\tcurrent_display\tweight_file\t"
            "presentation_flags\twaiver_reasons\treview_status",
        )
        self.assertIn(
            "VR Architecture\tVR Architecture\tTRvlvr\tv5\t"
            "VR Arch Single Model v5: 5_HP-Karaoke-UVR\t"
            "vr:5_HP-Karaoke-UVR\tVR v5 — HP Karaoke 5\t"
            "5_HP-Karaoke-UVR.pth\t\t"
            "\tclean",
            rendered,
        )
        self.assertIn(
            "SCNet\tSCNet\tmvsepless\t\t"
            "SCnet: 4-stems Huge SCNet Bleedless by Aname\t"
            "mdx:huge_scnet_4stems_bleedless\t"
            "SCNet — Huge Bleedless (4 Stems) · Aname\t"
            "huge_scnet_4stems_bleedless.ckpt\t\t\tclean",
            rendered,
        )

    def test_demucs_id_comes_from_the_runtime_primary_yaml(self) -> None:
        entry = catalogue.ModelEntry(
            source="TRvlvr",
            family="Demucs",
            catalogue_label="Demucs v4: htdemucs_ft",
            weight_file="f7e0c4bc-ba3fe64a.th",
            config_yaml="htdemucs_ft.yaml",
        )

        rendered = render.presentation_reference_tsv([entry])

        self.assertIn(
            "demucs:htdemucs_ft\tDemucs v4 — Hybrid Transformer Fine-Tuned\t",
            rendered,
        )

    def test_exact_manifest_waiver_marks_retained_flags_reviewed(self) -> None:
        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="MDX-Net",
            catalogue_label=("Mel-Band Roformer Instrumental by Becruily [mbr_inst_becruily]"),
            weight_file="mbr_inst_becruily.ckpt",
        )

        rendered = render.presentation_reference_tsv([entry])

        self.assertIn("underscore, embedded-id\tunderscore: ", rendered)
        self.assertTrue(rendered.rstrip().endswith("\treviewed"))
        self.assertIn("underscore: The underscore is part of the reviewed", rendered)
        self.assertIn("embedded-id: The bracketed exact backend ID", rendered)

    def test_repeated_family_flag_understands_normalized_stem_counts(self) -> None:
        entry = catalogue.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="SCnet: 4-stems SCNet Large",
            weight_file="scnet_large.ckpt",
        )

        self.assertIn(
            "repeated-family",
            render._presentation_flags(entry, "SCNet — (4 Stems) SCNet Large"),
        )

    def test_revision_quality_flags_detect_superseded_presentation_forms(self) -> None:
        entry = catalogue.ModelEntry(
            source="test",
            family="MDX-Net",
            catalogue_label="Model",
            weight_file="model.ckpt",
        )

        cases = {
            "MDX-Net — UVR Instrumental High Quality 4": "expanded-hq",
            "SCNet — (4 Stems) Huge Bleedless · Aname": "leading-stem-count",
            "MelBand Roformer — Xeno · DrYound3r (only weights)": ("operational-note"),
        }
        for display, flag in cases.items():
            with self.subTest(display=display):
                self.assertIn(flag, render._presentation_flags(entry, display))

    def test_sorts_rows_independently_of_collection_order(self) -> None:
        alpha = catalogue.ModelEntry(
            source="test",
            family="MDX-Net",
            catalogue_label="Alpha",
            weight_file="alpha.ckpt",
        )
        zulu = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="Zulu",
            weight_file="zulu.ckpt",
        )

        self.assertEqual(
            render.presentation_reference_tsv([zulu, alpha]),
            render.presentation_reference_tsv([alpha, zulu]),
        )

    def test_collision_detection_normalizes_unicode_and_case(self) -> None:
        composed = catalogue.ModelEntry(
            source="test",
            family="MDX-Net",
            catalogue_label="Caf\u00e9",
            weight_file="composed.ckpt",
        )
        decomposed = catalogue.ModelEntry(
            source="test",
            family="MDX-Net",
            catalogue_label="CAFE\u0301",
            weight_file="decomposed.ckpt",
        )

        audit = render.presentation_reference_audit([composed, decomposed])

        self.assertEqual(len(audit.collisions), 1)
        self.assertEqual(
            set(audit.collisions[0][1]),
            {"mdx:composed", "mdx:decomposed"},
        )

    def test_rows_do_not_end_in_whitespace_when_waiver_reasons_are_empty(self) -> None:
        entry = catalogue.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="SCnet: Large",
            weight_file="scnet_large.ckpt",
        )

        rendered = render.presentation_reference_tsv([entry])

        self.assertTrue(all(line == line.rstrip() for line in rendered.splitlines()))


class DisplayReferenceCliTests(unittest.TestCase):
    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-display-reference-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")
        self.reference = os.path.join(self.tmp, "model_display_reference.tsv")
        self.intent = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")

    def _run(
        self,
        argv: list[str],
        *,
        vr: Mapping[str, object] | None = None,
        mdx: Mapping[str, object] | None = None,
    ) -> int:
        import contextlib
        from unittest import mock

        class _Snapshot:
            def __init__(self) -> None:
                self.vr: dict[str, object] = dict(
                    {"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"} if vr is None else vr
                )
                self.mdx: dict[str, object] = dict({} if mdx is None else mdx)
                self.demucs: dict[str, object] = {}
                self.apollo: dict[str, object] = {}
                self.meta: dict[str, object] = {}
                self.unsupported: dict[str, object] = {}
                self.report = None

        snapshot = _Snapshot()

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.out))
            stack.enter_context(
                mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.reference)
            )
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", self.intent))
            stack.enter_context(
                mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem)
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=_clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue,
                    "_build_catalogue_context",
                    lambda **_kwargs: catalogue.CatalogueContext(),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue,
                    "_snapshot_and_payloads",
                    lambda **_kwargs: (snapshot, ({}, {}, {}, {})),
                )
            )
            return cli.main(argv)

    def test_flag_writes_the_complete_reference(self) -> None:
        self.assertEqual(self._run(["--write-display-reference"]), 0)
        with open(self.reference, encoding="utf-8") as handle:
            rendered = handle.read()
        self.assertIn("catalogue_generation", rendered)
        self.assertIn("1_HP-UVR.pth", rendered)

    def test_check_detects_reference_drift_without_writing(self) -> None:
        self.assertEqual(self._run(["--write-display-reference"]), 0)
        with open(self.reference, "a", encoding="utf-8") as handle:
            handle.write("drift\n")
        with open(self.reference, "rb") as handle:
            before = handle.read()

        self.assertEqual(self._run(["--check", "--write-display-reference"]), 1)
        with open(self.reference, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_check_rejects_matching_reference_with_unreviewed_flags(self) -> None:
        import contextlib
        import io

        mdx = {"MDX-Net Model: private_model": "private_model.onnx"}
        self.assertEqual(
            self._run(["--write-display-reference"], vr={}, mdx=mdx),
            0,
        )
        with open(self.reference, "rb") as handle:
            before = handle.read()
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            result = self._run(["--check", "--write-display-reference"], vr={}, mdx=mdx)

        self.assertEqual(result, 1)
        self.assertIn("unreviewed presentation flag", stderr.getvalue().lower())
        with open(self.reference, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_check_rejects_matching_case_insensitive_display_collision(self) -> None:
        import contextlib
        import io

        mdx = {
            "MDX-Net Model: Shared": "first.onnx",
            "MDX-Net: shared": "second.onnx",
        }
        self.assertEqual(
            self._run(["--write-display-reference"], vr={}, mdx=mdx),
            0,
        )
        with open(self.reference, "rb") as handle:
            before = handle.read()
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            result = self._run(["--check", "--write-display-reference"], vr={}, mdx=mdx)

        self.assertEqual(result, 1)
        self.assertIn("case-insensitive display collision", stderr.getvalue().lower())
        with open(self.reference, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_default_run_writes_the_reference(self) -> None:
        self.assertEqual(self._run([]), 0)
        self.assertTrue(os.path.exists(self.reference))

    def test_summary_with_flag_remains_read_only(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self._run(["--summary", "--write-display-reference"]), 1)
        self.assertFalse(os.path.exists(self.reference))

    def test_refused_run_does_not_write_the_reference(self) -> None:
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **400**\n")

        self.assertEqual(self._run(["--write-display-reference"]), 2)
        self.assertFalse(os.path.exists(self.reference))

    def test_flag_is_opt_in(self) -> None:
        self.assertTrue(cli._parse_args(["--write-display-reference"]).write_display_reference)
        self.assertFalse(cli._parse_args([]).write_display_reference)

    def test_stem_semantics_reference_flag_is_opt_in(self) -> None:
        self.assertTrue(
            cli._parse_args(["--write-stem-semantics-reference"]).write_stem_semantics_reference
        )
        self.assertFalse(cli._parse_args([]).write_stem_semantics_reference)


class CheckModeTests(unittest.TestCase):
    """--check reports drift without touching the tree."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-check-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")
        self.tsv = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.display = os.path.join(self.tmp, "model_display_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")

    def _run(self, argv: list) -> int:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(3)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        ctx = catalogue.CatalogueContext(
            community_by_file={
                "model.ckpt": catalogue.CommunityRef(
                    filename="model.ckpt",
                    arch="Roformer",
                    primary_stem="Vocals",
                    stems_text="vocals, other",
                    friendly_name="Some Model",
                    intent="vocals",
                )
            }
        )
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.out))
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", self.tsv))
            stack.enter_context(mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display))
            stack.enter_context(
                mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem)
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=_clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context", lambda **k: ctx)
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue,
                    "_snapshot_and_payloads",
                    lambda **k: (_Snapshot(), ({}, {}, {}, {})),
                )
            )
            return cli.main(argv)

    def test_check_on_an_up_to_date_document_exits_zero(self) -> None:
        self.assertEqual(self._run([]), 0)
        with open(self.out, "rb") as handle:
            before = handle.read()
        mtime = os.path.getmtime(self.out)
        self.assertEqual(self._run(["--check"]), 0)
        with open(self.out, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(os.path.getmtime(self.out), mtime, "--check rewrote the file")

    def test_check_reports_drift_without_writing(self) -> None:
        self.assertEqual(self._run([]), 0)
        with open(self.out, "a", encoding="utf-8") as handle:
            handle.write("\ndrifted\n")
        with open(self.out, "rb") as handle:
            drifted = handle.read()
        self.assertEqual(self._run(["--check"]), 1)
        with open(self.out, "rb") as handle:
            self.assertEqual(handle.read(), drifted, "--check wrote anyway")

    def test_check_on_a_missing_document_is_drift(self) -> None:
        self.assertEqual(self._run(["--check"]), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_check_also_covers_the_tsv_when_requested(self) -> None:
        self.assertEqual(self._run(["--write-tsv"]), 0)
        self.assertEqual(self._run(["--check", "--write-tsv"]), 0)
        os.unlink(self.tsv)
        self.assertEqual(self._run(["--check", "--write-tsv"]), 1)
        self.assertFalse(os.path.exists(self.tsv))

    def test_check_and_write_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            cli._parse_args(["--check", "--write"])

    def test_write_is_the_default(self) -> None:
        self.assertFalse(cli._parse_args([]).check)


class VolatileHeaderTests(unittest.TestCase):
    """Drift means the catalogue changed, not that time passed."""

    def test_a_changed_generation_timestamp_is_not_drift(self) -> None:
        rendered = render._render([], unsupported_count=0)
        aged = rendered.replace("Generated: ", "Generated: 1999-01-01 00:00 UTC ignored ", 1)
        self.assertNotEqual(rendered, aged)
        self.assertEqual(
            render._canonical_for_diff(rendered),
            render._canonical_for_diff(aged),
        )

    def test_a_changed_entry_is_drift(self) -> None:
        rendered = render._render([], unsupported_count=0)
        changed = rendered.replace("Total catalogue entries: **0**", "**9**", 1)
        self.assertNotEqual(
            render._canonical_for_diff(rendered),
            render._canonical_for_diff(changed),
        )


class ProvenanceBlockTests(unittest.TestCase):
    """The document should say whether it was generated from good data."""

    def _report(
        self,
        *,
        succeeded: tuple = (),
        failed: tuple = (),
        stale: tuple = (),
        usable: bool = True,
    ):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(
            mode=RefreshMode.STALE_WHILE_REVALIDATE,
            succeeded=succeeded,
            failed=failed,
            stale=stale,
            usable=usable,
        )

    def test_names_succeeded_and_failed_sources(self) -> None:
        from core.catalogue_types import SourceId

        text = render._render(
            [],
            unsupported_count=0,
            report=self._report(
                succeeded=(SourceId.UPSTREAM,),
                failed=((SourceId.POLITREES, "timeout"),),
                stale=(SourceId.MVSEPLESS,),
            ),
        )
        self.assertIn("upstream", text)
        self.assertIn("politrees", text)
        self.assertIn("timeout", text)
        self.assertIn("mvsepless", text)

    def test_provenance_lines_do_not_count_as_drift(self) -> None:
        from core.catalogue_types import SourceId

        a = render._render([], unsupported_count=0, report=self._report())
        b = render._render(
            [],
            unsupported_count=0,
            report=self._report(failed=((SourceId.POLITREES, "timeout"),)),
        )
        self.assertNotEqual(a, b)
        self.assertEqual(render._canonical_for_diff(a), render._canonical_for_diff(b))

    def test_online_provenance_block_does_not_drift_from_warm_offline_report(self) -> None:
        online = render._render([], unsupported_count=0, report=self._report())
        warm_offline = render._render([], unsupported_count=0, report=None)

        self.assertNotEqual(online, warm_offline)
        self.assertEqual(
            render._canonical_for_diff(online),
            render._canonical_for_diff(warm_offline),
        )

    def test_renders_without_a_report(self) -> None:
        text = render._render([], unsupported_count=0, report=None)
        self.assertIn("Total catalogue entries", text)

    def test_intent_source_prose_excludes_unused_hash_supplements(self) -> None:
        """Removing the fetch while retaining its provenance claim is misleading."""
        text = render._render([], unsupported_count=0, report=self._report())

        self.assertIn("YAML metadata", text)
        self.assertIn("community", text)
        self.assertNotIn("yaml/hash metadata", text)
        self.assertNotIn("Politrees model_data", text)
        self.assertNotIn("Cache politrees", text)


class FabricatedFlagTests(unittest.TestCase):
    """Metadata that cannot resolve a backend must not produce mismatch flags."""

    def test_intent_alone_is_not_resolved_metadata(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Model",
            weight_file="m.ckpt",
            name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(
            entry, EntryMeta(label="L", display="L", arch="Roformer", intent="vocals")
        )
        self.assertEqual(entry.metadata_source, "unavailable")

    def test_stems_still_count_as_resolved_metadata(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Model",
            weight_file="m.ckpt",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(
            entry,
            EntryMeta(label="L", display="L", arch="Roformer", stems=["vocals", "other"]),
        )
        self.assertEqual(entry.metadata_source, "catalogue_meta")

    def test_unknown_backend_focus_produces_no_mismatch_flags(self) -> None:
        """You cannot detect a mismatch against a backend you could not determine."""
        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Model",
            weight_file="m.ckpt",
            name_intent="vocals",
        )
        entry.metadata_source = "catalogue_meta"
        entry.backend_focus = "unknown"
        self.assertEqual(catalogue._flag_mismatches(entry), [])

    def test_intent_only_entry_ends_up_unflagged(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Model",
            weight_file="m.ckpt",
            name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(
            entry, EntryMeta(label="L", display="L", arch="Roformer", intent="vocals")
        )
        catalogue._finalize_entry(entry)
        self.assertEqual(entry.flags, [])


class YamlProvenanceStabilityTests(unittest.TestCase):
    """The metadata label must not flip between runs, or --check sees drift."""

    def test_a_downloaded_config_reports_the_same_source_on_the_next_run(self) -> None:
        import shutil
        import tempfile
        from unittest import mock

        cache_dir = tempfile.mkdtemp(prefix="uvr-generator-yaml-")
        self.addCleanup(shutil.rmtree, cache_dir, ignore_errors=True)
        url = "https://example.invalid/c/m.yaml"
        body = b"training:\n  instruments: [vocals, other]\n  target_instrument: other\n"

        class _Response:
            def read(self) -> bytes:
                return body

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with (
            mock.patch.object(catalogue, "YAML_CACHE_DIR", cache_dir),
            mock.patch("core.mdx_config_fetch._urlopen", return_value=_Response()) as fetch,
        ):
            first = catalogue._load_yaml_meta("m.yaml", url)[3]
            second = catalogue._load_yaml_meta("m.yaml", url)[3]

        self.assertEqual(first, second, "provenance label flipped between runs")
        self.assertEqual(first, "remote_yaml:m.yaml")
        self.assertEqual(fetch.call_count, 1)


class CheckContractTests(unittest.TestCase):
    """--check must be genuinely read-only and must not lie about coverage."""

    def _assert_default_online_swr_is_read_only(
        self, *, argv: list[str], stale_source: bool
    ) -> None:
        import contextlib
        import io
        import shutil
        import tempfile
        import threading
        from unittest import mock

        from core import catalogue_stem_cache, download_sizes, paths
        from core.catalogue_coordinator import CatalogueCoordinator
        from core.remote_catalog_cache import RemoteJsonSource

        tmp = tempfile.mkdtemp(prefix="uvr-online-swr-readonly-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache_root = os.path.join(tmp, "cache")
        supplemental_cache = os.path.join(cache_root, "supplemental")
        community_cache = os.path.join(cache_root, "community")
        yaml_cache = os.path.join(cache_root, "yaml")
        source_cache = os.path.join(cache_root, "sources", "upstream.json")
        stem_cache = os.path.join(cache_root, "derived-stems", "stems.json")
        size_cache = os.path.join(cache_root, "derived-sizes", "sizes.json")
        model_store = os.path.join(tmp, "model-store")
        legacy_data = os.path.join(tmp, "legacy-data")
        legacy_base = os.path.join(tmp, "legacy-base")
        legacy_size = os.path.join(legacy_data, "download_size_cache.json")
        out = os.path.join(tmp, "models-catalogue.md")
        intent_ref = os.path.join(tmp, "model_intent_reference.tsv")
        display_ref = os.path.join(tmp, "model_display_reference.tsv")
        sidecar = catalogue._ir_path_for(out)

        os.makedirs(legacy_data)
        legacy_size_bytes = b'{"legacy": true}\n'
        with open(legacy_size, "wb") as handle:
            handle.write(legacy_size_bytes)

        old_payload = {
            "vr_download_list": {},
            "mdx_download_list": {
                "MDX23C Model: Old": {"old.ckpt": "https://example.invalid/old.ckpt"}
            },
            "demucs_download_list": {},
        }
        source_bytes: bytes | None = None
        if stale_source:
            os.makedirs(os.path.dirname(source_cache))
            source_bytes = json.dumps({"fetched_at": 1.0, "data": old_payload}).encode("utf-8")
            with open(source_cache, "wb") as handle:
                handle.write(source_bytes)

        sentinels = {
            out: b"catalogue sentinel\n",
            intent_ref: b"intent sentinel\n",
            display_ref: b"display sentinel\n",
            sidecar: b'{"sidecar": "sentinel"}\n',
        }
        for path, data in sentinels.items():
            with open(path, "wb") as handle:
                handle.write(data)

        class _Response:
            status = 200
            headers: dict = {}

            def __init__(self, data: bytes) -> None:
                self.data = data

            def read(self, *_args: object) -> bytes:
                return self.data

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        fresh_payload = {
            "vr_download_list": {},
            "mdx_download_list": {
                "MDX23C Model: Fresh Async": {
                    "fresh.ckpt": "https://example.invalid/fresh.ckpt",
                    "fresh.yaml": "https://example.invalid/fresh.yaml",
                }
            },
            "demucs_download_list": {},
        }
        source_started = threading.Event()
        release_source = threading.Event()

        def source_open(_target: object) -> _Response:
            source_started.set()
            release_source.wait(timeout=2)
            return _Response(json.dumps(fresh_payload).encode("utf-8"))

        def supplemental_open(target: object) -> _Response:
            url = str(getattr(target, "full_url", target))
            if url == catalogue._COMMUNITY_MODELS_URL:
                return _Response(b"")
            raise AssertionError(f"unexpected fetch: {url}")

        source = RemoteJsonSource(
            source_id=SourceId.UPSTREAM,
            url="https://example.invalid/upstream.json",
            cache_filename="upstream.json",
            cache_path=source_cache,
            ttl_seconds=60,
            opener=source_open,
        )
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: source,
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        real_close = coordinator.close

        def wait_for_refresh_then_close() -> None:
            self.assertTrue(source_started.wait(timeout=2), "SWR fetch did not start")
            release_source.set()
            with source._lock:
                flight = source._flight
            self.assertIsNotNone(flight, "SWR worker was not registered")
            assert flight is not None
            self.assertTrue(flight.wait(timeout=2), "SWR publish did not finish")
            real_close()

        coordinator.close = wait_for_refresh_then_close  # type: ignore[method-assign]
        self.addCleanup(real_close)
        self.addCleanup(release_source.set)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", out))
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", intent_ref))
            stack.enter_context(mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", display_ref))
            stack.enter_context(
                mock.patch.object(catalogue, "CatalogueCoordinator", lambda: coordinator)
            )
            stack.enter_context(
                mock.patch.object(catalogue, "COMMUNITY_CACHE_DIR", community_cache)
            )
            stack.enter_context(mock.patch.object(catalogue, "YAML_CACHE_DIR", yaml_cache))
            stack.enter_context(mock.patch.object(paths, "DATA_DIR", legacy_data))
            stack.enter_context(mock.patch.object(paths, "BASE_PATH", legacy_base))
            stack.enter_context(mock.patch.object(paths, "MDX_C_CONFIG_PATH", model_store))
            stack.enter_context(mock.patch.object(paths, "CATALOGUE_STEM_CACHE_FILE", stem_cache))
            stack.enter_context(mock.patch.object(paths, "DOWNLOAD_SIZE_CACHE_FILE", size_cache))
            stack.enter_context(mock.patch.object(catalogue_stem_cache, "_memory_entries", None))
            stack.enter_context(mock.patch.object(download_sizes, "_memory_payload", None))
            stack.enter_context(mock.patch.object(download_sizes, "_memory_path", None))
            stack.enter_context(mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": ""}))
            stack.enter_context(mock.patch("core.mdx_config_fetch._urlopen", supplemental_open))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(argv)

        self.assertEqual(rc, 1, stderr.getvalue())
        latest = coordinator._latest
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertIn("MDX23C Model: Fresh Async", latest.mdx)
        if source_bytes is None:
            self.assertFalse(os.path.exists(os.path.dirname(source_cache)))
        else:
            with open(source_cache, "rb") as handle:
                self.assertEqual(handle.read(), source_bytes)
        self.assertTrue(
            os.path.isfile(legacy_size),
            "SWR publication migrated the legacy download-size cache",
        )
        with open(legacy_size, "rb") as handle:
            self.assertEqual(handle.read(), legacy_size_bytes)
        self.assertFalse(os.path.exists(os.path.dirname(size_cache)))
        self.assertFalse(os.path.exists(os.path.dirname(stem_cache)))
        self.assertFalse(os.path.exists(supplemental_cache))
        self.assertFalse(os.path.exists(community_cache))
        self.assertFalse(os.path.exists(yaml_cache))
        self.assertFalse(os.path.exists(model_store))
        for path, data in sentinels.items():
            with self.subTest(path=path):
                with open(path, "rb") as handle:
                    self.assertEqual(handle.read(), data)

    def test_default_online_check_swr_publish_keeps_every_cache_and_artifact_read_only(
        self,
    ) -> None:
        self._assert_default_online_swr_is_read_only(
            argv=["--check", "--write-display-reference"], stale_source=True
        )

    def test_default_online_summary_swr_publish_keeps_every_cache_and_artifact_read_only(
        self,
    ) -> None:
        self._assert_default_online_swr_is_read_only(argv=["--summary"], stale_source=False)

    def test_online_check_fetches_in_memory_without_mutating_any_cache_or_artifact(
        self,
    ) -> None:
        import contextlib
        import io
        import shutil
        import tempfile
        from unittest import mock

        from core.catalogue_coordinator import CatalogueCoordinator
        from core.remote_catalog_cache import RemoteJsonSource

        tmp = tempfile.mkdtemp(prefix="uvr-online-check-readonly-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache_root = os.path.join(tmp, "cache")
        supplemental_cache = os.path.join(cache_root, "supplemental")
        community_cache = os.path.join(cache_root, "community")
        yaml_cache = os.path.join(cache_root, "yaml")
        source_cache = os.path.join(cache_root, "sources", "upstream.json")
        stem_cache = os.path.join(cache_root, "derived", "stems.json")
        size_cache = os.path.join(cache_root, "identity", "sizes.json")
        model_store = os.path.join(tmp, "model-store")
        out = os.path.join(tmp, "models-catalogue.md")
        intent_ref = os.path.join(tmp, "model_intent_reference.tsv")
        display_ref = os.path.join(tmp, "model_display_reference.tsv")
        sidecar = catalogue._ir_path_for(out)

        os.makedirs(community_cache)
        stale_path = catalogue._cache_path(
            community_cache,
            catalogue._COMMUNITY_MODELS_URL,
            "models.txt",
        )
        with open(stale_path, "wb") as handle:
            handle.write(b'{"stale": true}')
        os.utime(stale_path, (1, 1))

        sentinels = {
            out: b"catalogue sentinel\n",
            intent_ref: b"intent sentinel\n",
            display_ref: b"display sentinel\n",
            sidecar: b'{"sidecar": "sentinel"}\n',
        }
        for path, data in sentinels.items():
            with open(path, "wb") as handle:
                handle.write(data)

        class _Response:
            status = 200
            headers: dict = {}

            def __init__(self, data: bytes) -> None:
                self.data = data

            def read(self, *_args: object) -> bytes:
                return self.data

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        upstream_payload = {
            "vr_download_list": {"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"},
            "mdx_download_list": {
                "MDX23C Model: Fresh": {
                    "fresh.ckpt": "https://example.invalid/fresh.ckpt",
                    "fresh.yaml": "https://example.invalid/fresh.yaml",
                }
            },
            "demucs_download_list": {},
        }
        source_calls: list[str] = []

        def source_open(target: object) -> _Response:
            source_calls.append(str(getattr(target, "full_url", target)))
            return _Response(json.dumps(upstream_payload).encode("utf-8"))

        supplement_calls: list[str] = []

        def supplemental_open(target: object) -> _Response:
            url = str(getattr(target, "full_url", target))
            supplement_calls.append(url)
            if url == catalogue._COMMUNITY_MODELS_URL:
                return _Response(b"")
            if url == "https://example.invalid/fresh.yaml":
                return _Response(
                    b"training:\n  instruments: [vocals, other]\n  target_instrument: other\n"
                )
            raise AssertionError(f"unexpected fetch: {url}")

        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: RemoteJsonSource(
                    source_id=SourceId.UPSTREAM,
                    url="https://example.invalid/upstream.json",
                    cache_path=source_cache,
                    opener=source_open,
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)

        stderr = io.StringIO()
        from core import catalogue_stem_cache, download_sizes

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", out))
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", intent_ref))
            stack.enter_context(mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", display_ref))
            stack.enter_context(
                mock.patch.object(catalogue, "CatalogueCoordinator", lambda: coordinator)
            )
            stack.enter_context(
                mock.patch.object(catalogue, "COMMUNITY_CACHE_DIR", community_cache)
            )
            stack.enter_context(mock.patch.object(catalogue, "YAML_CACHE_DIR", yaml_cache))
            stack.enter_context(
                mock.patch.object(catalogue.paths, "MDX_C_CONFIG_PATH", model_store)
            )
            stack.enter_context(
                mock.patch.object(catalogue.paths, "CATALOGUE_STEM_CACHE_FILE", stem_cache)
            )
            stack.enter_context(
                mock.patch.object(catalogue.paths, "DOWNLOAD_SIZE_CACHE_FILE", size_cache)
            )
            stack.enter_context(mock.patch.object(catalogue_stem_cache, "_memory_entries", None))
            stack.enter_context(mock.patch.object(download_sizes, "_memory_payload", None))
            stack.enter_context(mock.patch.object(download_sizes, "_memory_path", None))
            stack.enter_context(mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": ""}))
            stack.enter_context(mock.patch("core.mdx_config_fetch._urlopen", supplemental_open))
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=_clean_stem_audit
                )
            )
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(["--check", "--refresh", "--write-display-reference"])

        self.assertEqual(rc, 1, stderr.getvalue())
        self.assertTrue(source_calls, "coordinator network data was not compared")
        self.assertEqual(
            set(supplement_calls),
            {
                catalogue._COMMUNITY_MODELS_URL,
                "https://example.invalid/fresh.yaml",
            },
        )
        self.assertIn("Out of date", stderr.getvalue())
        with open(stale_path, "rb") as handle:
            self.assertEqual(handle.read(), b'{"stale": true}')
        for path, data in sentinels.items():
            with self.subTest(path=path):
                with open(path, "rb") as handle:
                    self.assertEqual(handle.read(), data)
        self.assertFalse(os.path.exists(supplemental_cache))
        self.assertEqual(os.listdir(community_cache), [os.path.basename(stale_path)])
        self.assertFalse(os.path.exists(yaml_cache))
        self.assertFalse(os.path.exists(os.path.dirname(source_cache)))
        self.assertFalse(os.path.exists(os.path.dirname(stem_cache)))
        self.assertFalse(os.path.exists(os.path.dirname(size_cache)))
        self.assertFalse(os.path.exists(model_store))

    def test_check_forbids_metadata_writes(self) -> None:
        """fetch_mdx_config_url writes yaml into the repo in the dev layout."""
        policy = cli._policy_for(cli._parse_args(["--check"]))
        self.assertFalse(policy.allow_metadata_writes)
        self.assertFalse(policy.allow_cache_writes)

    def test_a_normal_run_still_allows_metadata_writes(self) -> None:
        policy = cli._policy_for(cli._parse_args([]))
        self.assertTrue(policy.allow_metadata_writes)
        self.assertTrue(policy.allow_cache_writes)

    def test_load_yaml_meta_does_not_fetch_configs_when_writes_are_denied(self) -> None:
        from unittest import mock

        called = []

        def spy(name: str, url: str) -> bool:
            called.append(name)
            return False

        policy = catalogue.FetchPolicy(allow_network=True, allow_metadata_writes=False)
        with (
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", spy),
            mock.patch(
                "core.mdx_config_fetch._urlopen",
                side_effect=urllib.error.URLError("blocked"),
            ),
        ):
            catalogue._load_yaml_meta(
                "nope.yaml", "https://example.invalid/nope.yaml", policy=policy
            )
        self.assertEqual(called, [], "--check wrote a config into the model store")

    def test_read_only_online_yaml_fetch_is_parsed_without_creating_a_cache(self) -> None:
        import shutil
        import tempfile
        from unittest import mock

        tmp = tempfile.mkdtemp(prefix="uvr-yaml-readonly-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache_dir = os.path.join(tmp, "yaml-cache")
        model_store = os.path.join(tmp, "model-store")
        body = (
            b"training:\n"
            b"  instruments: [vocals, other]\n"
            b"  target_instrument: other\n"
            b"model:\n"
            b"  num_bands: 64\n"
        )

        class _Response:
            def read(self, *_args: object) -> bytes:
                return body

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        policy = catalogue.FetchPolicy(
            allow_network=True,
            allow_metadata_writes=False,
            allow_cache_writes=False,
        )
        with (
            mock.patch.object(catalogue, "YAML_CACHE_DIR", cache_dir),
            mock.patch.object(catalogue.paths, "MDX_C_CONFIG_PATH", model_store),
            mock.patch(
                "core.mdx_config_fetch.fetch_mdx_config_url",
                side_effect=AssertionError("model-store write path used"),
            ),
            mock.patch("core.mdx_config_fetch._urlopen", return_value=_Response()),
        ):
            instruments, target, arch, source, _digest = catalogue._load_yaml_meta(
                "fresh.yaml",
                "https://example.invalid/fresh.yaml",
                policy=policy,
            )

        self.assertEqual(instruments, ["vocals", "other"])
        self.assertEqual(target, "other")
        self.assertEqual(arch, "Mel-Band Roformer")
        self.assertEqual(source, "remote_yaml:fresh.yaml")
        self.assertFalse(os.path.exists(cache_dir))
        self.assertFalse(os.path.exists(model_store))

    def test_check_does_not_claim_to_refuse_a_write_it_never_makes(self) -> None:
        import contextlib
        import io
        from unittest import mock

        class _Snapshot:
            vr: dict = {}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        import tempfile

        tmp = tempfile.mkdtemp(prefix="uvr-checkmsg-")
        out = os.path.join(tmp, "models-catalogue.md")
        with open(out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **400**\n")

        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", out))
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue.CatalogueContext()
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                )
            )
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(["--check"])

        self.assertEqual(rc, 2)
        message = stderr.getvalue()
        self.assertNotIn("Refusing to write", message)
        self.assertIn("cannot judge", message.lower())

    def test_legacy_tsv_flag_writes_the_empty_but_available_reference(self) -> None:
        import contextlib
        import io
        import tempfile
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        tmp = tempfile.mkdtemp(prefix="uvr-tsvwarn-")
        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", os.path.join(tmp, "c.md")))
            stack.enter_context(
                mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(tmp, "r.tsv"))
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "DISPLAY_REFERENCE_TSV_PATH",
                    os.path.join(tmp, "display.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                    os.path.join(tmp, "stem.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=_clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue.CatalogueContext()
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                )
            )
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(["--write-tsv"])

        self.assertEqual(rc, 0)
        self.assertIn("deprecated", stderr.getvalue().lower())


class IntermediateRepresentationTests(unittest.TestCase):
    """A stable machine-readable form that Markdown and TSV render from."""

    def _entry(self, label: str = "Some Model"):
        return catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label=label,
            weight_file="m.ckpt",
            instruments=["vocals", "other"],
            stem_count=2,
            name_intent="vocals",
            metadata_source="catalogue_meta",
        )

    def test_carries_a_schema_version(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=0)
        self.assertEqual(ir["schema_version"], catalogue.IR_SCHEMA_VERSION)

    def test_round_trips_through_json(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=3)
        restored = json.loads(json.dumps(ir))
        self.assertEqual(restored["unsupported_omitted"], 3)
        self.assertEqual(restored["entries"][0]["catalogue_label"], "Some Model")
        self.assertEqual(restored["entries"][0]["instruments"], ["vocals", "other"])

    def test_entry_count_is_recorded_for_the_publication_guard(self) -> None:
        ir = catalogue.build_ir(
            [self._entry("a"), self._entry("b")], report=None, unsupported_count=0
        )
        self.assertEqual(ir["entry_count"], 2)

    def test_provenance_is_included_when_a_report_exists(self) -> None:
        from core.catalogue_types import RefreshMode, RefreshReport, SourceId

        report = RefreshReport(
            mode=RefreshMode.OFFLINE, usable=True, failed=((SourceId.POLITREES, "boom"),)
        )
        ir = catalogue.build_ir([self._entry()], report=report, unsupported_count=0)
        self.assertEqual(ir["provenance"]["mode"], "offline")
        self.assertTrue(ir["provenance"]["failed"])

    def test_no_report_still_produces_valid_ir(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=0)
        self.assertEqual(ir["provenance"], {})

    def test_previous_entry_count_prefers_the_sidecar(self) -> None:
        """More reliable than re-parsing a rendered summary line."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            sidecar = catalogue._ir_path_for(doc)
            with open(sidecar, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "entry_count": 412,
                        # Must prove it describes this document; see
                        # SidecarTrustTests for the stale case.
                        "document_sha256": catalogue._document_digest(doc),
                    },
                    handle,
                )
            self.assertEqual(cli._previous_entry_count(doc), 412)

    def test_previous_entry_count_falls_back_to_the_document(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            self.assertEqual(cli._previous_entry_count(doc), 7)

    def test_a_corrupt_sidecar_falls_back_rather_than_failing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            with open(catalogue._ir_path_for(doc), "w", encoding="utf-8") as handle:
                handle.write("{not json")
            self.assertEqual(cli._previous_entry_count(doc), 7)


class StemSemanticsReferenceRenderTests(unittest.TestCase):
    def test_provenance_prefix_and_waiver_projection_preserve_review_columns(self) -> None:
        entry = catalogue.ModelEntry(
            source="fixture-source",
            family="Apollo",
            catalogue_label="Restoration fixture",
            weight_file="restoration.onnx",
            arch="Apollo execution",
        )
        from core.model_stem_manifest import StemSemanticsRegistry

        registry = StemSemanticsRegistry(
            roles={},
            pairs={},
            models={},
            waivers={"apollo:restoration": "no stem inventory"},
        )

        audit = cli.stem_audit.audit_catalogue_stems(
            [entry],
            catalogue.CatalogueContext(),
            registry=registry,
        )
        rendered = render.stem_semantics_reference_tsv(audit.reference_rows)

        header, row = rendered.splitlines()
        columns = row.split("\t")
        self.assertEqual(
            header.split("\t"),
            [
                "runtime_family",
                "runtime_basename",
                "catalogue_source",
                "catalogue_label",
                "execution_arch",
                *STEM_SEMANTICS_REFERENCE_HEADERS,
            ],
        )
        self.assertEqual(
            columns[:5],
            [
                "apollo",
                "restoration",
                "fixture-source",
                "Restoration fixture",
                "Apollo execution",
            ],
        )
        self.assertEqual(columns[5], "apollo:restoration")
        self.assertNotEqual(columns[6], "")
        self.assertEqual(columns[-6:-3], ["reviewed_waiver", "waived", "no stem inventory"])
        self.assertEqual(columns[-3:], ["", "", ""])

    def test_native_complement_ordered_sum_and_false_default_render_exact_cells(self) -> None:
        registry = load_stem_manifest_document(
            {
                "schema_version": 2,
                "roles": {
                    "vocal.lead": {
                        "display": "Lead Vocals",
                        "filename_tag": "Lead_Vocals",
                        "family": "vocal",
                    },
                    "vocal.lead.removed": {
                        "display": "Lead Vocals Removed",
                        "filename_tag": "Lead_Vocals_Removed",
                        "family": "vocal",
                        "removed_of": "vocal.lead",
                    },
                    "vocal.backing": {
                        "display": "Backing Vocals",
                        "filename_tag": "Backing_Vocals",
                        "family": "vocal",
                    },
                    "mix.instrumental": {
                        "display": "Instrumental",
                        "filename_tag": "Instrumental",
                        "family": "mix",
                    },
                    "mix.instrumental_with_backing_vocals": {
                        "display": "Instrumental with Backing Vocals",
                        "filename_tag": "Instrumental_with_Backing_Vocals",
                        "family": "mix",
                    },
                },
                "pairs": {},
                "models": {
                    "mdx:fixture": {
                        "native_signature": ["Lead", "Backing", "Instrumental"],
                        "intent": "karaoke",
                        "contexts": {
                            "full_mix": {
                                "logical_primary": "vocal.lead",
                                "logical_secondary": "vocal.lead.removed",
                                "outputs": [
                                    {"native": "Lead", "role": "vocal.lead"},
                                    {"native": "Backing", "role": "vocal.backing"},
                                    {
                                        "native": "Instrumental",
                                        "role": "mix.instrumental",
                                    },
                                    {
                                        "native": None,
                                        "role": "vocal.lead.removed",
                                        "production": "derived",
                                        "complement_of": "vocal.lead",
                                    },
                                    {
                                        "native": None,
                                        "role": "mix.instrumental_with_backing_vocals",
                                        "production": "derived",
                                        "derived_from": [
                                            "vocal.backing",
                                            "mix.instrumental",
                                        ],
                                        "selected_by_default": False,
                                    },
                                ],
                            },
                            "vocal_split": {
                                "logical_primary": "vocal.backing",
                                "outputs": [
                                    {"native": "Lead", "role": "vocal.lead"},
                                    {"native": "Backing", "role": "vocal.backing"},
                                    {
                                        "native": "Instrumental",
                                        "role": "mix.instrumental",
                                    },
                                ],
                            },
                        },
                        "evidence": "fixture",
                    }
                },
                "waivers": {"apollo:restoration": "no stem inventory"},
            }
        )
        entries = [
            catalogue.ModelEntry(
                source="fixture-source",
                family="Roformer",
                catalogue_label="Fixture",
                weight_file="fixture.ckpt",
                primary_stem="Lead",
                instruments=["Lead", "Backing", "Instrumental"],
            ),
            catalogue.ModelEntry(
                source="fixture-source",
                family="Apollo",
                catalogue_label="Restoration fixture",
                weight_file="restoration.onnx",
                arch="Apollo execution",
            ),
        ]

        audit = cli.stem_audit.audit_catalogue_stems(
            entries,
            catalogue.CatalogueContext(),
            registry=registry,
        )
        lines = render.stem_semantics_reference_tsv(audit.reference_rows).splitlines()
        headers = lines[0].split("\t")
        by_context_role = {
            (
                columns[headers.index("processing_context")],
                columns[headers.index("role_id")],
            ): columns
            for columns in (line.split("\t") for line in lines[1:])
            if columns[headers.index("role_id")]
        }
        waiver = next(
            line.split("\t") for line in lines[1:] if line.startswith("apollo\trestoration\t")
        )

        full_lead = by_context_role[("full_mix", "vocal.lead")]
        full_removed = by_context_role[("full_mix", "vocal.lead.removed")]
        full_sum = by_context_role[("full_mix", "mix.instrumental_with_backing_vocals")]
        split_lead = by_context_role[("vocal_split", "vocal.lead")]

        self.assertEqual(full_lead[headers.index("logical_secondary")], "false")
        self.assertEqual(full_removed[headers.index("logical_secondary")], "true")
        self.assertEqual(split_lead[headers.index("logical_secondary")], "")
        self.assertEqual(full_lead[-3:], ["", "", "true"])
        self.assertEqual(full_removed[-3:], ["vocal.lead", "", "true"])
        self.assertEqual(
            full_sum[-3:],
            ["", "vocal.backing|mix.instrumental", "false"],
        )
        self.assertEqual(full_sum[headers.index("logical_secondary")], "false")
        self.assertEqual(waiver[headers.index("logical_secondary")], "")
        self.assertEqual(waiver[-3:], ["", "", ""])


class SummaryModeTests(unittest.TestCase):
    """--summary answers the maintainer's likely question without 7,000 lines."""

    def _entries(self):
        flagged = catalogue.ModelEntry(
            source="TRvlvr",
            family="Roformer",
            catalogue_label="Bad Model",
            weight_file="bad.ckpt",
            name_intent="vocals",
            metadata_source="bundled_yaml:x.yaml",
        )
        flagged.flags = ["NAME says vocal but backend is instrumental-focused"]
        unknown = catalogue.ModelEntry(
            source="extras",
            family="MDX23C",
            catalogue_label="Mystery",
            weight_file="m.ckpt",
            name_intent="unknown",
        )
        fine = catalogue.ModelEntry(
            source="TRvlvr",
            family="VR Architecture",
            catalogue_label="Good Model",
            weight_file="g.pth",
            name_intent="vocals",
            metadata_source="bundled_yaml:y.yaml",
        )
        return [flagged, unknown, fine]

    def test_reports_counts(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=4)
        self.assertIn("**3**", text)
        self.assertIn("4", text)

    def test_lists_flagged_entries(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertIn("Bad Model", text)
        self.assertIn("backend is instrumental-focused", text)

    def test_lists_unknown_intent_entries(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertIn("Mystery", text)

    def test_omits_the_clean_entries(self) -> None:
        """The point is the exception list, not the full inventory."""
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertNotIn("Good Model", text)

    def test_is_much_shorter_than_the_full_render(self) -> None:
        entries = self._entries()
        full = render._render(entries, unsupported_count=0)
        summary = render.render_summary_report(entries, unsupported_count=0)
        self.assertLess(len(summary), len(full))

    def test_semantic_summary_uses_structured_audit_counts_and_sections(self) -> None:
        ambiguity_evidence = (
            StemRelationshipEvidence(
                model_id="mdx:broken",
                context=StemProcessingContext.FULL_MIX,
                native="Vocals",
                role_id="vocal.vocals",
            ),
            StemRelationshipEvidence(
                model_id="mdx:alternate",
                context=StemProcessingContext.VOCAL_SPLIT,
                native="vocals",
                role_id="vocal.backing",
            ),
        )
        variant_evidence = (
            ambiguity_evidence[0],
            StemRelationshipEvidence(
                model_id="mdx:lead",
                context=StemProcessingContext.FULL_MIX,
                native="Lead Vocal",
                role_id="vocal.vocals",
            ),
        )
        audit = StemAuditResult(
            catalogue_model_ids=("mdx:broken", "mdx:waived", "mdx:raw"),
            reviewed_model_ids=("mdx:broken",),
            waived_model_ids=("mdx:waived",),
            raw_model_ids=("mdx:raw",),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(
                StemAuditDiagnostic(
                    code="native-signature",
                    model_ids=("mdx:broken",),
                    message="reviewed declaration does not match runtime-native source keys",
                    expected=("Vocals",),
                    actual=("Instrumental",),
                ),
                StemAuditDiagnostic(
                    code="context-duplicate-role",
                    model_ids=("mdx:broken",),
                    context=StemProcessingContext.FULL_MIX,
                    message="processing context maps more than one output to the same role",
                    actual=("vocal.vocals", "vocal.vocals"),
                ),
                StemAuditDiagnostic(
                    code="context-native-signature",
                    model_ids=("mdx:broken",),
                    context=StemProcessingContext.FULL_MIX,
                    message="context native outputs do not match the declaration signature",
                    expected=("Vocals",),
                    actual=("Instrumental",),
                ),
                StemAuditDiagnostic(
                    code="pair-incomplete",
                    model_ids=("mdx:broken",),
                    message="pair is incomplete",
                ),
                StemAuditDiagnostic(
                    code="role-display-collision",
                    model_ids=("mdx:broken",),
                    message="roles share a display",
                ),
                StemAuditDiagnostic(
                    code="reference-drift",
                    model_ids=("mdx:broken",),
                    message="checked-in reference differs",
                    expected=("expected-digest",),
                    actual=("actual-digest",),
                    structural=False,
                ),
            ),
            native_to_role_ambiguities=(
                NativeToRoleAmbiguity(
                    normalized_native="vocals",
                    native_spellings=("Vocals", "vocals"),
                    role_ids=("vocal.backing", "vocal.vocals"),
                    model_ids=("mdx:alternate", "mdx:broken"),
                    evidence=ambiguity_evidence,
                ),
            ),
            role_to_native_variants=(
                RoleToNativeVariant(
                    role_id="vocal.vocals",
                    normalized_natives=("lead vocal", "vocals"),
                    native_spellings=("Lead Vocal", "Vocals"),
                    model_ids=("mdx:broken", "mdx:lead"),
                    evidence=variant_evidence,
                ),
            ),
        )

        text = render.render_summary_report(self._entries(), unsupported_count=0, stem_audit=audit)

        self.assertIn("Reviewed catalogue models: **1**", text)
        self.assertIn("Waived catalogue models: **1**", text)
        self.assertIn("Raw catalogue models: **1**", text)
        self.assertIn("Structural stem findings: **5**", text)
        self.assertIn("Accidental semantic collisions: **1**", text)
        self.assertIn("Native-to-role ambiguity groups: **1**", text)
        self.assertIn("Role-to-native variant groups: **1**", text)
        for heading in (
            "## Signature and context findings",
            "## Native-to-role ambiguities",
            "## Role-to-native variants",
            "## Invalid pairs",
            "## Collisions",
            "## Reference drift",
        ):
            self.assertIn(heading, text)
        self.assertIn("`native-signature`", text)
        self.assertIn("`mdx:broken`", text)
        self.assertIn("full_mix", text)
        self.assertIn("expected: `Vocals`", text)
        self.assertIn("actual: `Instrumental`", text)
        self.assertIn("normalized native `vocals`", text)
        self.assertIn("role `vocal.vocals`", text)
        self.assertIn("`mdx:alternate` (vocal_split)", text)
        self.assertIn("`Lead Vocal`", text)
        self.assertNotIn("Nothing flagged", text)
        self.assertNotIn("No stem semantic audit findings.", text)

    def test_summary_does_not_overwrite_the_document(self) -> None:
        """A summary is an ad-hoc query, not a replacement for the catalogue."""
        import contextlib
        import io
        import tempfile
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "models-catalogue.md")
            with open(out, "w", encoding="utf-8") as handle:
                handle.write("THE REAL CATALOGUE\n- Total catalogue entries: **400**\n")
            stdout = io.StringIO()
            with (
                mock.patch.object(cli, "OUTPUT_PATH", out),
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue.CatalogueContext()
                ),
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                ),
                contextlib.redirect_stdout(stdout),
            ):
                rc = cli.main(["--summary"])

            self.assertEqual(rc, 2)
            with open(out, encoding="utf-8") as handle:
                self.assertIn("THE REAL CATALOGUE", handle.read())
            self.assertFalse(os.path.exists(catalogue._ir_path_for(out)))
        self.assertIn("Counts", stdout.getvalue())

    def test_summary_flag_exists(self) -> None:
        self.assertTrue(cli._parse_args(["--summary"]).summary)
        self.assertFalse(cli._parse_args([]).summary)


class CollectEntriesIsTheRealPathTests(unittest.TestCase):
    """A second entry path exercised only by tests is how main and tests drift."""

    def test_main_collects_through_collect_entries(self) -> None:
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch.object(cli, "OUTPUT_PATH", os.path.join(tmp, "c.md")),
                mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(tmp, "intent.tsv")),
                mock.patch.object(
                    cli, "DISPLAY_REFERENCE_TSV_PATH", os.path.join(tmp, "display.tsv")
                ),
                mock.patch.object(
                    cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", os.path.join(tmp, "stem.tsv")
                ),
                mock.patch.object(
                    cli.stem_audit,
                    "audit_catalogue_stems",
                    side_effect=_clean_stem_audit,
                ),
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue.CatalogueContext()
                ),
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                ),
                mock.patch.object(
                    catalogue, "collect_entries", wraps=catalogue.collect_entries
                ) as collect,
            ):
                cli.main([])
        self.assertEqual(collect.call_count, 1, "main did not go through collect_entries")


class UnifiedPublicationCliTests(unittest.TestCase):
    """The generator publishes and compares one complete snapshot bundle."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-unified-publication-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.output = os.path.join(self.tmp, "models-catalogue.md")
        self.intent = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.display = os.path.join(self.tmp, "model_display_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")
        self.ir = catalogue._ir_path_for(self.output)
        self.context = catalogue.CatalogueContext(
            community_by_file={
                "model.ckpt": catalogue.CommunityRef(
                    filename="model.ckpt",
                    arch="Roformer",
                    primary_stem="Vocals",
                    stems_text="vocals, other",
                    friendly_name="Fixture model",
                    intent="vocals",
                )
            },
        )
        self.entry = catalogue.ModelEntry(
            source="fixture",
            family="MDX23C",
            catalogue_label="Fixture Model",
            weight_file="model.ckpt",
            instruments=["vocals", "other"],
            primary_stem="vocals",
            stem_count=2,
            name_intent="vocals",
            metadata_source="fixture",
        )

    def _audit(self, *args: object, **kwargs: object) -> StemAuditResult:
        return StemAuditResult(
            catalogue_model_ids=("mdx:model",),
            reviewed_model_ids=("mdx:model",),
            waived_model_ids=(),
            raw_model_ids=(),
            evidence_counts=CatalogueEvidenceCounts(148, 123, 92, ()),
            diagnostics=(),
        )

    def _run(
        self,
        argv: list[str],
        *,
        context: catalogue.CatalogueContext | None = None,
        audit: object | None = None,
    ) -> int:
        from unittest import mock

        class _Snapshot:
            unsupported: dict[str, object] = {}
            report = None

        from catalogue import stem_audit

        audit_side_effect = self._audit if audit is None else audit
        if isinstance(audit_side_effect, StemAuditResult):
            audit_result = audit_side_effect

            def return_audit(*_args: object, **_kwargs: object) -> StemAuditResult:
                return audit_result

            audit_side_effect = return_audit

        with (
            mock.patch.object(cli, "OUTPUT_PATH", self.output),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", self.intent),
            mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display),
            mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem),
            mock.patch.object(
                catalogue,
                "_build_catalogue_context",
                return_value=context or self.context,
            ),
            mock.patch.object(
                catalogue,
                "collect_entries",
                return_value=(_Snapshot(), [self.entry]),
            ),
            mock.patch.object(
                stem_audit,
                "audit_catalogue_stems",
                side_effect=audit_side_effect,
            ),
        ):
            return cli.main(argv)

    def test_default_write_synchronizes_every_generated_artifact(self) -> None:
        """Removing a default renderer must leave a missing checked-in output."""
        self.assertEqual(self._run([]), 0)

        for path in (self.output, self.ir, self.intent, self.display, self.stem):
            with self.subTest(path=path):
                self.assertTrue(os.path.isfile(path))
        with open(self.ir, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["entry_count"], 1)

    def test_check_compares_every_generated_artifact_without_repairing_it(self) -> None:
        """A stale reference cannot escape --check because its flag was omitted."""
        self.assertEqual(self._run([]), 0)
        with open(self.intent, "a", encoding="utf-8") as handle:
            handle.write("stale\n")
        with open(self.intent, "rb") as handle:
            before = handle.read()

        self.assertEqual(self._run(["--check"]), 1)
        with open(self.intent, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_structural_audit_failure_blocks_every_replacement(self) -> None:
        """Publishing any subset after invalidating manifest structure is unsafe."""
        invalid = StemAuditResult(
            catalogue_model_ids=("mdx:model",),
            reviewed_model_ids=(),
            waived_model_ids=(),
            raw_model_ids=("mdx:model",),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(
                StemAuditDiagnostic(
                    code="catalogue-unreviewed",
                    model_ids=("mdx:model",),
                    message="fixture has no reviewed declaration",
                ),
            ),
        )
        sentinels = {
            self.output: b"markdown sentinel\n",
            self.intent: b"intent sentinel\n",
            self.display: b"display sentinel\n",
            self.stem: b"stem sentinel\n",
            self.ir: b"ir sentinel\n",
        }
        for path, contents in sentinels.items():
            with open(path, "wb") as handle:
                handle.write(contents)

        self.assertEqual(self._run([], audit=invalid), 1)
        for path, contents in sentinels.items():
            with self.subTest(path=path), open(path, "rb") as handle:
                self.assertEqual(handle.read(), contents)

    def test_missing_required_supplemental_evidence_is_degraded(self) -> None:
        """Unavailable evidence cannot replace a complete reference set."""
        incomplete = catalogue.CatalogueContext(
            unavailable_supplemental_evidence=("community models.txt reference",)
        )

        self.assertEqual(self._run([], context=incomplete), 2)
        self.assertFalse(os.path.exists(self.output))

    def test_summary_reports_semantic_findings_without_publishing(self) -> None:
        """A summary must consume the audit result instead of recollecting semantics."""
        import contextlib
        import io

        finding = StemAuditResult(
            catalogue_model_ids=("mdx:model",),
            reviewed_model_ids=(),
            waived_model_ids=(),
            raw_model_ids=("mdx:model",),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(
                StemAuditDiagnostic(
                    code="reference-drift",
                    model_ids=("mdx:model",),
                    message="fixture reference differs",
                    structural=False,
                ),
            ),
        )
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            self.assertEqual(self._run(["--summary"], audit=finding), 1)

        self.assertIn("## Reference drift", stdout.getvalue())
        self.assertFalse(os.path.exists(self.output))

    def test_summary_reports_disk_drift_separately_and_changes_no_bytes(self) -> None:
        self.assertEqual(self._run([]), 0)
        with open(self.stem, "a", encoding="utf-8") as handle:
            handle.write("stale row\n")
        paths = (self.output, self.ir, self.intent, self.display, self.stem)
        before = {}
        for path in paths:
            with open(path, "rb") as handle:
                before[path] = handle.read()

        self.assertEqual(self._run(["--summary"]), 1)

        for path in paths:
            with self.subTest(path=path), open(path, "rb") as handle:
                self.assertEqual(handle.read(), before[path])

    def test_candidate_row_parity_failure_blocks_write_check_and_summary(self) -> None:
        from unittest import mock

        for argv in ([], ["--check"], ["--summary"]):
            with (
                self.subTest(argv=argv),
                mock.patch.object(
                    render,
                    "stem_semantics_reference_tsv",
                    return_value="not the structured rows\n",
                ),
            ):
                self.assertEqual(self._run(argv), 1)
            self.assertFalse(os.path.exists(self.output))

    def test_help_pins_all_four_exit_codes_and_summary_semantics(self) -> None:
        import contextlib
        import io

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            cli._parse_args(["--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("0  clean snapshot", help_text)
        self.assertIn("1  generated drift or semantic findings", help_text)
        self.assertIn("2  degraded or unusable evidence", help_text)
        self.assertIn("130  interrupted opt-in remote confidence audit", help_text)
        self.assertNotIn("--summary completed", help_text)

    def test_legacy_reference_flags_are_deprecated_no_ops(self) -> None:
        """Compatibility flags must not split the generated artifact bundle."""
        import contextlib
        import io

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(
                self._run(
                    [
                        "--write-tsv",
                        "--write-display-reference",
                        "--write-stem-semantics-reference",
                    ]
                ),
                0,
            )
        self.assertEqual(stderr.getvalue().lower().count("deprecated"), 3)
        self.assertTrue(os.path.isfile(self.stem))

    def test_validated_registry_is_loaded_once_and_renderer_consumes_audit_rows(self) -> None:
        """The renderer cannot reload or independently resolve manifest semantics."""
        from unittest import mock

        from core.model_stem_manifest import BUNDLED_MANIFEST_PATH, load_stem_manifest

        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        seen: list[object] = []
        rendered_rows: list[object] = []

        def render_stems(rows: object) -> str:
            rendered_rows.append(rows)
            return cli.stem_audit.reference_rows_tsv(rows)  # type: ignore[arg-type]

        def audit_stems(*_args: object, **kwargs: object) -> StemAuditResult:
            seen.append(kwargs.get("registry"))
            return self._audit()

        with (
            mock.patch.object(
                cli,
                "load_stem_manifest",
                wraps=load_stem_manifest,
                create=True,
            ) as loader,
            mock.patch.object(
                render,
                "stem_semantics_reference_tsv",
                side_effect=render_stems,
            ),
        ):
            self.assertEqual(self._run([], audit=audit_stems), 0)

        loader.assert_called_once_with(BUNDLED_MANIFEST_PATH)
        self.assertEqual(seen, [registry])
        self.assertEqual(rendered_rows, [()])

    def test_missing_politrees_hash_files_do_not_degrade_a_complete_offline_bundle(self) -> None:
        """Unused hash supplements cannot turn five matching artifacts into exit 2."""
        from unittest import mock

        community_cache = os.path.join(self.tmp, "community-cache")
        unused_hash_cache = os.path.join(self.tmp, "absent-politrees-hashes")
        yaml_cache = os.path.join(self.tmp, "yaml-cache")
        yaml_url = "https://example.invalid/model.yaml"
        os.makedirs(community_cache)
        with open(
            catalogue._cache_path(
                community_cache,
                catalogue._COMMUNITY_MODELS_URL,
                "models.txt",
            ),
            "wb",
        ) as handle:
            handle.write(b"model.ckpt  MDX23C  vocals*, other  Fixture model\n")
        os.makedirs(yaml_cache)
        with open(
            catalogue._cache_path(yaml_cache, yaml_url, "model.yaml"),
            "wb",
        ) as handle:
            handle.write(b"training:\n  instruments: [vocals, other]\n")
        self.entry.config_yaml = "model.yaml"
        self.entry.config_url = yaml_url
        self.entry.metadata_source = "remote_yaml:model.yaml"
        network_calls: list[str] = []

        def record_network(target: object) -> None:
            network_calls.append(str(getattr(target, "full_url", target)))
            raise AssertionError("offline generator requested the network")

        with (
            mock.patch.object(catalogue, "COMMUNITY_CACHE_DIR", community_cache),
            mock.patch.object(catalogue, "YAML_CACHE_DIR", yaml_cache),
            mock.patch("core.mdx_config_fetch._urlopen", side_effect=record_network),
        ):
            context = catalogue._build_catalogue_context(policy=catalogue.OFFLINE_FETCH_POLICY)

        self.assertEqual(network_calls, [])
        self.assertFalse(os.path.exists(unused_hash_cache))
        self.assertEqual(context.unavailable_supplemental_evidence, ())
        self.assertEqual(set(context.community_by_file), {"model.ckpt"})
        informational = StemAuditResult(
            catalogue_model_ids=("mdx:model",),
            reviewed_model_ids=("mdx:model",),
            waived_model_ids=(),
            raw_model_ids=(),
            evidence_counts=CatalogueEvidenceCounts(148, 123, 92, ()),
            diagnostics=(),
            native_to_role_ambiguities=(
                NativeToRoleAmbiguity(
                    normalized_native="vocals",
                    native_spellings=("Vocals", "vocals"),
                    role_ids=("vocal.lead", "vocal.vocals"),
                    model_ids=("mdx:model",),
                    evidence=(),
                ),
            ),
            role_to_native_variants=(),
        )
        self.assertTrue(informational.ok)
        self.assertTrue(informational.structurally_valid)

        self.assertEqual(self._run([], context=context, audit=informational), 0)
        self.assertEqual(self._run(["--check"], context=context, audit=informational), 0)
        for path in (self.output, self.ir, self.intent, self.display, self.stem):
            with self.subTest(path=path):
                self.assertTrue(os.path.isfile(path))


class MalformedManifestCliTests(unittest.TestCase):
    """Normal modes reject a bad manifest before collection or rendering."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-malformed-stem-manifest-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.output = os.path.join(self.tmp, "models-catalogue.md")
        self.intent = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.display = os.path.join(self.tmp, "model_display_reference.tsv")
        self.stem = os.path.join(self.tmp, "model_stem_semantics_reference.tsv")
        self.ir = catalogue._ir_path_for(self.output)
        self.manifest = os.path.join(self.tmp, "bad-manifest.json")
        with open(self.manifest, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 0}, handle)
        self.sentinels = {
            self.output: b"catalogue sentinel\n",
            self.ir: b"ir sentinel\n",
            self.intent: b"intent sentinel\n",
            self.display: b"display sentinel\n",
            self.stem: b"stem sentinel\n",
        }
        for path, data in self.sentinels.items():
            with open(path, "wb") as handle:
                handle.write(data)

    def _assert_manifest_invalid(self, argv: list[str]) -> None:
        import contextlib
        import io
        from pathlib import Path
        from unittest import mock

        stderr = io.StringIO()
        blocked = AssertionError("manifest validation must precede this boundary")
        with (
            mock.patch.object(cli, "OUTPUT_PATH", self.output),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", self.intent),
            mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", self.display),
            mock.patch.object(cli, "STEM_SEMANTICS_REFERENCE_TSV_PATH", self.stem),
            mock.patch.object(
                cli,
                "BUNDLED_MANIFEST_PATH",
                Path(self.manifest),
                create=True,
            ),
            mock.patch.object(
                catalogue,
                "_build_catalogue_context",
                side_effect=blocked,
            ) as context_builder,
            mock.patch.object(catalogue, "collect_entries", side_effect=blocked) as collector,
            mock.patch.object(render, "_render", side_effect=blocked) as catalogue_renderer,
            mock.patch.object(
                render,
                "presentation_reference_audit",
                side_effect=blocked,
            ) as display_renderer,
            mock.patch.object(
                render,
                "stem_semantics_reference_tsv",
                side_effect=blocked,
            ) as stem_renderer,
            mock.patch.object(
                render,
                "render_summary_report",
                side_effect=blocked,
            ) as summary_renderer,
            contextlib.redirect_stderr(stderr),
        ):
            rc = cli.main(argv)

        self.assertEqual(rc, 1)
        lines = stderr.getvalue().splitlines()
        self.assertEqual(len(lines), 1, stderr.getvalue())
        self.assertIn("manifest-invalid", lines[0])
        self.assertNotIn("Traceback", stderr.getvalue())
        for boundary in (
            context_builder,
            collector,
            catalogue_renderer,
            display_renderer,
            stem_renderer,
            summary_renderer,
        ):
            boundary.assert_not_called()
        for path, data in self.sentinels.items():
            with self.subTest(path=path), open(path, "rb") as handle:
                self.assertEqual(handle.read(), data)

    def test_write_rejects_malformed_manifest_before_side_effects(self) -> None:
        self._assert_manifest_invalid([])

    def test_check_rejects_malformed_manifest_before_side_effects(self) -> None:
        self._assert_manifest_invalid(["--check"])

    def test_summary_rejects_malformed_manifest_before_side_effects(self) -> None:
        self._assert_manifest_invalid(["--summary"])


class SidecarTrustTests(unittest.TestCase):
    """The sidecar may only speak for the document it was written with."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-sidecar-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.doc = os.path.join(self.tmp, "models-catalogue.md")

    def _write_doc(self, count: int) -> None:
        with open(self.doc, "w", encoding="utf-8") as handle:
            handle.write(f"- Total catalogue entries: **{count}**\n")

    def _write_sidecar(self, count: int, *, digest: Optional[str] = None) -> None:
        payload: dict = {"schema_version": 1, "entry_count": count}
        if digest is not None:
            payload["document_sha256"] = digest
        with open(catalogue._ir_path_for(self.doc), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_a_sidecar_written_with_this_document_is_trusted(self) -> None:
        self._write_doc(474)
        self._write_sidecar(474, digest=catalogue._document_digest(self.doc))
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_a_stale_sidecar_cannot_lower_the_guard_floor(self) -> None:
        """The exact hazard: a degraded run's sidecar outliving its document."""
        self._write_doc(474)
        self._write_sidecar(88, digest="sha-of-some-other-document")
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_a_sidecar_with_no_digest_is_not_trusted(self) -> None:
        """Written before the cross-check existed; the document is authoritative."""
        self._write_doc(474)
        self._write_sidecar(88)
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_the_sidecar_is_used_when_the_document_has_no_count(self) -> None:
        with open(self.doc, "w", encoding="utf-8") as handle:
            handle.write("a document with no summary line\n")
        self._write_sidecar(412, digest=catalogue._document_digest(self.doc))
        self.assertEqual(cli._previous_entry_count(self.doc), 412)

    def test_a_published_run_writes_a_matching_digest(self) -> None:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.doc))
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "REFERENCE_TSV_PATH",
                    os.path.join(self.tmp, "model_intent_reference.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "DISPLAY_REFERENCE_TSV_PATH",
                    os.path.join(self.tmp, "model_display_reference.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                    os.path.join(self.tmp, "model_stem_semantics_reference.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=_clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue.CatalogueContext()
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                )
            )
            self.assertEqual(cli.main([]), 0)

        with open(catalogue._ir_path_for(self.doc), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["document_sha256"], catalogue._document_digest(self.doc))


class SummaryHonestyTests(unittest.TestCase):
    """A summary of a failed fetch must not read as a clean bill of health."""

    def _dead_report(self):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(mode=RefreshMode.OFFLINE, usable=False)

    def test_an_unusable_snapshot_is_called_out(self) -> None:
        text = render.render_summary_report([], unsupported_count=0, report=self._dead_report())
        self.assertNotIn("Nothing flagged", text)
        self.assertIn("unusable", text.lower())

    def test_an_empty_catalogue_is_called_out_even_without_a_report(self) -> None:
        text = render.render_summary_report([], unsupported_count=0, report=None)
        self.assertNotIn("Nothing flagged", text)
        self.assertIn("no entries", text.lower())

    def test_a_healthy_empty_of_problems_run_still_reads_clean(self) -> None:
        entry = catalogue.ModelEntry(
            source="TRvlvr",
            family="VR Architecture",
            catalogue_label="Good",
            weight_file="g.pth",
            name_intent="vocals",
            metadata_source="bundled_yaml:y.yaml",
        )
        text = render.render_summary_report([entry], unsupported_count=0)
        self.assertIn("Nothing flagged", text)


class EntryMetaOverlayTests(unittest.TestCase):
    def test_fills_blank_stems_target_and_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_KARAOKE

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="MelBand Roformer Karaoke",
            weight_file="kara.ckpt",
            name_intent="unknown",
        )
        meta = EntryMeta(
            label=entry.catalogue_label,
            display="MelBand Roformer — Karaoke",
            arch="MDX",
            stems=["vocals", "other"],
            target_instrument="vocals",
            intent=INTENT_KARAOKE,
        )
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["vocals", "other"])
        self.assertEqual(entry.target_instrument, "vocals")
        self.assertEqual(entry.primary_stem, "vocals")
        self.assertEqual(entry.name_intent, INTENT_KARAOKE)

    def test_does_not_overwrite_resolved_fields_or_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_UNKNOWN

        entry = catalogue.ModelEntry(
            source="extras",
            family="Roformer",
            catalogue_label="Named",
            weight_file="model.ckpt",
            instruments=["drums", "bass"],
            target_instrument="drums",
            primary_stem="drums",
            name_intent="instrumental",
        )
        meta = EntryMeta(
            label=entry.catalogue_label,
            display="Named",
            arch="MDX",
            stems=["vocals"],
            target_instrument="vocals",
            intent=INTENT_UNKNOWN,
        )
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["drums", "bass"])
        self.assertEqual(entry.target_instrument, "drums")
        self.assertEqual(entry.primary_stem, "drums")
        self.assertEqual(entry.name_intent, "instrumental")

        entry.name_intent = "unknown"
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.name_intent, "unknown")


class RenderDisplayTests(unittest.TestCase):
    def test_render_uses_id_aware_display_in_tables_and_detail_headings(self) -> None:
        label = "VR Arch Single Model v5: 1_HP-UVR"
        entry = catalogue.ModelEntry(
            source="extras",
            family="VR Architecture",
            catalogue_label=label,
            weight_file="1_HP-UVR.pth",
            name_intent="instrumental",
            best_result="Instrumental",
            backend_focus="instrumental_primary",
        )

        rendered = render._render([entry])

        self.assertIn("| VR Architecture | VR v5 — HP 1 |", rendered)
        self.assertIn("### VR v5 — HP 1", rendered)
        self.assertNotIn("| VR Architecture | 1_HP-UVR |", rendered)

    def test_summary_uses_id_aware_display(self) -> None:
        entry = catalogue.ModelEntry(
            source="extras",
            family="VR Architecture",
            catalogue_label="VR Arch Single Model v5: 1_HP-UVR",
            weight_file="1_HP-UVR.pth",
            name_intent="instrumental",
        )
        entry.flags = ["review me"]

        rendered = render.render_summary_report([entry])

        self.assertIn("**VR v5 — HP 1** (VR Architecture)", rendered)
        self.assertNotIn("**1_HP-UVR**", rendered)

    def test_quick_reference_keeps_the_complete_projected_display(self) -> None:
        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label=(
                "Mel-Band Roformer Karaoke Fusion Aggressive by Gonzaluigi "
                "[mbr_karaoke_fusion_aggr_gonzaluigi]"
            ),
            weight_file="mbr_karaoke_fusion_aggr_gonzaluigi.ckpt",
            name_intent="karaoke",
        )
        expected = (
            "MelBand Roformer — Karaoke Fusion Aggressive · Gonzaluigi "
            "[mbr_karaoke_fusion_aggr_gonzaluigi]"
        )

        rendered = render._render([entry])
        quick_reference = rendered.split("## Karaoke models", 1)[0]

        self.assertIn(expected, quick_reference)

    def test_render_header_lists_all_sources(self) -> None:
        rendered = render._render([])
        self.assertIn("TRvlvr + Politrees + extras + mvsepless", rendered)
        self.assertIn(
            "catalogue helper summarizing primary/target",
            rendered,
        )
        self.assertNotIn("what `ModelConfig` uses as `primary_stem`", rendered)

    def test_parse_args_offline(self) -> None:
        args = cli._parse_args(["--offline"])
        self.assertTrue(args.offline)


class FetchHelperTests(unittest.TestCase):
    def test_fetch_cached_uses_core_urlopen(self) -> None:
        import tempfile
        from unittest.mock import patch

        class _Resp:
            def read(self) -> bytes:
                return b'{"ok": true}'

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("core.mdx_config_fetch._urlopen", return_value=_Resp()),
        ):
            path = catalogue._fetch_cached("https://example.invalid/x.json", tmp, "x.json")
            if path is None:
                self.fail("expected a cached file")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"ok": true}')

    def test_load_yaml_meta_uses_generator_cache_not_runtime_config_storage(self) -> None:
        import tempfile
        from unittest.mock import patch

        yaml_name = "zz_core_fetch_probe.yaml"
        body = b"training:\n  instruments: [vocals, other]\n  target_instrument: vocals\n"

        class _Response:
            def read(self) -> bytes:
                return body

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, "generator-cache")
            runtime_dir = os.path.join(tmp, "runtime-configs")
            with (
                patch.object(catalogue, "YAML_CACHE_DIR", cache_dir),
                patch.object(catalogue.paths, "MDX_C_CONFIG_PATH", runtime_dir),
                patch(
                    "core.mdx_config_fetch.fetch_mdx_config_url",
                    side_effect=AssertionError("runtime config fetch used"),
                ),
                patch("core.mdx_config_fetch._urlopen", return_value=_Response()),
            ):
                instruments, target, _arch, source, _digest = catalogue._load_yaml_meta(
                    yaml_name, "https://example.invalid/x.yaml"
                )

            self.assertEqual(instruments, ["vocals", "other"])
            self.assertEqual(target, "vocals")
            self.assertEqual(source, f"remote_yaml:{yaml_name}")
            self.assertTrue(
                os.path.isfile(
                    catalogue._cache_path(
                        cache_dir,
                        "https://example.invalid/x.yaml",
                        yaml_name,
                    )
                )
            )
            self.assertFalse(os.path.exists(runtime_dir))


class StemConfidenceAuditModeTests(unittest.TestCase):
    """The remote confidence review is isolated from catalogue publication."""

    def test_audit_mode_exposes_the_legacy_review_filters(self) -> None:
        args = cli._parse_args(
            [
                "--audit-stem-confidence",
                "--guessed-only",
                "--only",
                "karaoke",
                "--limit",
                "3",
                "--json",
                "/tmp/confidence.json",
                "--quiet",
                "--no-cache",
            ]
        )

        self.assertTrue(args.audit_stem_confidence)
        self.assertTrue(args.guessed_only)
        self.assertEqual(args.only, "karaoke")
        self.assertEqual(args.limit, 3)
        self.assertEqual(args.json_path, "/tmp/confidence.json")
        self.assertTrue(args.quiet)
        self.assertTrue(args.no_hash_cache)

    def test_audit_only_filters_are_rejected_outside_audit_mode(self) -> None:
        with self.assertRaises(SystemExit):
            cli._parse_args(["--guessed-only"])

    def test_offline_rejects_hash_cache_bypass(self) -> None:
        with self.assertRaises(SystemExit):
            cli._parse_args(["--audit-stem-confidence", "--offline", "--no-cache"])

    def test_audit_mode_does_not_collect_or_publish_catalogue_artifacts(self) -> None:
        import contextlib
        import io
        from unittest import mock

        with (
            mock.patch.object(
                cli.stem_audit,
                "run_stem_confidence_audit",
                return_value=0,
            ) as audit,
            mock.patch.object(
                catalogue,
                "_build_catalogue_context",
                side_effect=AssertionError("publication collection must not run"),
            ),
            mock.patch.object(
                cli,
                "load_stem_manifest",
                side_effect=AssertionError("confidence audit must not load publication manifest"),
                create=True,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.main(["--audit-stem-confidence", "--quiet"]), 0)

        self.assertTrue(audit.called)

    def test_offline_refresh_reuses_warm_source_config_and_hash_caches(self) -> None:
        import contextlib
        import io
        import tempfile
        from types import SimpleNamespace
        from unittest import mock

        target = SimpleNamespace(
            entry_id="warm",
            label="Warm model",
            config_url="https://example.test/warm.yaml",
            checkpoint_url="https://example.test/warm.ckpt",
            is_bv_model=False,
        )
        source = SimpleNamespace(
            state=SimpleNamespace(content=SimpleNamespace(payload={"warm": {}}))
        )
        source_calls: list[Any] = []
        source.load = lambda **kwargs: source_calls.append(kwargs["mode"])
        coordinator = SimpleNamespace(source=lambda _source_id: source, close=lambda: None)
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "hashes.json")
            cache = cli.stem_audit.HashCache(cache_path)
            cache.put(
                target.checkpoint_url,
                cli.stem_audit.HashLookup(digest="known", status="ok"),
            )
            cache.save()
            with (
                mock.patch(
                    "core.catalogue_coordinator.CatalogueCoordinator",
                    return_value=coordinator,
                ),
                mock.patch(
                    "scripts.model_tool_support.iter_catalogue_targets",
                    return_value=iter([target]),
                ),
                mock.patch.object(
                    cli.stem_audit, "default_hash_cache_path", return_value=cache_path
                ),
                mock.patch.object(
                    cli.stem_audit, "_curated_hash_table", return_value={"known": {}}
                ),
                mock.patch("catalogue.stem_audit.os.path.isfile", return_value=True),
                mock.patch(
                    "core.model_data.load_mdx_c_config",
                    return_value={"training": {"instruments": ["vocals", "other"]}},
                ) as config_load,
                mock.patch(
                    "catalogue.collect._fetch_yaml_bytes",
                    side_effect=AssertionError("offline config fetch"),
                ),
                mock.patch(
                    "scripts.model_tool_support.checkpoint_tail_hash",
                    side_effect=AssertionError("offline checkpoint fetch"),
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    cli.main(["--audit-stem-confidence", "--offline", "--refresh", "--quiet"]),
                    0,
                )

        config_load.assert_called_once()
        self.assertEqual([mode.value for mode in source_calls], ["offline"])


if __name__ == "__main__":
    unittest.main()
