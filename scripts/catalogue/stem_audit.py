"""Structured strict auditing for one already-collected catalogue snapshot.

The public entry point in this module is deliberately pure with respect to
catalogue collection and repository files.  Callers supply the exact entries,
supplemental context, rendered reference candidate, and checked-in reference.
That keeps every renderer and validator on one authoritative snapshot and
lets later CLI code distinguish structural manifest failures from repairable
generated-reference drift without parsing human-readable audit output."""
from __future__ import annotations

from typing import (
    AbstractSet,
    Sequence,
)

from catalogue import audit_types
from catalogue.audit_reference import _reference_rows_for_entry

# Legacy public imports retain object identity; consumers use the owners.
from catalogue.audit_reference import catalogue_stem_relationships as catalogue_stem_relationships
from catalogue.audit_reference import reference_rows_tsv as reference_rows_tsv
from catalogue.audit_rules import (
    _catalogue_model_id,
    _diagnostic_sort_key,
    _pair_diagnostics,
    _role_collision_diagnostics,
    _route_collision_diagnostics,
    _signature_matches,
    _sorted_model_ids,
    _target_projection_diagnostics,
    _unused_role_diagnostics,
    assess_model_contexts,
)
from catalogue.audit_rules import catalogue_evidence_counts as catalogue_evidence_counts
from catalogue.audit_types import (
    _REVIEWED_VOCAL_SPLIT_IDS,
    _ContextRoleProjection,
)
from catalogue.audit_types import STEM_SEMANTICS_IDENTITY_HEADERS as STEM_SEMANTICS_IDENTITY_HEADERS
from catalogue.audit_types import (
    STEM_SEMANTICS_REFERENCE_HEADERS as STEM_SEMANTICS_REFERENCE_HEADERS,
)
from catalogue.audit_types import CatalogueEvidenceCounts as CatalogueEvidenceCounts
from catalogue.audit_types import ManifestCandidateResult as ManifestCandidateResult
from catalogue.audit_types import NativeToRoleAmbiguity as NativeToRoleAmbiguity
from catalogue.audit_types import RoleToNativeVariant as RoleToNativeVariant
from catalogue.audit_types import StemAuditDiagnostic as StemAuditDiagnostic
from catalogue.audit_types import StemAuditResult as StemAuditResult
from catalogue.audit_types import StemRelationshipEvidence as StemRelationshipEvidence
from catalogue.audit_types import StemSemanticReferenceRow as StemSemanticReferenceRow
from catalogue.confidence import HashCache as HashCache
from catalogue.confidence import HashLookup as HashLookup
from catalogue.confidence import StemConfidenceEntry as StemConfidenceEntry
from catalogue.confidence import default_hash_cache_path as default_hash_cache_path
from catalogue.confidence import iter_stem_confidence_entries as iter_stem_confidence_entries
from catalogue.confidence import render_stem_confidence_summary as render_stem_confidence_summary
from catalogue.confidence import render_stem_confidence_table as render_stem_confidence_table
from catalogue.confidence import run_stem_confidence_audit as run_stem_confidence_audit
from catalogue.confidence import select_confidence_targets as select_confidence_targets
from catalogue.confidence import write_stem_confidence_json as write_stem_confidence_json
from catalogue.evidence import is_runtime_target_instrument, reconcile_stem_semantics
from catalogue.manifest_candidate import build_manifest_candidate as build_manifest_candidate
from catalogue.types import CatalogueContext, ModelEntry
from core.model_stem_manifest import StemSemanticsRegistry
from core.model_stem_semantics import (
    MODEL_STEM_INTENTS,
)
from core.stem_roles import (
    StemProcessingContext,
)


