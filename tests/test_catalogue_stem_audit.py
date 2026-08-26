"""Focused tests for the structured, collection-free catalogue stem audit."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from catalogue import collect  # noqa: E402
from catalogue import stem_audit as stem_audit_module  # noqa: E402
from catalogue.stem_audit import (  # noqa: E402
    STEM_SEMANTICS_REFERENCE_HEADERS,
    StemAuditDiagnostic,
    StemAuditResult,
    audit_catalogue_stems,
)

from core.model_stem_manifest import StemPairDefinition, StemSemanticsRegistry  # noqa: E402
from core.stem_roles import (  # noqa: E402
    SemanticStemOutput,
    StemId,
    StemProcessingContext,
    StemProduction,
    StemRoleDefinition,
    StemRoleFamily,
    StemRoleId,
)

VOCALS = StemRoleId("vocal.vocals")
INSTRUMENTAL = StemRoleId("mix.instrumental")
BASS = StemRoleId("instrument.bass")
NO_BASS = StemRoleId("instrument.bass_removed")


def _role(
    role_id: StemRoleId,
    display: str,
    tag: str,
    family: StemRoleFamily,
) -> StemRoleDefinition:
    return StemRoleDefinition(role_id, display, tag, family)


def _native(name: str, role: StemRoleId) -> SemanticStemOutput:
    return SemanticStemOutput(
        native=StemId(name),
        role=role,
        production=StemProduction.NATIVE,
        backend_primary=False,
        logical_primary=False,
    )


def _derived(role: StemRoleId, source_role: StemRoleId) -> SemanticStemOutput:
    return SemanticStemOutput(
        native=None,
        role=role,
        production=StemProduction.DERIVED,
        backend_primary=False,
        logical_primary=False,
        complement_of=source_role,
    )


def _context(
    logical_primary: StemRoleId,
    *outputs: SemanticStemOutput,
) -> SimpleNamespace:
    return SimpleNamespace(logical_primary=logical_primary, outputs=outputs)


def _declaration(
    signature: tuple[str, ...],
    full_mix: SimpleNamespace,
    *,
    vocal_split: SimpleNamespace | None = None,
) -> SimpleNamespace:
    contexts = {StemProcessingContext.FULL_MIX: full_mix}
    if vocal_split is not None:
        contexts[StemProcessingContext.VOCAL_SPLIT] = vocal_split
    return SimpleNamespace(
        native_signature=signature,
        intent="vocals",
        contexts=contexts,
        evidence="fixture",
    )


def _entry(
    basename: str,
    *,
    instruments: tuple[str, ...] = ("Vocals", "Instrumental"),
    primary: str = "Vocals",
    target: str = "",
    metadata_source: str = "community_models.txt",
    karaoke: bool = False,
) -> collect.ModelEntry:
    return collect.ModelEntry(
        source="fixture",
        family="MDX-Net ONNX",
        catalogue_label=basename,
        weight_file=f"{basename}.onnx",
        instruments=list(instruments),
        primary_stem=primary,
        target_instrument=target,
        metadata_source=metadata_source,
        is_karaoke=karaoke,
    )


def _registry(
    models: dict[str, object],
    *,
    roles: dict[StemRoleId, StemRoleDefinition] | None = None,
    pairs: dict[str, object] | None = None,
    waivers: dict[str, str] | None = None,
) -> StemSemanticsRegistry:
    selected_roles = roles or {
        VOCALS: _role(VOCALS, "Vocals", "Vocals", StemRoleFamily.VOCAL),
        INSTRUMENTAL: _role(
            INSTRUMENTAL,
            "Instrumental",
            "Instrumental",
            StemRoleFamily.MIX,
        ),
    }
    selected_pairs = pairs
    if selected_pairs is None:
        selected_pairs = {
            "pair.vocals_instrumental": StemPairDefinition(
                "pair.vocals_instrumental",
                "Vocals / Instrumental",
                (VOCALS, INSTRUMENTAL),
            )
        }
    return StemSemanticsRegistry(
        selected_roles,
        selected_pairs,  # type: ignore[arg-type]
        models,  # type: ignore[arg-type]
        waivers or {},
    )


def _codes(result: StemAuditResult) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def _diagnostic(result: StemAuditResult, code: str) -> StemAuditDiagnostic:
    return next(diagnostic for diagnostic in result.diagnostics if diagnostic.code == code)


class StructuredCatalogueStemAuditTests(unittest.TestCase):
    def test_uses_supplied_entries_and_context_without_collecting_again(self) -> None:
        entry = _entry("fixture")
        registry = _registry(
            {
                "mdx:fixture": _declaration(
                    ("Vocals", "Instrumental"),
                    _context(
                        VOCALS,
                        _native("Vocals", VOCALS),
                        _native("Instrumental", INSTRUMENTAL),
                    ),
                )
            }
        )

        with (
            patch.object(collect, "collect_entries", side_effect=AssertionError("second collect")),
            patch.object(
                collect,
                "_build_catalogue_context",
                side_effect=AssertionError("second context build"),
            ),
        ):
            result = audit_catalogue_stems(
                [entry],
                collect.CatalogueContext(),
                expected_reference_text="same reference",
                actual_reference_text="same reference",
                registry=registry,
            )

        self.assertEqual(result.catalogue_model_ids, ("mdx:fixture",))
        self.assertEqual(result.reviewed_model_ids, ("mdx:fixture",))
        self.assertNotIn("catalogue-unreviewed", _codes(result))
        self.assertNotIn("native-signature", _codes(result))

    def test_catalogue_coverage_diagnostics_name_missing_and_orphan_ids(self) -> None:
        registry = _registry(
            {
                "mdx:reviewed": _declaration(
                    ("Vocals", "Instrumental"),
                    _context(
                        VOCALS,
                        _native("Vocals", VOCALS),
                        _native("Instrumental", INSTRUMENTAL),
                    ),
                ),
                "mdx:orphan": _declaration(
                    ("Vocals", "Instrumental"),
                    _context(
                        VOCALS,
                        _native("Vocals", VOCALS),
                        _native("Instrumental", INSTRUMENTAL),
                    ),
                ),
            },
            waivers={"mdx:waived": "reviewed exception"},
        )

        result = audit_catalogue_stems(
            [_entry("reviewed"), _entry("missing"), _entry("waived")],
            collect.CatalogueContext(),
            expected_reference_text="same",
            actual_reference_text="same",
            registry=registry,
        )

        self.assertEqual(
            _diagnostic(result, "catalogue-unreviewed").model_ids,
            ("mdx:missing",),
        )
        self.assertEqual(
            _diagnostic(result, "manifest-orphan").model_ids,
            ("mdx:orphan",),
        )
        self.assertEqual(result.raw_model_ids, ("mdx:missing",))
        self.assertEqual(result.waived_model_ids, ("mdx:waived",))

    def test_signature_and_context_findings_keep_model_and_context_fields(self) -> None:
        invalid_context = _context(
            INSTRUMENTAL,
            _native("Lead", VOCALS),
            _native("Backing", VOCALS),
        )
        registry = _registry({"mdx:broken": _declaration(("Lead", "Backing"), invalid_context)})

        result = audit_catalogue_stems(
            [_entry("broken")],
            collect.CatalogueContext(),
            expected_reference_text="same",
            actual_reference_text="same",
            registry=registry,
        )

        signature = _diagnostic(result, "native-signature")
        self.assertEqual(signature.model_ids, ("mdx:broken",))
        self.assertEqual(signature.expected, ("Lead", "Backing"))
        self.assertEqual(signature.actual, ("Vocals", "Instrumental"))
        duplicate = _diagnostic(result, "context-duplicate-role")
        self.assertEqual(duplicate.model_ids, ("mdx:broken",))
        self.assertEqual(duplicate.context, StemProcessingContext.FULL_MIX)
        self.assertEqual(
            _diagnostic(result, "context-logical-primary").model_ids,
            ("mdx:broken",),
        )
        self.assertIn("context-unreviewed", _codes(result))

    def test_target_projection_requires_one_native_target_and_dependent_complement(self) -> None:
        roles = {
            BASS: _role(BASS, "Bass", "Bass", StemRoleFamily.INSTRUMENT),
            NO_BASS: _role(
                NO_BASS,
                "No Bass",
                "No Bass",
                StemRoleFamily.RESIDUAL,
            ),
        }
        registry = _registry(
            {
                "mdx:target": _declaration(
                    ("bass", "other"),
                    _context(
                        BASS,
                        _native("bass", BASS),
                        _native("other", NO_BASS),
                    ),
                )
            },
            roles=roles,
            pairs={},
        )

        result = audit_catalogue_stems(
            [
                _entry(
                    "target",
                    instruments=("bass", "other"),
                    primary="bass",
                    target="bass",
                    metadata_source="bundled_yaml:target.yaml",
                )
            ],
            collect.CatalogueContext(),
            expected_reference_text="same",
            actual_reference_text="same",
            registry=registry,
        )

        for code in (
            "target-runtime-signature",
            "target-native-output",
            "target-derived-complement",
        ):
            diagnostic = _diagnostic(result, code)
            self.assertEqual(diagnostic.model_ids, ("mdx:target",))
            self.assertEqual(diagnostic.context, StemProcessingContext.FULL_MIX)
        signature = _diagnostic(result, "target-runtime-signature")
        self.assertEqual(signature.expected, ("bass", "other"))
        self.assertEqual(signature.actual, ("bass",))

    def test_vocal_split_findings_name_each_exact_model(self) -> None:
        full_mix = _context(
            VOCALS,
            _native("Vocals", VOCALS),
            _native("Instrumental", INSTRUMENTAL),
        )
        registry = _registry(
            {
                "mdx:karaoke": _declaration(("Vocals", "Instrumental"), full_mix),
                "mdx:plain": _declaration(
                    ("Vocals", "Instrumental"),
                    full_mix,
                    vocal_split=full_mix,
                ),
            }
        )

        result = audit_catalogue_stems(
            [_entry("karaoke", karaoke=True), _entry("plain")],
            collect.CatalogueContext(),
            expected_reference_text="same",
            actual_reference_text="same",
            registry=registry,
        )

        self.assertEqual(
            _diagnostic(result, "missing-vocal-split").model_ids,
            ("mdx:karaoke",),
        )
        self.assertEqual(
            _diagnostic(result, "unexpected-vocal-split").model_ids,
            ("mdx:plain",),
        )

    def test_role_collisions_and_incomplete_pairs_report_affected_models(self) -> None:
        duplicate = StemRoleId("vocal.duplicate")
        missing = StemRoleId("vocal.missing")
        roles = {
            VOCALS: _role(VOCALS, "Vocals", "Voice", StemRoleFamily.VOCAL),
            duplicate: _role(
                duplicate,
                "ＶＯＣＡＬＳ",
                "voice",
                StemRoleFamily.VOCAL,
            ),
        }
        registry = _registry(
            {
                "mdx:collision": _declaration(
                    ("Vocals", "Duplicate"),
                    _context(
                        VOCALS,
                        _native("Vocals", VOCALS),
                        _native("Duplicate", duplicate),
                    ),
                )
            },
            roles=roles,
            pairs={
                "pair.incomplete": SimpleNamespace(
                    id="pair.incomplete",
                    display="Incomplete",
                    roles=(VOCALS, missing),
                )
            },
        )

        result = audit_catalogue_stems(
            [_entry("collision", instruments=("Vocals", "Duplicate"))],
            collect.CatalogueContext(),
            expected_reference_text="same",
            actual_reference_text="same",
            registry=registry,
        )

        self.assertEqual(
            _diagnostic(result, "role-display-collision").model_ids,
            ("mdx:collision",),
        )
        self.assertEqual(
            _diagnostic(result, "role-tag-collision").model_ids,
            ("mdx:collision",),
        )
        pair = _diagnostic(result, "pair-incomplete")
        self.assertEqual(pair.model_ids, ("mdx:collision",))
        self.assertEqual(pair.expected, (str(VOCALS), str(missing)))
        self.assertEqual(pair.actual, (str(VOCALS),))

    def test_incomplete_resolved_pair_projection_reports_exact_model_and_context(self) -> None:
        registry = _registry(
            {
                "mdx:pair-context": _declaration(
                    ("Lead", "Backing"),
                    _context(
                        VOCALS,
                        _native("Lead", VOCALS),
                        _native("Backing", INSTRUMENTAL),
                    ),
                )
            }
        )

        result = audit_catalogue_stems(
            [_entry("pair-context")],
            collect.CatalogueContext(),
            expected_reference_text="same",
            actual_reference_text="same",
            registry=registry,
        )

        self.assertEqual(
            result.diagnostics_with_code("pair-context-incomplete"),
            (
                StemAuditDiagnostic(
                    code="pair-context-incomplete",
                    model_ids=("mdx:pair-context",),
                    context=StemProcessingContext.FULL_MIX,
                    message=("pair.vocals_instrumental resolved without every declared pair role"),
                    expected=(str(VOCALS), str(INSTRUMENTAL)),
                    actual=(),
                ),
            ),
        )

    def test_evidence_and_reference_drift_are_structured_not_rendered_text(self) -> None:
        entry = _entry("fixture")
        registry = _registry(
            {
                "mdx:fixture": _declaration(
                    ("Vocals", "Instrumental"),
                    _context(
                        VOCALS,
                        _native("Vocals", VOCALS),
                        _native("Instrumental", INSTRUMENTAL),
                    ),
                )
            }
        )

        result = audit_catalogue_stems(
            [entry],
            collect.CatalogueContext(),
            expected_reference_text="expected\trow\n",
            actual_reference_text="actual\trow\n",
            registry=registry,
        )

        evidence = _diagnostic(result, "evidence-count")
        self.assertEqual(evidence.model_ids, ("mdx:fixture",))
        self.assertEqual(evidence.expected, ("148", "123", "92"))
        self.assertEqual(evidence.actual, ("6", "6", "1"))
        drift = _diagnostic(result, "reference-drift")
        self.assertEqual(drift.model_ids, ("mdx:fixture",))
        self.assertFalse(drift.structural)
        self.assertFalse(result.reference_matches)
        self.assertTrue(result.structurally_valid is False)
        self.assertNotIn("expected\trow", drift.message)

    def test_reference_header_contract_appends_dependency_and_default_columns(self) -> None:
        self.assertEqual(
            STEM_SEMANTICS_REFERENCE_HEADERS,
            (
                "model_id",
                "model_display",
                "native_signature",
                "processing_context",
                "native_stem",
                "production",
                "backend_primary",
                "backend_target",
                "logical_primary",
                "role_id",
                "canonical_name",
                "filename_tag",
                "pair_id",
                "intent",
                "intent_source",
                "review_status",
                "evidence_or_waiver",
                "complement_of",
                "derived_from",
                "selected_by_default",
            ),
        )

    def test_relationship_projections_are_model_specific_filtered_and_deterministic(self) -> None:
        """Reordering entries cannot add waivers, orphans, or derived outputs."""
        models: dict[str, object] = {
            "mdx:alpha": _declaration(
                (" Vocals ",),
                _context(VOCALS, _native(" Vocals ", VOCALS)),
                vocal_split=_context(VOCALS, _native(" Vocals ", VOCALS)),
            ),
            "mdx:beta": _declaration(
                ("vocals",),
                _context(INSTRUMENTAL, _native("vocals", INSTRUMENTAL)),
            ),
            "mdx:lead": _declaration(
                ("Lead Vocal",),
                _context(VOCALS, _native("Lead Vocal", VOCALS)),
            ),
            "mdx:case": _declaration(
                ("VOCALS",),
                _context(VOCALS, _native("VOCALS", VOCALS)),
            ),
            "mdx:derived": _declaration(
                ("Track",),
                _context(
                    BASS,
                    _native("Track", BASS),
                    _derived(VOCALS, BASS),
                ),
            ),
            "mdx:orphan": _declaration(
                ("orphan secret",),
                _context(VOCALS, _native("orphan secret", VOCALS)),
            ),
        }
        roles = {
            VOCALS: _role(VOCALS, "Vocals", "Vocals", StemRoleFamily.VOCAL),
            INSTRUMENTAL: _role(
                INSTRUMENTAL,
                "Instrumental",
                "Instrumental",
                StemRoleFamily.MIX,
            ),
            BASS: _role(BASS, "Bass", "Bass", StemRoleFamily.INSTRUMENT),
        }
        registry = _registry(
            models,
            roles=roles,
            pairs={},
            waivers={"mdx:waived": "intentionally unprojected"},
        )
        entries = [
            _entry("alpha", instruments=(" Vocals ",), primary=" Vocals ", karaoke=True),
            _entry("beta", instruments=("vocals",), primary="vocals"),
            _entry("lead", instruments=("Lead Vocal",), primary="Lead Vocal"),
            _entry("case", instruments=("VOCALS",), primary="VOCALS"),
            _entry("derived", instruments=("Track",), primary="Track"),
            _entry("waived", instruments=("waiver secret",), primary="waiver secret"),
        ]

        forward = audit_catalogue_stems(
            entries,
            collect.CatalogueContext(),
            expected_reference_text="same",
            actual_reference_text="same",
            registry=registry,
        )
        reverse = audit_catalogue_stems(
            list(reversed(entries)),
            collect.CatalogueContext(),
            expected_reference_text="same",
            actual_reference_text="same",
            registry=registry,
        )

        self.assertEqual(forward.native_to_role_ambiguities, reverse.native_to_role_ambiguities)
        self.assertEqual(forward.role_to_native_variants, reverse.role_to_native_variants)
        self.assertEqual(len(forward.native_to_role_ambiguities), 1)
        ambiguity = forward.native_to_role_ambiguities[0]
        self.assertEqual(ambiguity.normalized_native, "vocals")
        self.assertEqual(ambiguity.role_ids, (str(INSTRUMENTAL), str(VOCALS)))
        self.assertEqual(
            ambiguity.model_ids,
            ("mdx:alpha", "mdx:beta", "mdx:case"),
        )
        self.assertEqual(
            ambiguity.native_spellings,
            (" Vocals ", "VOCALS", "vocals"),
        )
        self.assertEqual(
            {evidence.context for evidence in ambiguity.evidence},
            {StemProcessingContext.FULL_MIX, StemProcessingContext.VOCAL_SPLIT},
        )
        self.assertEqual(len(ambiguity.evidence), len(set(ambiguity.evidence)))

        vocal_variants = next(
            group for group in forward.role_to_native_variants if group.role_id == str(VOCALS)
        )
        self.assertEqual(vocal_variants.normalized_natives, ("lead vocal", "vocals"))
        self.assertEqual(
            vocal_variants.native_spellings,
            ("Lead Vocal", " Vocals ", "VOCALS"),
        )
        all_evidence = tuple(
            evidence
            for group in (*forward.native_to_role_ambiguities, *forward.role_to_native_variants)
            for evidence in group.evidence
        )
        self.assertFalse(
            {"mdx:waived", "mdx:orphan"} & {evidence.model_id for evidence in all_evidence}
        )
        self.assertFalse(
            any(
                evidence.model_id == "mdx:derived" and evidence.role_id == str(VOCALS)
                for evidence in all_evidence
            )
        )

    def test_expected_relationship_diversity_is_informational_not_diagnostic(self) -> None:
        """Deleting the informational/diagnostic boundary would make a valid audit fail."""
        roles = {
            VOCALS: _role(VOCALS, "Vocals", "Vocals", StemRoleFamily.VOCAL),
            INSTRUMENTAL: _role(
                INSTRUMENTAL,
                "Instrumental",
                "Instrumental",
                StemRoleFamily.MIX,
            ),
        }
        registry = _registry(
            {
                "mdx:first": _declaration(
                    ("Vocals",),
                    _context(VOCALS, _native("Vocals", VOCALS)),
                ),
                "mdx:second": _declaration(
                    ("vocals",),
                    _context(INSTRUMENTAL, _native("vocals", INSTRUMENTAL)),
                ),
                "mdx:third": _declaration(
                    ("Lead Vocal",),
                    _context(VOCALS, _native("Lead Vocal", VOCALS)),
                ),
            },
            roles=roles,
            pairs={},
        )
        entries = [
            _entry("first", instruments=("Vocals",), primary="Vocals"),
            _entry("second", instruments=("vocals",), primary="vocals"),
            _entry("third", instruments=("Lead Vocal",), primary="Lead Vocal"),
        ]
        counts = stem_audit_module.catalogue_evidence_counts(entries, {})
        pinned = (counts.literal_names, counts.normalized_names, counts.primary_names)

        with patch.object(stem_audit_module, "_PINNED_EVIDENCE_COUNTS", pinned):
            result = audit_catalogue_stems(
                entries,
                collect.CatalogueContext(),
                expected_reference_text="same",
                actual_reference_text="same",
                registry=registry,
            )

        self.assertEqual(result.diagnostics, ())
        self.assertTrue(result.ok)
        self.assertTrue(result.structurally_valid)
        self.assertEqual(len(result.native_to_role_ambiguities), 1)
        self.assertEqual(len(result.role_to_native_variants), 1)

    def test_bundled_relationship_projection_retains_reviewed_six_and_fourteen(self) -> None:
        """A projection that admits waivers/derived rows changes the reviewed baseline."""
        from core.model_stem_manifest import BUNDLED_MANIFEST_PATH, load_stem_manifest

        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        ambiguities, variants = stem_audit_module.catalogue_stem_relationships(
            registry,
            tuple((*registry.models, *registry.waivers)),
        )

        self.assertEqual(len(ambiguities), 6)
        self.assertEqual(len(variants), 14)


if __name__ == "__main__":
    unittest.main()
