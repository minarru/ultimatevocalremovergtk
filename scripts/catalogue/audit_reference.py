"""Audit reference for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

from collections import defaultdict
from typing import (
    AbstractSet,
    Sequence,
)

from catalogue.audit_rules import _output_role, _sorted_model_ids
from catalogue.audit_types import (
    STEM_SEMANTICS_IDENTITY_HEADERS,
    STEM_SEMANTICS_REFERENCE_HEADERS,
    NativeToRoleAmbiguity,
    RoleToNativeVariant,
    StemRelationshipEvidence,
    StemSemanticReferenceRow,
    _tsv_cell,
)
from catalogue.types import ModelEntry
from core.model_stem_manifest import StemSemanticsRegistry
from core.stem_roles import (
    StemId,
    StemProcessingContext,
    StemReviewStatus,
    StemRoleId,
)


def reference_rows_tsv(rows: Sequence[StemSemanticReferenceRow]) -> str:
    """Canonical candidate bytes used to verify the separate renderer."""
    headers = (*STEM_SEMANTICS_IDENTITY_HEADERS, *STEM_SEMANTICS_REFERENCE_HEADERS)
    lines = ["\t".join(headers)]
    lines.extend("\t".join(_tsv_cell(cell) for cell in row.tsv_cells()) for row in rows)
    return "\n".join(lines) + "\n"


def _native_sort_key(value: str) -> tuple[str, str]:
    return StemId(value).casefold(), value


def _relationship_evidence_sort_key(
    evidence: StemRelationshipEvidence,
) -> tuple[str, str, str, str, str, str]:
    return (
        evidence.model_id.casefold(),
        evidence.model_id,
        evidence.context.value,
        StemId(evidence.native).casefold(),
        evidence.native,
        evidence.role_id,
    )


def catalogue_stem_relationships(
    registry: StemSemanticsRegistry,
    catalogue_model_ids: Sequence[str],
) -> tuple[tuple[NativeToRoleAmbiguity, ...], tuple[RoleToNativeVariant, ...]]:
    """Project reviewed catalogue-native relationships without creating findings.

    Membership is the intersection of exact supplied catalogue IDs and reviewed
    declarations, excluding every waiver. Only native outputs contribute;
    derived recipes have no runtime-native spelling to relate.
    """
    supplied_ids = set(catalogue_model_ids)
    reviewed_ids = (set(registry.models) & supplied_ids) - set(registry.waivers)
    uses: set[StemRelationshipEvidence] = set()
    for model_id in sorted(reviewed_ids, key=lambda value: (value.casefold(), value)):
        declaration = registry.models[model_id]
        for context, declared_context in sorted(
            declaration.contexts.items(),
            key=lambda item: item[0].value,
        ):
            for output in declared_context.outputs:
                if output.native is None or not isinstance(output.role, StemRoleId):
                    continue
                uses.add(
                    StemRelationshipEvidence(
                        model_id=model_id,
                        context=context,
                        native=output.native.raw,
                        role_id=str(output.role),
                    )
                )

    by_native: dict[str, set[StemRelationshipEvidence]] = defaultdict(set)
    by_role: dict[str, set[StemRelationshipEvidence]] = defaultdict(set)
    for evidence in uses:
        by_native[StemId(evidence.native).casefold()].add(evidence)
        by_role[evidence.role_id].add(evidence)

    ambiguities = []
    for normalized_native, grouped in sorted(by_native.items()):
        role_ids = tuple(sorted({item.role_id for item in grouped}, key=str.casefold))
        if len(role_ids) < 2:
            continue
        evidence = tuple(sorted(grouped, key=_relationship_evidence_sort_key))
        ambiguities.append(
            NativeToRoleAmbiguity(
                normalized_native=normalized_native,
                native_spellings=tuple(
                    sorted({item.native for item in evidence}, key=_native_sort_key)
                ),
                role_ids=role_ids,
                model_ids=_sorted_model_ids(item.model_id for item in evidence),
                evidence=evidence,
            )
        )

    variants = []
    for role_id, grouped in sorted(by_role.items(), key=lambda item: item[0].casefold()):
        normalized_natives = tuple(sorted({StemId(item.native).casefold() for item in grouped}))
        if len(normalized_natives) < 2:
            continue
        evidence = tuple(sorted(grouped, key=_relationship_evidence_sort_key))
        variants.append(
            RoleToNativeVariant(
                role_id=role_id,
                normalized_natives=normalized_natives,
                native_spellings=tuple(
                    sorted({item.native for item in evidence}, key=_native_sort_key)
                ),
                model_ids=_sorted_model_ids(item.model_id for item in evidence),
                evidence=evidence,
            )
        )
    return tuple(ambiguities), tuple(variants)


def _reference_identity(entry: ModelEntry, model_id: str) -> tuple[str, ...]:
    runtime_family, separator, runtime_basename = model_id.partition(":")
    if not separator or not runtime_family or not runtime_basename:
        raise ValueError(f"invalid canonical model ID for stem reference: {model_id!r}")
    return (
        runtime_family,
        runtime_basename,
        entry.source,
        entry.catalogue_label,
        entry.arch or entry.family,
    )


def _pair_id_for_role(
    role: object,
    context_roles: AbstractSet[object],
    registry: StemSemanticsRegistry,
) -> str:
    return next(
        (
            pair.id
            for pair in registry.pairs.values()
            if role in pair.roles and set(pair.roles).issubset(context_roles)
        ),
        "",
    )


def _reference_rows_for_entry(
    entry: ModelEntry,
    registry: StemSemanticsRegistry,
) -> tuple[StemSemanticReferenceRow, ...]:
    evidence = entry.stem_semantics
    if evidence is None:
        raise ValueError(f"entry has no reconciled stem evidence: {entry.catalogue_label!r}")
    identity = _reference_identity(entry, evidence.model_id)
    if evidence.model_id in registry.waivers:
        return (
            StemSemanticReferenceRow(
                *identity,
                model_id=evidence.model_id,
                model_display=evidence.model_display,
                native_signature=(),
                processing_context=StemProcessingContext.FULL_MIX,
                native_stem="",
                production="",
                backend_primary="",
                backend_target="",
                logical_primary=None,
                logical_secondary=None,
                role_id="",
                canonical_name="",
                filename_tag="",
                pair_id="",
                intent="",
                intent_source="reviewed_waiver",
                review_status=StemReviewStatus.WAIVED.value,
                evidence_or_waiver=registry.waivers[evidence.model_id],
            ),
        )
    rows = []
    for semantics in sorted(evidence.contexts, key=lambda item: item.context.value):
        context_roles = {output.role for output in semantics.outputs}
        secondary_present = semantics.logical_secondary_role is not None
        for output in semantics.outputs:
            role_id = _output_role(output)
            definition = (
                registry.roles.get(output.role) if isinstance(output.role, StemRoleId) else None
            )
            fallback = output.native.raw if output.native is not None else role_id
            rows.append(
                StemSemanticReferenceRow(
                    *identity,
                    model_id=evidence.model_id,
                    model_display=evidence.model_display,
                    native_signature=evidence.native_signature,
                    processing_context=semantics.context,
                    native_stem=output.native.raw if output.native is not None else "",
                    production=output.production.value,
                    backend_primary=entry.primary_stem,
                    backend_target=entry.target_instrument,
                    logical_primary=output.logical_primary,
                    logical_secondary=(output.logical_secondary if secondary_present else None),
                    role_id=role_id,
                    canonical_name=definition.display if definition is not None else fallback,
                    filename_tag=(definition.filename_tag if definition is not None else fallback),
                    pair_id=_pair_id_for_role(output.role, context_roles, registry),
                    intent=semantics.intent,
                    intent_source="reviewed_manifest",
                    review_status=semantics.status.value,
                    evidence_or_waiver=semantics.evidence or semantics.warning,
                    complement_of=str(output.complement_of or ""),
                    derived_from=tuple(str(role) for role in output.derived_from),
                    selected_by_default=output.selected_by_default,
                )
            )
    return tuple(rows)
