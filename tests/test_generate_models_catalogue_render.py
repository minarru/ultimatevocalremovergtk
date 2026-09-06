"""Generator render behavior."""

import json
import os
import tempfile
import unittest

# isort: off
# Load script imports through the shared fixture bootstrap.
from tests import generator_fixtures as fixtures

from catalogue import collect as catalogue
from catalogue import render
from catalogue import types as catalogue_types
from catalogue.audit_types import (
    STEM_SEMANTICS_REFERENCE_HEADERS,
)

from core.model_stem_manifest import load_stem_manifest_document




# isort: on

cli = fixtures.cli

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
                entry = catalogue_types.ModelEntry(
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
        entry = catalogue_types.ModelEntry(
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
            catalogue_types.ModelEntry(
                source="TRvlvr",
                family="VR Architecture",
                catalogue_label="VR Arch Single Model v5: 5_HP-Karaoke-UVR",
                weight_file="5_HP-Karaoke-UVR.pth",
            ),
            catalogue_types.ModelEntry(
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
        entry = catalogue_types.ModelEntry(
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
        entry = catalogue_types.ModelEntry(
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
        entry = catalogue_types.ModelEntry(
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
        entry = catalogue_types.ModelEntry(
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
        alpha = catalogue_types.ModelEntry(
            source="test",
            family="MDX-Net",
            catalogue_label="Alpha",
            weight_file="alpha.ckpt",
        )
        zulu = catalogue_types.ModelEntry(
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
        composed = catalogue_types.ModelEntry(
            source="test",
            family="MDX-Net",
            catalogue_label="Caf\u00e9",
            weight_file="composed.ckpt",
        )
        decomposed = catalogue_types.ModelEntry(
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
        entry = catalogue_types.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="SCnet: Large",
            weight_file="scnet_large.ckpt",
        )

        rendered = render.presentation_reference_tsv([entry])

        self.assertTrue(all(line == line.rstrip() for line in rendered.splitlines()))


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

    def test_reportless_warm_run_retains_trusted_published_provenance(self) -> None:
        from core.catalogue_types import RefreshMode, RefreshReport, SourceId

        report = RefreshReport(
            mode=RefreshMode.FORCE,
            succeeded=(
                SourceId.EXTRAS,
                SourceId.UPSTREAM,
                SourceId.POLITREES,
                SourceId.MVSEPLESS,
            ),
            upstream_live=True,
            usable=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            document = os.path.join(directory, "models-catalogue.md")
            text = render._render([], unsupported_count=0, report=report)
            with open(document, "w", encoding="utf-8") as handle:
                handle.write(text)
            with open(catalogue._ir_path_for(document), "w", encoding="utf-8") as handle:
                json.dump(
                    catalogue.build_ir(
                        [],
                        report=report,
                        unsupported_count=0,
                        document_sha256=catalogue._document_digest(document),
                    ),
                    handle,
                )

            retained = cli._retained_refresh_report(document)

        self.assertIsNotNone(retained)
        self.assertEqual(retained.mode, RefreshMode.FORCE)
        self.assertEqual(set(retained.succeeded), set(report.succeeded))
        self.assertTrue(retained.upstream_live)
        warm_text = render._render([], unsupported_count=0, report=retained)
        self.assertIn("- Snapshot mode: `force`", warm_text)
        self.assertIn("- Source upstream live: True", warm_text)

    def test_intent_source_prose_excludes_unused_hash_supplements(self) -> None:
        """Removing the fetch while retaining its provenance claim is misleading."""
        text = render._render([], unsupported_count=0, report=self._report())

        self.assertIn("YAML metadata", text)
        self.assertIn("community", text)
        self.assertNotIn("yaml/hash metadata", text)
        self.assertNotIn("Politrees model_data", text)
        self.assertNotIn("Cache politrees", text)


class StemSemanticsReferenceRenderTests(unittest.TestCase):
    def test_provenance_prefix_and_waiver_projection_preserve_review_columns(self) -> None:
        entry = catalogue_types.ModelEntry(
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
            catalogue_types.CatalogueContext(),
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
            catalogue_types.ModelEntry(
                source="fixture-source",
                family="Roformer",
                catalogue_label="Fixture",
                weight_file="fixture.ckpt",
                primary_stem="Lead",
                instruments=["Lead", "Backing", "Instrumental"],
            ),
            catalogue_types.ModelEntry(
                source="fixture-source",
                family="Apollo",
                catalogue_label="Restoration fixture",
                weight_file="restoration.onnx",
                arch="Apollo execution",
            ),
        ]

        audit = cli.stem_audit.audit_catalogue_stems(
            entries,
            catalogue_types.CatalogueContext(),
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


class RenderDisplayTests(unittest.TestCase):
    def test_render_uses_id_aware_display_in_tables_and_detail_headings(self) -> None:
        label = "VR Arch Single Model v5: 1_HP-UVR"
        entry = catalogue_types.ModelEntry(
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
        entry = catalogue_types.ModelEntry(
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
        entry = catalogue_types.ModelEntry(
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
