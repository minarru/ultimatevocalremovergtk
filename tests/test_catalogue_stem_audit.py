"""Focused tests for the structured, collection-free catalogue stem audit."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from catalogue import collect
from catalogue.stem_audit import (
    STEM_SEMANTICS_REFERENCE_HEADERS,
    StemAuditDiagnostic,
    StemAuditResult,
    audit_catalogue_stems,
)

from core.model_stem_manifest import StemPairDefinition, StemSemanticsRegistry
from core.stem_roles import (
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
        StemId(name),
        role,
        StemProduction.NATIVE,
        False,
        False,
    )


def _derived(role: StemRoleId, source_role: StemRoleId) -> SemanticStemOutput:
    return SemanticStemOutput(
        None,
        role,
        StemProduction.DERIVED,
        False,
        False,
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

    def test_reference_header_contract_remains_the_existing_seventeen_columns(self) -> None:
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
            ),
        )


if __name__ == "__main__":
    unittest.main()