def audit_catalogue_stems(
    entries: Sequence[ModelEntry],
    context: CatalogueContext,
    *,
    expected_reference_text: str = "",
    actual_reference_text: str | None = None,
    registry: StemSemanticsRegistry,
    current_model_ids: AbstractSet[str] | None = None,
) -> StemAuditResult:
    """Audit one supplied catalogue snapshot and own its reference rows.

    The legacy text arguments remain accepted for callers being migrated, but
    on-disk drift is deliberately outside this structural phase.
    """
    selected_registry = registry
    if any(entry.stem_semantics is None for entry in entries):
        reconcile_stem_semantics(list(entries), registry=selected_registry)
    model_ids_by_entry = tuple(
        sorted(
            ((_catalogue_model_id(entry), entry) for entry in entries),
            key=lambda item: (item[0].casefold(), item[0]),
        )
    )
    catalogue_model_ids = _sorted_model_ids(model_id for model_id, _entry in model_ids_by_entry)
    diagnostics: list[StemAuditDiagnostic] = []

    duplicate_ids = _sorted_model_ids(
        model_id
        for model_id in catalogue_model_ids
        if sum(candidate == model_id for candidate, _entry in model_ids_by_entry) > 1
    )
    if duplicate_ids:
        diagnostics.append(
            StemAuditDiagnostic(
                code="catalogue-duplicate-id",
                model_ids=duplicate_ids,
                message="multiple collected entries project to the same canonical model ID",
            )
        )

    catalogue_id_set = set(catalogue_model_ids)
    coverage_ids = (
        set(selected_registry.models).union(selected_registry.waivers)
        if current_model_ids is None
        else set(current_model_ids)
    )
    declaration_ids = set(selected_registry.models).intersection(coverage_ids)
    waiver_ids = set(selected_registry.waivers).intersection(coverage_ids)
    overlap = _sorted_model_ids(declaration_ids & waiver_ids)
    if overlap:
        diagnostics.append(
            StemAuditDiagnostic(
                code="manifest-review-overlap",
                model_ids=overlap,
                message="model IDs cannot be both declared and waived",
            )
        )
    missing = _sorted_model_ids(catalogue_id_set - declaration_ids - waiver_ids)
    if missing:
        diagnostics.append(
            StemAuditDiagnostic(
                code="catalogue-unreviewed",
                model_ids=missing,
                message="catalogue model IDs have neither reviewed declarations nor waivers",
            )
        )
    orphaned_declarations = _sorted_model_ids(declaration_ids - catalogue_id_set)
    if orphaned_declarations:
        diagnostics.append(
            StemAuditDiagnostic(
                code="manifest-orphan-declaration",
                model_ids=orphaned_declarations,
                message="manifest declarations are absent from the supplied catalogue snapshot",
            )
        )
    orphaned_waivers = _sorted_model_ids(waiver_ids - catalogue_id_set)
    if orphaned_waivers:
        diagnostics.append(
            StemAuditDiagnostic(
                code="manifest-orphan-waiver",
                model_ids=orphaned_waivers,
                message="manifest waivers are absent from the supplied catalogue snapshot",
            )
        )

    for model_id in sorted(declaration_ids, key=str.casefold):
        declaration = selected_registry.models[model_id]
        if declaration.intent in MODEL_STEM_INTENTS:
            continue
        diagnostics.append(
            StemAuditDiagnostic(
                code="intent-invalid",
                model_ids=(model_id,),
                message="reviewed declaration intent is outside the closed vocabulary",
                expected=tuple(sorted(MODEL_STEM_INTENTS)),
                actual=(str(declaration.intent),),
            )
        )

    reviewed_ids = set()
    raw_ids = set(missing)
    context_role_projections: list[_ContextRoleProjection] = []
    reference_rows: list[StemSemanticReferenceRow] = []
    for model_id, entry in model_ids_by_entry:
        if model_id in waiver_ids:
            reference_rows.extend(_reference_rows_for_entry(entry, selected_registry))
            continue
        declaration = selected_registry.models.get(model_id)
        if declaration is None:
            raw_ids.add(model_id)
            continue
        reconciled = entry.stem_semantics
        if reconciled is None:
            raise AssertionError("stem reconciliation did not attach evidence")
        runtime_signature = reconciled.native_signature
        if not _signature_matches(declaration.native_signature, runtime_signature):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="native-signature",
                    model_ids=(model_id,),
                    message="reviewed declaration does not match runtime-native source keys",
                    expected=tuple(declaration.native_signature),
                    actual=runtime_signature,
                )
            )
        assessment = assess_model_contexts(
            model_id, declaration,
            {semantics.context: semantics for semantics in reconciled.contexts},
        )
        diagnostics.extend(assessment.diagnostics)
        model_reviewed = assessment.fully_reviewed
        model_context_projections = assessment.projections
        context_role_projections.extend(model_context_projections)
        for projection in model_context_projections:
            if projection.semantics is not None:
                diagnostics.extend(
                    _route_collision_diagnostics(
                        model_id,
                        projection.context,
                        projection.semantics.outputs,
                        selected_registry,
                    )
                )
        reference_rows.extend(_reference_rows_for_entry(entry, selected_registry))
        if model_reviewed:
            reviewed_ids.add(model_id)
        else:
            raw_ids.add(model_id)
        if is_runtime_target_instrument(
            model_id,
            target_instrument=entry.target_instrument,
            metadata_source=entry.metadata_source,
            config_yaml=entry.config_yaml,
        ):
            diagnostics.extend(
                _target_projection_diagnostics(model_id, declaration, runtime_signature)
            )
        eligible_for_vocal_split = entry.is_karaoke or model_id in _REVIEWED_VOCAL_SPLIT_IDS
        has_vocal_split = StemProcessingContext.VOCAL_SPLIT in declaration.contexts
        if eligible_for_vocal_split and not has_vocal_split:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="missing-vocal-split",
                    model_ids=(model_id,),
                    context=StemProcessingContext.VOCAL_SPLIT,
                    message="karaoke or reviewed BVE model lacks a vocal_split declaration",
                )
            )
        elif has_vocal_split and not eligible_for_vocal_split:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="unexpected-vocal-split",
                    model_ids=(model_id,),
                    context=StemProcessingContext.VOCAL_SPLIT,
                    message="non-karaoke model has an unapproved vocal_split declaration",
                )
            )

    diagnostics.extend(_role_collision_diagnostics(selected_registry, catalogue_model_ids))
    diagnostics.extend(_unused_role_diagnostics(selected_registry, catalogue_model_ids))
    diagnostics.extend(
        _pair_diagnostics(selected_registry, catalogue_model_ids, context_role_projections)
    )

    evidence_counts = catalogue_evidence_counts(entries, context.community_by_file)
    actual_evidence = (
        evidence_counts.literal_names,
        evidence_counts.normalized_names,
        evidence_counts.primary_names,
    )
    if actual_evidence != audit_types._PINNED_EVIDENCE_COUNTS:
        diagnostics.append(
            StemAuditDiagnostic(
                code="evidence-count",
                model_ids=catalogue_model_ids,
                message="catalogue evidence vocabulary differs from the reviewed baseline",
                expected=tuple(str(value) for value in audit_types._PINNED_EVIDENCE_COUNTS),
                actual=tuple(str(value) for value in actual_evidence),
            )
        )

    waived_catalogue_ids = catalogue_id_set & waiver_ids
    raw_ids.update(catalogue_id_set - reviewed_ids - waived_catalogue_ids)
    native_to_role_ambiguities, role_to_native_variants = catalogue_stem_relationships(
        selected_registry,
        _sorted_model_ids(reviewed_ids),
    )
    return StemAuditResult(
        catalogue_model_ids=catalogue_model_ids,
        reviewed_model_ids=_sorted_model_ids(reviewed_ids),
        waived_model_ids=_sorted_model_ids(waived_catalogue_ids),
        raw_model_ids=_sorted_model_ids(raw_ids),
        evidence_counts=evidence_counts,
        diagnostics=tuple(sorted(diagnostics, key=_diagnostic_sort_key)),
        reference_rows=tuple(reference_rows),
        native_to_role_ambiguities=native_to_role_ambiguities,
        role_to_native_variants=role_to_native_variants,
    )



__all__ = [
    "CatalogueEvidenceCounts",
    "NativeToRoleAmbiguity",
    "RoleToNativeVariant",
    "STEM_SEMANTICS_REFERENCE_HEADERS",
    "StemAuditDiagnostic",
    "StemAuditResult",
    "StemRelationshipEvidence",
    "HashCache",
    "HashLookup",
    "ManifestCandidateResult",
    "StemConfidenceEntry",
    "audit_catalogue_stems",
    "build_manifest_candidate",
    "catalogue_evidence_counts",
    "catalogue_stem_relationships",
    "default_hash_cache_path",
    "iter_stem_confidence_entries",
    "render_stem_confidence_summary",
    "render_stem_confidence_table",
    "run_stem_confidence_audit",
    "select_confidence_targets",
    "write_stem_confidence_json",
]
