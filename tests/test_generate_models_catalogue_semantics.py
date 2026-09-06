"""Generator semantics behavior."""

import unittest
from typing import cast

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as fixtures

from catalogue import collect as catalogue
from catalogue import config_evidence as catalogue_config_evidence
from catalogue import entry_rules as catalogue_entry_rules
from catalogue import evidence as catalogue_evidence
from catalogue import render
from catalogue import types as catalogue_types

from core.stem_roles import (
    ModelStemSemantics,
    SemanticStemOutput,
    StemId,
    StemProcessingContext,
    StemProduction,
    StemReviewStatus,
    StemRoleId,
)




# isort: on

class RuntimeStemSignatureTests(unittest.TestCase):
    def test_exact_non_config_signatures_outrank_conflicting_summary_hints(self) -> None:
        fixtures = (
            (
                "demucs:htdemucs_6s",
                ("summary-drums", "summary-vocals"),
                ("drums", "bass", "other", "vocals", "guitar", "piano"),
            ),
            (
                "vr:UVR-BVE-4B_SN-44100-1",
                ("Lead Only",),
                ("Vocals", "Instrumental"),
            ),
        )

        for model_id, hints, expected in fixtures:
            with self.subTest(model_id=model_id):
                self.assertEqual(catalogue_evidence.reviewed_stem_signature(model_id, hints), expected)
                self.assertEqual(catalogue_evidence.runtime_stem_signature(model_id, hints), expected)

    def test_config_backed_signature_keeps_parsed_config_precedence(self) -> None:
        self.assertEqual(
            catalogue_evidence.reviewed_stem_signature(
                "mdx:mbr_guitar_becruily",
                ("Live Config A", "Live Config B"),
            ),
            ("Live Config A", "Live Config B"),
        )

    def test_reviewed_non_config_signature_ignores_incidental_config_name(self) -> None:
        from core.model_manifest import load_model_manifest_document

        document = fixtures._generator_manifest_document()
        del document["models"]["mdx:model"]["config_evidence"]
        registry = load_model_manifest_document(document).stems

        self.assertEqual(
            catalogue_evidence.reviewed_stem_signature(
                "mdx:model",
                ("Config A", "Config B"),
                registry=registry,
                evidence_uses_config=True,
                reviewed_non_config_ids={"mdx:model"},
            ),
            ("Vocals",),
        )

    def test_all_24_exact_demucs_records_have_generator_signatures(self) -> None:
        from core.model_manifest.stems import stem_semantics_registry

        demucs_ids = tuple(
            model_id
            for model_id in stem_semantics_registry().models
            if model_id.startswith("demucs:")
        )

        self.assertEqual(len(demucs_ids), 24)
        self.assertTrue(
            all(catalogue_evidence.reviewed_stem_signature(model_id, ()) for model_id in demucs_ids)
        )

    def test_reviewed_collection_evidence_removes_exact_three_guess_false_positives(self) -> None:
        from core.model_stem_manifest import load_bundled_stem_semantics

        entries = [
            catalogue_types.ModelEntry(
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
        reconcile = getattr(catalogue_evidence, "reconcile_stem_semantics", None)
        self.assertIsNotNone(reconcile)
        assert reconcile is not None
        unreviewed = catalogue_types.ModelEntry(
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
            cast(catalogue_types.ReconciledStemEvidence, entry.stem_semantics) for entry in entries
        ]
        unreviewed_semantics = cast(catalogue_types.ReconciledStemEvidence, unreviewed.stem_semantics)

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
        exact = catalogue_evidence.runtime_stem_reconciliation(
            "mdx:MDX23C-8KFFT-InstVoc_HQ",
            ("Vocals", "Instrumental"),
            config_yaml="model_2_stem_full_band_8k.yaml",
            config_sha256=digest,
            metadata_source="bundled_yaml:model_2_stem_full_band_8k.yaml",
        )
        missing = catalogue_evidence.runtime_stem_reconciliation(
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
        instruments, target, _arch, source, digest = catalogue_config_evidence._load_yaml_meta(
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
            catalogue_evidence.runtime_stem_signature(
                "mdx:UVR_MDXNET_KARA_2",
                ("other", "vocals"),
                target_instrument="other",
                metadata_source="community_models.txt",
            ),
            ("Instrumental", "Vocals"),
        )

    def test_yaml_target_projects_the_model_config_native_inventory(self) -> None:
        self.assertEqual(
            catalogue_evidence.runtime_stem_signature(
                "mdx:bs_bass_xlancer",
                ("bass", "other"),
                target_instrument="bass",
                metadata_source="bundled_yaml:bs_bass_xlancer_config.yaml",
            ),
            ("bass",),
        )
        self.assertEqual(
            catalogue_evidence.runtime_stem_signature(
                "mdx:bs_karaoke_gabox",
                ("vocals", "other"),
                target_instrument="vocals",
                metadata_source="remote_yaml:bs_karaoke_gabox_config.yaml",
            ),
            ("vocals",),
        )

    def test_community_target_hint_does_not_rewrite_runtime_inventory(self) -> None:
        self.assertEqual(
            catalogue_evidence.runtime_stem_signature(
                "mdx:community-only",
                ("Vocals", "Instrumental"),
                target_instrument="Vocals",
                metadata_source="community_models.txt",
            ),
            ("Vocals", "Instrumental"),
        )


class ReviewedResultProjectionTests(unittest.TestCase):
    """Reviewed routes, not pre-review guesses, own published result prose."""

    def _bundled_projection(self, model_id: str) -> catalogue_types.ReviewedResultProjection:
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
        return catalogue_evidence._reviewed_result_projection((semantics,), registry)

    def _explicit_secondary_projection(self) -> catalogue_types.ReviewedResultProjection:
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
        return catalogue_evidence._reviewed_result_projection((semantics,), registry)

    def _pair_secondary_projection(self) -> catalogue_types.ReviewedResultProjection:
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
        return catalogue_evidence._reviewed_result_projection((semantics,), registry)

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
                catalogue_types.ModelEntry(
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
                catalogue_evidence.reconcile_stem_semantics(
                    [entry],
                    registry=load_bundled_stem_semantics(),
                )
                semantics = cast(catalogue_types.ReconciledStemEvidence, entry.stem_semantics)
                self.assertFalse(semantics.reviewed)
                self.assertEqual(entry.best_result, best_result)
                self.assertEqual(entry.ui_export_note, ui_export_note)

    def _entries(self) -> list[catalogue_types.ModelEntry]:
        from core.model_stem_manifest import load_bundled_stem_semantics

        entries = [
            catalogue_types.ModelEntry(
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
            catalogue_types.ModelEntry(
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

        catalogue_evidence.reconcile_stem_semantics(
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
        entry = catalogue_types.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="MelBand Roformer Kim | Inst v1 by Unwa",
            weight_file="model.ckpt",
            instruments=["other", "vocals"],
            stem_count=2,
        )
        self.assertIn("Vocals / Instrumental", catalogue_entry_rules._ui_note(entry))

    def test_four_stem_vocals_other_uses_subset_row_note(self):
        entry = catalogue_types.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="4-stems SCNet Large",
            weight_file="model.ckpt",
            instruments=["Drums", "Bass", "Other", "Vocals"],
            stem_count=4,
            name_intent="multi_stem",
        )
        self.assertEqual(catalogue_entry_rules._ui_note(entry), "UI: per-stem subset or focus row")

    def test_special_fx_best_result_and_focus(self):
        entry = catalogue_types.ModelEntry(
            source="test",
            family="VR Architecture",
            catalogue_label="UVR-DeNoise by FoxJoy",
            weight_file="UVR-DeNoise.pth",
            primary_stem="noise",
            name_intent="special_fx",
            metadata_source="community_models.txt",
        )
        catalogue_entry_rules._finalize_entry(entry)
        self.assertIn("Noise", entry.best_result)
        self.assertTrue(entry.backend_focus.startswith("special_fx_primary:"))
        self.assertIn("complement", entry.ui_export_note)

    def test_karaoke_2_gets_karaoke_backend_focus(self):
        entry = catalogue_types.ModelEntry(
            source="test",
            family="MDX-Net ONNX",
            catalogue_label="MDX-Net Model: UVR-MDX-NET Karaoke 2",
            weight_file="UVR_MDXNET_KARA_2.onnx",
            primary_stem="Instrumental",
            name_intent="karaoke",
            metadata_source="community_models.txt",
        )
        catalogue_entry_rules._finalize_entry(entry)
        self.assertTrue(entry.is_karaoke)
        self.assertEqual(entry.backend_focus, "karaoke_instrumental_primary")

    def test_specialty_stem_flags_old_vocals_mismatch(self):
        entry = catalogue_types.ModelEntry(
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
        flags = catalogue_entry_rules._flag_mismatches(entry)
        self.assertTrue(any("specialty 2-stem" in flag for flag in flags))


class FabricatedFlagTests(unittest.TestCase):
    """Metadata that cannot resolve a backend must not produce mismatch flags."""

    def test_intent_alone_is_not_resolved_metadata(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue_types.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Model",
            weight_file="m.ckpt",
            name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue_entry_rules._apply_entry_meta(
            entry, EntryMeta(label="L", display="L", arch="Roformer", intent="vocals")
        )
        self.assertEqual(entry.metadata_source, "unavailable")

    def test_stems_still_count_as_resolved_metadata(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue_types.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Model",
            weight_file="m.ckpt",
        )
        entry.metadata_source = "unavailable"
        catalogue_entry_rules._apply_entry_meta(
            entry,
            EntryMeta(label="L", display="L", arch="Roformer", stems=["vocals", "other"]),
        )
        self.assertEqual(entry.metadata_source, "catalogue_meta")

    def test_unknown_backend_focus_produces_no_mismatch_flags(self) -> None:
        """You cannot detect a mismatch against a backend you could not determine."""
        entry = catalogue_types.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Model",
            weight_file="m.ckpt",
            name_intent="vocals",
        )
        entry.metadata_source = "catalogue_meta"
        entry.backend_focus = "unknown"
        self.assertEqual(catalogue_entry_rules._flag_mismatches(entry), [])

    def test_intent_only_entry_ends_up_unflagged(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue_types.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Model",
            weight_file="m.ckpt",
            name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue_entry_rules._apply_entry_meta(
            entry, EntryMeta(label="L", display="L", arch="Roformer", intent="vocals")
        )
        catalogue_entry_rules._finalize_entry(entry)
        self.assertEqual(entry.flags, [])
