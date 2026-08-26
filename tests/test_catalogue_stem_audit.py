"""Focused tests for the structured, collection-free catalogue stem audit."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from catalogue import collect, render  # noqa: E402
from catalogue import stem_audit as stem_audit_module  # noqa: E402
from catalogue.render import stem_semantics_reference_tsv  # noqa: E402
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
    StemReviewStatus,
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
    logical_secondary: StemRoleId | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        logical_primary=logical_primary,
        logical_secondary=logical_secondary,
        outputs=outputs,
    )


def _declaration(
    signature: tuple[str, ...],
    full_mix: SimpleNamespace,
    *,
    vocal_split: SimpleNamespace | None = None,
    intent: str = "vocals",
) -> SimpleNamespace:
    contexts = {StemProcessingContext.FULL_MIX: full_mix}
    if vocal_split is not None:
        contexts[StemProcessingContext.VOCAL_SPLIT] = vocal_split
    return SimpleNamespace(
        native_signature=signature,
        intent=intent,
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
    def _audit(
        self,
        entries: list[collect.ModelEntry],
        registry: StemSemanticsRegistry,
    ) -> StemAuditResult:
        counts = stem_audit_module.catalogue_evidence_counts(entries, {})
        pinned = (counts.literal_names, counts.normalized_names, counts.primary_names)
        with patch.object(stem_audit_module, "_PINNED_EVIDENCE_COUNTS", pinned):
            return audit_catalogue_stems(
                entries,
                collect.CatalogueContext(),
                expected_reference_text="same",
                actual_reference_text="same",
                registry=registry,
            )

    def test_audit_owns_immutable_rows_and_renderer_only_serializes_them(self) -> None:
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

        result = self._audit([entry], registry)

        self.assertTrue(hasattr(result, "reference_rows"))
        rows = getattr(result, "reference_rows", ())
        self.assertEqual(len(rows), 2)
        with self.assertRaises((AttributeError, TypeError)):
            rows[0].intent = "changed"
        rendered = render.stem_semantics_reference_tsv(rows)
        self.assertEqual(rendered, stem_audit_module.reference_rows_tsv(rows))
        self.assertEqual({row.model_id for row in rows}, {"mdx:fixture"})
        self.assertEqual(
            {(row.processing_context, row.role_id) for row in rows},
            {
                (StemProcessingContext.FULL_MIX, str(VOCALS)),
                (StemProcessingContext.FULL_MIX, str(INSTRUMENTAL)),
            },
        )

    def test_reference_rows_are_bidirectionally_complete_for_declarations_and_waivers(
        self,
    ) -> None:
        lead = StemRoleId("vocal.lead")
        backing = StemRoleId("vocal.backing")
        accompaniment = StemRoleId("mix.instrumental_with_backing_vocals")
        roles = {
            lead: _role(lead, "Lead Vocals", "Lead_Vocals", StemRoleFamily.VOCAL),
            backing: _role(backing, "Backing Vocals", "Backing_Vocals", StemRoleFamily.VOCAL),
            INSTRUMENTAL: _role(
                INSTRUMENTAL,
                "Instrumental",
                "Instrumental",
                StemRoleFamily.MIX,
            ),
            accompaniment: _role(
                accompaniment,
                "Instrumental with Backing Vocals",
                "Instrumental_with_Backing_Vocals",
                StemRoleFamily.MIX,
            ),
        }
        summed = SemanticStemOutput(
            native=None,
            role=accompaniment,
            production=StemProduction.DERIVED,
            backend_primary=False,
            logical_primary=False,
            derived_from=(backing, INSTRUMENTAL),
            selected_by_default=False,
        )
        registry = _registry(
            {
                "mdx:reviewed": _declaration(
                    ("Lead", "Backing", "Instrumental"),
                    _context(
                        accompaniment,
                        _native("Lead", lead),
                        _native("Backing", backing),
                        _native("Instrumental", INSTRUMENTAL),
                        summed,
                        logical_secondary=lead,
                    ),
                    vocal_split=_context(
                        backing,
                        _native("Lead", lead),
                        _native("Backing", backing),
                        _native("Instrumental", INSTRUMENTAL),
                        logical_secondary=lead,
                    ),
                    intent="karaoke",
                )
            },
            roles=roles,
            pairs={},
            waivers={"mdx:waived": "reviewed exception"},
        )
        entries = [
            _entry(
                "reviewed",
                instruments=("Lead", "Backing", "Instrumental"),
                primary="Lead",
                karaoke=True,
            ),
            _entry("waived"),
        ]

        result = self._audit(entries, registry)
        self.assertTrue(hasattr(result, "reference_rows"))
        rows = getattr(result, "reference_rows", ())

        self.assertEqual({row.model_id for row in rows}, {"mdx:reviewed", "mdx:waived"})
        reviewed_rows = [row for row in rows if row.model_id == "mdx:reviewed"]
        waiver_rows = [row for row in rows if row.model_id == "mdx:waived"]
        expected_routes = {
            (context, str(output.role))
            for context, declaration in registry.models["mdx:reviewed"].contexts.items()
            for output in declaration.outputs
        }
        self.assertEqual(
            {(row.processing_context, row.role_id) for row in reviewed_rows},
            expected_routes,
        )
        self.assertTrue(all(type(row.selected_by_default) is bool for row in reviewed_rows))
        full_mix = [
            row for row in reviewed_rows if row.processing_context is StemProcessingContext.FULL_MIX
        ]
        self.assertEqual(sum(row.logical_secondary is True for row in full_mix), 1)
        self.assertTrue(all(type(row.logical_secondary) is bool for row in full_mix))
        sum_row = next(row for row in full_mix if row.role_id == str(accompaniment))
        self.assertEqual(sum_row.complement_of, "")
        self.assertEqual(sum_row.derived_from, (str(backing), str(INSTRUMENTAL)))
        self.assertFalse(sum_row.selected_by_default)
        self.assertEqual(len(waiver_rows), 1)
        self.assertIsNone(waiver_rows[0].logical_secondary)
        self.assertEqual(waiver_rows[0].complement_of, "")
        self.assertEqual(waiver_rows[0].derived_from, ())
        self.assertIsNone(waiver_rows[0].selected_by_default)

    def test_manifest_global_structure_reports_unused_intent_overlap_and_separate_orphans(
        self,
    ) -> None:
        unused = StemRoleId("vocal.unused")
        roles = {
            VOCALS: _role(VOCALS, "Vocals", "Vocals", StemRoleFamily.VOCAL),
            INSTRUMENTAL: _role(
                INSTRUMENTAL,
                "Instrumental",
                "Instrumental",
                StemRoleFamily.MIX,
            ),
            unused: _role(unused, "Unused", "Unused", StemRoleFamily.VOCAL),
        }
        registry = _registry(
            {
                "mdx:fixture": _declaration(
                    ("Vocals", "Instrumental"),
                    _context(
                        VOCALS,
                        _native("Vocals", VOCALS),
                        _native("Instrumental", INSTRUMENTAL),
                    ),
                    intent="invented",
                ),
                "mdx:orphan-declaration": _declaration(
                    ("Vocals",), _context(VOCALS, _native("Vocals", VOCALS))
                ),
            },
            roles=roles,
            waivers={
                "mdx:fixture": "overlap",
                "mdx:orphan-waiver": "orphan",
            },
        )

        result = self._audit([_entry("fixture")], registry)

        self.assertEqual(
            {
                "role-unused",
                "intent-invalid",
                "manifest-review-overlap",
                "manifest-orphan-declaration",
                "manifest-orphan-waiver",
            }
            - _codes(result),
            set(),
        )
        self.assertEqual(_diagnostic(result, "role-unused").actual, (str(unused),))
        self.assertEqual(
            _diagnostic(result, "manifest-orphan-declaration").model_ids,
            ("mdx:orphan-declaration",),
        )
        self.assertEqual(
            _diagnostic(result, "manifest-orphan-waiver").model_ids,
            ("mdx:orphan-waiver",),
        )

    def test_context_recipe_and_karaoke_secondary_diagnostics_are_schema_2_exact(self) -> None:
        accompaniment = StemRoleId("mix.instrumental_with_backing_vocals")
        lead = StemRoleId("vocal.lead")
        roles = {
            lead: _role(lead, "Lead Vocals", "Lead_Vocals", StemRoleFamily.VOCAL),
            INSTRUMENTAL: _role(
                INSTRUMENTAL,
                "Instrumental",
                "Instrumental",
                StemRoleFamily.MIX,
            ),
            accompaniment: _role(
                accompaniment,
                "Instrumental with Backing Vocals",
                "Instrumental_with_Backing_Vocals",
                StemRoleFamily.MIX,
            ),
        }
        invalid_sum = SemanticStemOutput(
            native=None,
            role=accompaniment,
            production=StemProduction.DERIVED,
            backend_primary=False,
            logical_primary=False,
            derived_from=(INSTRUMENTAL,),
        )
        registry = _registry(
            {
                "mdx:karaoke": _declaration(
                    ("Lead", "Instrumental"),
                    _context(
                        accompaniment,
                        _native("Lead", lead),
                        _native("Instrumental", INSTRUMENTAL),
                        invalid_sum,
                    ),
                    vocal_split=_context(
                        INSTRUMENTAL,
                        _native("Lead", lead),
                        _native("Instrumental", INSTRUMENTAL),
                        logical_secondary=accompaniment,
                    ),
                    intent="karaoke",
                )
            },
            roles=roles,
            pairs={},
        )

        result = self._audit(
            [_entry("karaoke", instruments=("Lead", "Instrumental"), karaoke=True)],
            registry,
        )

        self.assertIn("context-logical-secondary-required", _codes(result))
        self.assertIn("context-logical-secondary", _codes(result))
        recipe = _diagnostic(result, "context-recipe-invalid")
        self.assertEqual(recipe.context, StemProcessingContext.FULL_MIX)
        self.assertEqual(recipe.expected, ("two-or-more native role dependencies",))

    def test_target_complement_rejects_one_source_derived_from_alias(self) -> None:
        roles = {
            BASS: _role(BASS, "Bass", "Bass", StemRoleFamily.INSTRUMENT),
            NO_BASS: _role(NO_BASS, "No Bass", "No_Bass", StemRoleFamily.RESIDUAL),
        }
        invalid_alias = SemanticStemOutput(
            native=None,
            role=NO_BASS,
            production=StemProduction.DERIVED,
            backend_primary=False,
            logical_primary=False,
            derived_from=(BASS,),
        )
        registry = _registry(
            {
                "mdx:target": _declaration(
                    ("bass",),
                    _context(BASS, _native("bass", BASS), invalid_alias),
                )
            },
            roles=roles,
            pairs={},
        )

        result = self._audit(
            [
                _entry(
                    "target",
                    instruments=("bass",),
                    primary="bass",
                    target="bass",
                    metadata_source="bundled_yaml:target.yaml",
                )
            ],
            registry,
        )

        self.assertIn("target-derived-complement", _codes(result))
        self.assertIn("context-recipe-invalid", _codes(result))

    def test_rendered_route_collision_is_scoped_to_one_model_context(self) -> None:
        duplicate = StemRoleId("vocal.duplicate")
        roles = {
            VOCALS: _role(VOCALS, "Vocals", "Voice", StemRoleFamily.VOCAL),
            duplicate: _role(duplicate, "ＶＯＣＡＬＳ", "voice", StemRoleFamily.VOCAL),
        }
        registry = _registry(
            {
                "mdx:collision": _declaration(
                    ("One", "Two"),
                    _context(
                        VOCALS,
                        _native("One", VOCALS),
                        _native("Two", duplicate),
                    ),
                )
            },
            roles=roles,
            pairs={},
        )

        result = self._audit(
            [_entry("collision", instruments=("One", "Two"), primary="One")], registry
        )

        for code in ("route-display-collision", "route-tag-collision"):
            self.assertIn(code, _codes(result))
            diagnostic = _diagnostic(result, code)
            self.assertEqual(diagnostic.model_ids, ("mdx:collision",))
            self.assertEqual(diagnostic.context, StemProcessingContext.FULL_MIX)

    def test_reference_projection_detects_stale_secondary_and_default_flags(self) -> None:
        entry = _entry("fixture")
        declaration = _declaration(
            ("Vocals", "Instrumental"),
            _context(
                VOCALS,
                _native("Vocals", VOCALS),
                _native("Instrumental", INSTRUMENTAL),
                logical_secondary=INSTRUMENTAL,
            ),
        )
        registry = _registry({"mdx:fixture": declaration})
        stale_outputs = (
            SimpleNamespace(
                native=StemId("Vocals"),
                role=VOCALS,
                production=StemProduction.NATIVE,
                logical_primary=True,
                logical_secondary=True,
                complement_of=None,
                derived_from=(),
                selected_by_default=None,
            ),
            SimpleNamespace(
                native=StemId("Instrumental"),
                role=INSTRUMENTAL,
                production=StemProduction.NATIVE,
                logical_primary=False,
                logical_secondary=False,
                complement_of=None,
                derived_from=(),
                selected_by_default=True,
            ),
        )
        stale = SimpleNamespace(
            model_id="mdx:fixture",
            context=StemProcessingContext.FULL_MIX,
            outputs=stale_outputs,
            status=StemReviewStatus.REVIEWED,
            warning="",
            evidence="fixture",
            intent="vocals",
            logical_secondary_role=INSTRUMENTAL,
        )

        with patch.object(collect, "resolve_catalogue_stem_semantics", return_value=stale):
            result = self._audit([entry], registry)

        self.assertIn("reference-logical-secondary", _codes(result))
        self.assertIn("reference-selected-by-default", _codes(result))

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
            _diagnostic(result, "manifest-orphan-declaration").model_ids,
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

    def test_structural_audit_does_not_mix_in_on_disk_reference_drift(self) -> None:
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
        self.assertNotIn("reference-drift", _codes(result))
        self.assertTrue(result.reference_matches)
        self.assertTrue(result.structurally_valid is False)
        self.assertEqual(
            stem_semantics_reference_tsv(result.reference_rows),
            stem_audit_module.reference_rows_tsv(result.reference_rows),
        )

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
                "logical_secondary",
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

    def test_context_logical_secondary_must_be_distinct_and_present_exactly_once(self) -> None:
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
        cases = (
            ("missing", BASS, (BASS,)),
            ("primary", VOCALS, (VOCALS,)),
        )
        for label, logical_secondary, expected in cases:
            registry = _registry(
                {
                    "mdx:fixture": _declaration(
                        ("Vocals", "Instrumental"),
                        _context(
                            VOCALS,
                            _native("Vocals", VOCALS),
                            _native("Instrumental", INSTRUMENTAL),
                            logical_secondary=logical_secondary,
                        ),
                    )
                },
                roles=roles,
            )

            result = audit_catalogue_stems(
                [_entry("fixture")],
                collect.CatalogueContext(),
                expected_reference_text="same",
                actual_reference_text="same",
                registry=registry,
            )

            with self.subTest(label=label):
                diagnostic = _diagnostic(result, "context-logical-secondary")
                self.assertEqual(diagnostic.model_ids, ("mdx:fixture",))
                self.assertEqual(diagnostic.context, StemProcessingContext.FULL_MIX)
                self.assertEqual(diagnostic.expected, tuple(str(role) for role in expected))

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

    def test_task5_bundled_relationship_projection_is_exact(self) -> None:
        """Promoted native routes are visible until Task 6 tightens diagnostics."""
        from core.model_stem_manifest import BUNDLED_MANIFEST_PATH, load_stem_manifest

        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        ambiguities, variants = stem_audit_module.catalogue_stem_relationships(
            registry,
            tuple((*registry.models, *registry.waivers)),
        )

        self.assertEqual(
            [(item.normalized_native, item.role_ids) for item in ambiguities],
            [
                ("bass", ("instrument.bass", "vocal.bass")),
                (
                    "dry",
                    (
                        "effect.noise.removed",
                        "effect.reverb.removed",
                        "effect.reverb_echo.removed",
                    ),
                ),
                (
                    "instrumental",
                    (
                        "mix.instrumental",
                        "mix.instrumental_with_backing_vocals",
                        "mix.instrumental_with_lead_vocals",
                        "vocal.backing",
                        "vocal.lead",
                    ),
                ),
                ("lead", ("instrument.guitar.lead", "vocal.lead")),
                ("no dry", ("effect.reverb", "effect.reverb_echo")),
                (
                    "no reverb",
                    ("effect.reverb.removed", "effect.reverb_echo.removed"),
                ),
                (
                    "other",
                    (
                        "effect.noise",
                        "instrument.bowed_strings.removed",
                        "instrument.drums.removed",
                        "mix.instrumental",
                        "mix.instrumental_with_backing_vocals",
                        "mix.music",
                        "residual.other",
                        "vocal.aspiration.removed",
                        "vocal.backing",
                    ),
                ),
                ("reverb", ("effect.reverb", "effect.reverb_echo")),
                ("strings", ("instrument.bowed_strings", "instrument.strings")),
                (
                    "vocals",
                    ("cinematic.speech", "vocal.backing", "vocal.lead", "vocal.vocals"),
                ),
            ],
        )
        self.assertEqual(
            [(item.role_id, item.normalized_natives) for item in variants],
            [
                ("cinematic.sfx", ("effects", "sfx")),
                ("cinematic.speech", ("speech", "vocals")),
                ("effect.noise", ("noise", "other")),
                ("effect.noise.removed", ("dry", "no noise")),
                ("effect.reverb", ("no dry", "reverb")),
                ("effect.reverb.removed", ("dry", "no reverb", "noreverb")),
                ("effect.reverb_echo", ("no dry", "reverb")),
                ("effect.reverb_echo.removed", ("dry", "no reverb")),
                ("instrument.bowed_strings", ("bowed_strings", "strings")),
                ("instrument.drums.removed", ("no drums", "other")),
                ("instrument.percussion", ("percussion", "percussions")),
                ("instrument.woodwinds", ("woodwind", "woodwinds")),
                ("mix.instrumental", ("instrument", "instrumental", "other")),
                (
                    "mix.instrumental_with_backing_vocals",
                    ("instrumental", "other"),
                ),
                ("mix.music", ("music", "other")),
                ("spatial.center", ("cen", "center", "mid", "similarity")),
                ("spatial.side", ("side", "wide")),
                (
                    "vocal.backing",
                    ("back-vocal", "backing_vocal", "instrumental", "other", "vocals"),
                ),
                (
                    "vocal.lead",
                    ("instrumental", "karaoke", "lead", "lead-vocal", "vocals"),
                ),
                ("vocal.vocals", ("vocal", "vocals", "voices", "vox")),
            ],
        )
        evidence = {
            (item.model_id, StemId(item.native).casefold(), item.role_id)
            for group in (*ambiguities, *variants)
            for item in group.evidence
        }
        self.assertIn(
            ("mdx:kuielab_a_bass", "bass", "instrument.bass"),
            evidence,
        )
        self.assertIn(
            ("mdx:scnet_choirsep_exp", "bass", "vocal.bass"),
            evidence,
        )
        self.assertIn(
            ("mdx:Reverb_HQ_By_FoxJoy", "reverb", "effect.reverb"),
            evidence,
        )
        self.assertIn(
            ("vr:UVR-DeEcho-DeReverb", "reverb", "effect.reverb_echo"),
            evidence,
        )
        self.assertIn(
            ("vr:UVR-De-Reverb-aufr33-jarredou", "no dry", "effect.reverb"),
            evidence,
        )
        self.assertIn(
            ("vr:UVR-DeEcho-DeReverb", "no reverb", "effect.reverb_echo.removed"),
            evidence,
        )
        # Classic ONNX computed inverses remain addressable native backend
        # keys and therefore participate in the relationship evidence.
        self.assertIn(("mdx:Kim_Inst", "vocals", "vocal.vocals"), evidence)
        # A configured target complement is a derived semantic route, not a
        # runtime-native spelling, and must never enter either projection.
        self.assertFalse(
            any(
                model_id == "mdx:model_bs_roformer_ep_937_sdr_10.5309"
                and role_id == "instrument.drum_bass"
                for model_id, _native, role_id in evidence
            )
        )

    def test_all_28_promoted_ids_are_present_in_semantic_reference_tsv(self) -> None:
        from core.mdx_runtime_contract import load_bundled_mdx_runtime_contracts
        from core.model_stem_manifest import load_bundled_stem_semantics

        contracts = {
            model_id: contract
            for model_id, contract in load_bundled_mdx_runtime_contracts().contracts.items()
            if model_id != "mdx:UVR_MDXNET_KARA_2"
        }
        entries = [
            collect.ModelEntry(
                source="runtime-contract-test",
                family="MDX-Net ONNX",
                catalogue_label=model_id,
                weight_file=(
                    model_id.removeprefix("mdx:")
                    + (".onnx" if contract.backend == "classic_onnx" else ".ckpt")
                ),
                config_yaml=(contract.config_yamls[0] if contract.config_yamls else ""),
                config_sha256=(
                    contract.config_evidence[contract.config_yamls[0]].content_sha256
                    if contract.config_yamls
                    else ""
                ),
                primary_stem=contract.primary_native,
                instruments=(
                    list(contract.config_evidence[contract.config_yamls[0]].training_instruments)
                    if contract.config_yamls
                    else list(contract.native_signature)
                ),
                target_instrument=(
                    contract.primary_native if contract.backend == "mdx_c_target" else ""
                ),
                metadata_source=(
                    f"bundled_yaml:{contract.config_yamls[0]}"
                    if contract.config_yamls
                    else "runtime-contract-test"
                ),
            )
            for model_id, contract in contracts.items()
        ]

        registry = load_bundled_stem_semantics()
        result = audit_catalogue_stems(
            entries,
            collect.CatalogueContext(),
            registry=registry,
        )
        rendered = stem_semantics_reference_tsv(result.reference_rows)
        rows = [line.split("\t") for line in rendered.splitlines()]
        model_id_column = rows[0].index("model_id")
        status_column = rows[0].index("review_status")
        rendered_ids = {row[model_id_column] for row in rows[1:]}

        self.assertEqual(len(contracts), 28)
        self.assertEqual(rendered_ids, set(contracts))
        self.assertTrue(all(row[status_column] == "reviewed" for row in rows[1:]))

    def test_canonical_snapshot_is_483_2_0_with_bidirectional_row_parity(self) -> None:
        """Checked identity evidence and reviewed schema-2 routes agree exactly."""
        from core.mdx_runtime_contract import load_bundled_mdx_runtime_contracts
        from core.model_stem_manifest import load_bundled_stem_semantics

        registry = load_bundled_stem_semantics()
        runtime_contracts = load_bundled_mdx_runtime_contracts().contracts
        reference_path = os.path.join(ROOT, "docs", "model_stem_semantics_reference.tsv")
        with open(reference_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        headers = lines[0].split("\t")
        identity_by_id = {}
        for line in lines[1:]:
            cells = dict(zip(headers, line.split("\t"), strict=True))
            identity_by_id.setdefault(cells["model_id"], cells)

        family_by_runtime = {
            "demucs": "Demucs",
            "vr": "VR Architecture",
            "apollo": "Apollo",
            "mdx": "MDX-Net ONNX",
        }
        extension_by_runtime = {
            "demucs": ".th",
            "vr": ".pth",
            "apollo": ".onnx",
            "mdx": ".ckpt",
        }
        entries = []
        for model_id, identity in sorted(identity_by_id.items()):
            runtime_family, runtime_basename = model_id.split(":", 1)
            declaration = registry.models.get(model_id)
            signature = tuple(declaration.native_signature) if declaration else ()
            contract = runtime_contracts.get(model_id)
            config_yaml = contract.config_yamls[0] if contract and contract.config_yamls else ""
            collected_instruments = (
                contract.config_evidence[config_yaml].training_instruments
                if contract is not None and config_yaml
                else signature
            )
            entries.append(
                collect.ModelEntry(
                    source=identity["catalogue_source"],
                    family=family_by_runtime[runtime_family],
                    catalogue_label=identity["catalogue_label"],
                    weight_file=runtime_basename + extension_by_runtime[runtime_family],
                    arch=identity["execution_arch"],
                    config_yaml=config_yaml,
                    config_sha256=(
                        contract.config_evidence[config_yaml].content_sha256
                        if contract is not None and config_yaml
                        else ""
                    ),
                    instruments=list(collected_instruments),
                    primary_stem=signature[0] if signature else "",
                    target_instrument=(
                        contract.primary_native
                        if contract is not None and contract.backend == "mdx_c_target"
                        else ""
                    ),
                    metadata_source=(
                        f"bundled_yaml:{config_yaml}"
                        if config_yaml
                        else "canonical-reference-identity"
                    ),
                    is_karaoke=bool(declaration and declaration.intent == "karaoke"),
                )
            )

        counts = stem_audit_module.catalogue_evidence_counts(entries, {})
        pinned = (counts.literal_names, counts.normalized_names, counts.primary_names)
        with patch.object(stem_audit_module, "_PINNED_EVIDENCE_COUNTS", pinned):
            result = audit_catalogue_stems(
                entries,
                collect.CatalogueContext(),
                registry=registry,
            )

        self.assertEqual(len(identity_by_id), 485)
        self.assertEqual(
            len(result.reviewed_model_ids),
            483,
            (result.raw_model_ids, result.diagnostics),
        )
        self.assertEqual(len(result.waived_model_ids), 2)
        self.assertEqual(result.raw_model_ids, ())
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(
            {row.model_id for row in result.reference_rows},
            set(identity_by_id),
        )

        rows_by_route = {
            (row.model_id, row.processing_context, row.role_id): row
            for row in result.reference_rows
            if row.review_status == StemReviewStatus.REVIEWED.value
        }
        expected_routes = {
            (model_id, context, str(output.role)): output
            for model_id, declaration in registry.models.items()
            for context, declared_context in declaration.contexts.items()
            for output in declared_context.outputs
        }
        self.assertEqual(set(rows_by_route), set(expected_routes))
        for key, output in expected_routes.items():
            row = rows_by_route[key]
            self.assertIs(type(row.selected_by_default), bool)
            self.assertEqual(row.complement_of, str(output.complement_of or ""))
            self.assertEqual(
                row.derived_from,
                tuple(str(role) for role in output.derived_from),
            )
            declared_context = registry.models[key[0]].contexts[key[1]]
            if declared_context.logical_secondary is None:
                self.assertIsNone(row.logical_secondary)
            else:
                self.assertIs(type(row.logical_secondary), bool)

        waiver_rows = [
            row
            for row in result.reference_rows
            if row.review_status == StemReviewStatus.WAIVED.value
        ]
        self.assertEqual({row.model_id for row in waiver_rows}, set(registry.waivers))
        self.assertEqual(len(waiver_rows), 2)
        self.assertTrue(
            all(
                row.complement_of == ""
                and row.derived_from == ()
                and row.selected_by_default is None
                for row in waiver_rows
            )
        )
        self.assertEqual(
            render.stem_semantics_reference_tsv(result.reference_rows),
            stem_audit_module.reference_rows_tsv(result.reference_rows),
        )


if __name__ == "__main__":
    unittest.main()
