"""Structured strict auditing for one already-collected catalogue snapshot.

The public entry point in this module is deliberately pure with respect to
catalogue collection and repository files.  Callers supply the exact entries,
supplemental context, rendered reference candidate, and checked-in reference.
That keeps every renderer and validator on one authoritative snapshot and
lets later CLI code distinguish structural manifest failures from repairable
generated-reference drift without parsing human-readable audit output.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import AbstractSet, Any, Iterable, Iterator, Mapping, Sequence

from catalogue.collect import (
    CatalogueContext,
    ModelEntry,
    catalogue_projection,
    is_runtime_target_instrument,
    reconcile_stem_semantics,
)
from core.model_stem_manifest import StemSemanticsRegistry
from core.model_stem_semantics import MODEL_STEM_INTENTS
from core.stem_roles import (
    StemId,
    StemProcessingContext,
    StemProduction,
    StemReviewStatus,
    StemRoleId,
)

STEM_SEMANTICS_REFERENCE_HEADERS = (
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
)
STEM_SEMANTICS_IDENTITY_HEADERS = (
    "runtime_family",
    "runtime_basename",
    "catalogue_source",
    "catalogue_label",
    "execution_arch",
)

_COMPLEMENT_ONLY_NAMES = frozenset({"drum-bass", "no bass", "no drums", "no other"})
_PINNED_EVIDENCE_COUNTS = (148, 123, 92)
_REVIEWED_VOCAL_SPLIT_IDS = frozenset(
    {
        "mdx:mbr_bve_gonzaluigi",
        "mdx:model_MelBand-Roformer_BVE_by-Gonza",
        "vr:UVR-BVE-4B_SN-44100-1",
    }
)


@dataclass(frozen=True, slots=True)
class CatalogueEvidenceCounts:
    """Provenanced vocabulary measurements; never semantic declarations."""

    literal_names: int
    normalized_names: int
    primary_names: int
    community_tokens: tuple[str, ...]

    @property
    def complement_only_names(self) -> int:
        """Number of fixed complement-only vocabulary supplements."""
        return len(_COMPLEMENT_ONLY_NAMES)


@dataclass(frozen=True, slots=True)
class StemAuditDiagnostic:
    """One machine-readable strict finding tied to exact catalogue identities."""

    code: str
    model_ids: tuple[str, ...]
    message: str
    context: StemProcessingContext | None = None
    expected: tuple[str, ...] = ()
    actual: tuple[str, ...] = ()
    structural: bool = True


@dataclass(frozen=True, slots=True)
class StemSemanticReferenceRow:
    """One immutable audit-owned reviewed route or exact waiver row."""

    runtime_family: str
    runtime_basename: str
    catalogue_source: str
    catalogue_label: str
    execution_arch: str
    model_id: str
    model_display: str
    native_signature: tuple[str, ...]
    processing_context: StemProcessingContext
    native_stem: str
    production: str
    backend_primary: str
    backend_target: str
    logical_primary: bool | None
    logical_secondary: bool | None
    role_id: str
    canonical_name: str
    filename_tag: str
    pair_id: str
    intent: str
    intent_source: str
    review_status: str
    evidence_or_waiver: str
    complement_of: str = ""
    derived_from: tuple[str, ...] = ()
    selected_by_default: bool | None = None

    def tsv_cells(self) -> tuple[str, ...]:
        """Return the fixed Task 2 TSV schema without presentation inference."""

        def boolean(value: bool | None) -> str:
            return "" if value is None else str(value).lower()

        return (
            self.runtime_family,
            self.runtime_basename,
            self.catalogue_source,
            self.catalogue_label,
            self.execution_arch,
            self.model_id,
            self.model_display,
            "|".join(self.native_signature),
            self.processing_context.value,
            self.native_stem,
            self.production,
            self.backend_primary,
            self.backend_target,
            boolean(self.logical_primary),
            boolean(self.logical_secondary),
            self.role_id,
            self.canonical_name,
            self.filename_tag,
            self.pair_id,
            self.intent,
            self.intent_source,
            self.review_status,
            self.evidence_or_waiver,
            self.complement_of,
            "|".join(self.derived_from),
            boolean(self.selected_by_default),
        )


def _tsv_cell(value: object) -> str:
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def reference_rows_tsv(rows: Sequence[StemSemanticReferenceRow]) -> str:
    """Canonical candidate bytes used to verify the separate renderer."""
    headers = (*STEM_SEMANTICS_IDENTITY_HEADERS, *STEM_SEMANTICS_REFERENCE_HEADERS)
    lines = ["\t".join(headers)]
    lines.extend("\t".join(_tsv_cell(cell) for cell in row.tsv_cells()) for row in rows)
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class StemRelationshipEvidence:
    """One exact reviewed native/context/role use in a catalogue model."""

    model_id: str
    context: StemProcessingContext
    native: str
    role_id: str


@dataclass(frozen=True, slots=True)
class NativeToRoleAmbiguity:
    """One normalized native key carrying multiple reviewed role meanings."""

    normalized_native: str
    native_spellings: tuple[str, ...]
    role_ids: tuple[str, ...]
    model_ids: tuple[str, ...]
    evidence: tuple[StemRelationshipEvidence, ...]


@dataclass(frozen=True, slots=True)
class RoleToNativeVariant:
    """One reviewed role emitted under multiple normalized native keys."""

    role_id: str
    normalized_natives: tuple[str, ...]
    native_spellings: tuple[str, ...]
    model_ids: tuple[str, ...]
    evidence: tuple[StemRelationshipEvidence, ...]


@dataclass(frozen=True, slots=True)
class StemAuditResult:
    """Structured outcome for one supplied catalogue/manifest projection."""

    catalogue_model_ids: tuple[str, ...]
    reviewed_model_ids: tuple[str, ...]
    waived_model_ids: tuple[str, ...]
    raw_model_ids: tuple[str, ...]
    evidence_counts: CatalogueEvidenceCounts
    diagnostics: tuple[StemAuditDiagnostic, ...]
    reference_rows: tuple[StemSemanticReferenceRow, ...] = ()
    native_to_role_ambiguities: tuple[NativeToRoleAmbiguity, ...] = ()
    role_to_native_variants: tuple[RoleToNativeVariant, ...] = ()

    @property
    def structurally_valid(self) -> bool:
        return not any(diagnostic.structural for diagnostic in self.diagnostics)

    @property
    def reference_matches(self) -> bool:
        return not any(
            diagnostic.code == "reference-candidate-mismatch" for diagnostic in self.diagnostics
        )

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    def diagnostics_for(self, model_id: str) -> tuple[StemAuditDiagnostic, ...]:
        """Return all findings that explicitly affect ``model_id``."""
        return tuple(
            diagnostic for diagnostic in self.diagnostics if model_id in diagnostic.model_ids
        )

    def diagnostics_with_code(self, code: str) -> tuple[StemAuditDiagnostic, ...]:
        """Return findings of one stable machine-readable kind."""
        return tuple(diagnostic for diagnostic in self.diagnostics if diagnostic.code == code)


@dataclass(frozen=True, slots=True)
class _ContextRoleProjection:
    """Declared roles and the roles that survived exact runtime resolution."""

    model_id: str
    context: StemProcessingContext
    declared_roles: frozenset[str]
    resolved_roles: frozenset[str]
    semantics: Any | None = None


def _audit_key(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _signature_matches(expected: Sequence[str], actual: Sequence[str]) -> bool:
    expected_keys = tuple(_audit_key(value) for value in expected)
    actual_keys = tuple(_audit_key(value) for value in actual)
    return expected_keys == actual_keys


def _sorted_model_ids(model_ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(model_ids), key=lambda value: (value.casefold(), value)))


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


def _catalogue_model_id(entry: ModelEntry) -> str:
    return catalogue_projection(entry)[0]


def _community_stem_tokens(stems_text: str) -> tuple[str, ...]:
    tokens = []
    for raw in stems_text.split(","):
        token = raw.replace("*", "").strip()
        token = token.split("(", 1)[0].strip()
        if token and token.casefold() != "unknown":
            tokens.append(token)
    return tuple(tokens)


def catalogue_evidence_counts(
    entries: Sequence[ModelEntry], community_by_file: Mapping[str, Any]
) -> CatalogueEvidenceCounts:
    """Measure the approved evidence universe without inventing semantics."""
    current_files = {str(entry.weight_file).casefold() for entry in entries}
    literals = set(_COMPLEMENT_ONLY_NAMES)
    primary = set()
    community_tokens = set()
    for entry in entries:
        literals.update(str(stem) for stem in entry.instruments if str(stem))
        if entry.primary_stem:
            value = str(entry.primary_stem)
            literals.add(value)
            primary.add(value.casefold())
        if entry.target_instrument:
            literals.add(str(entry.target_instrument))
    for filename, reference in community_by_file.items():
        if filename.casefold() not in current_files:
            continue
        for token in _community_stem_tokens(str(reference.stems_text)):
            literals.add(token)
            community_tokens.add(token)
    return CatalogueEvidenceCounts(
        literal_names=len(literals),
        normalized_names=len({value.casefold() for value in literals}),
        primary_names=len(primary),
        community_tokens=tuple(sorted(community_tokens, key=str.casefold)),
    )


def _context_value(raw_context: object) -> StemProcessingContext | None:
    try:
        if isinstance(raw_context, StemProcessingContext):
            return raw_context
        return StemProcessingContext(str(raw_context))
    except ValueError:
        return None


def _output_role(output: Any) -> str:
    return str(output.role)


def _native_outputs(context: Any) -> tuple[Any, ...]:
    return tuple(output for output in context.outputs if output.native is not None)


def _derived_outputs(context: Any) -> tuple[Any, ...]:
    return tuple(output for output in context.outputs if output.native is None)


def _diagnostic_sort_key(
    diagnostic: StemAuditDiagnostic,
) -> tuple[str, tuple[str, ...], str, str]:
    context = diagnostic.context.value if diagnostic.context is not None else ""
    return diagnostic.code, diagnostic.model_ids, context, diagnostic.message


def _role_users(registry: StemSemanticsRegistry) -> Mapping[str, set[str]]:
    users: dict[str, set[str]] = defaultdict(set)
    for model_id, declaration in registry.models.items():
        for context in declaration.contexts.values():
            for output in context.outputs:
                users[_output_role(output)].add(model_id)
    return users


def _affected_role_users(
    roles: Iterable[object],
    users: Mapping[str, set[str]],
    catalogue_model_ids: tuple[str, ...],
) -> tuple[str, ...]:
    affected = {model_id for role in roles for model_id in users.get(str(role), set())}
    return _sorted_model_ids(affected) or catalogue_model_ids


def _role_collision_diagnostics(
    registry: StemSemanticsRegistry,
    catalogue_model_ids: tuple[str, ...],
) -> list[StemAuditDiagnostic]:
    users = _role_users(registry)
    diagnostics = []
    for field_name, code in (
        ("display", "role-display-collision"),
        ("filename_tag", "role-tag-collision"),
    ):
        grouped: dict[str, list[object]] = defaultdict(list)
        for role_id, definition in registry.roles.items():
            grouped[_audit_key(getattr(definition, field_name))].append(role_id)
        for normalized_value, roles in grouped.items():
            if len(roles) < 2:
                continue
            role_ids = tuple(sorted((str(role) for role in roles), key=str.casefold))
            diagnostics.append(
                StemAuditDiagnostic(
                    code=code,
                    model_ids=_affected_role_users(roles, users, catalogue_model_ids),
                    message=(
                        f"roles {', '.join(role_ids)} share normalized {field_name} "
                        f"{normalized_value!r}"
                    ),
                    actual=role_ids,
                )
            )
    return diagnostics


def _unused_role_diagnostics(
    registry: StemSemanticsRegistry,
    catalogue_model_ids: tuple[str, ...],
) -> list[StemAuditDiagnostic]:
    used = {
        output.role
        for declaration in registry.models.values()
        for context in declaration.contexts.values()
        for output in context.outputs
        if isinstance(output.role, StemRoleId)
    }
    used.update(role for pair in registry.pairs.values() for role in pair.roles)
    unused = tuple(sorted((str(role) for role in set(registry.roles) - used), key=str.casefold))
    if not unused:
        return []
    return [
        StemAuditDiagnostic(
            code="role-unused",
            model_ids=catalogue_model_ids,
            message="role definitions must be used by a context output or pair",
            actual=unused,
        )
    ]


def _route_collision_diagnostics(
    model_id: str,
    context: StemProcessingContext,
    outputs: Sequence[Any],
    registry: StemSemanticsRegistry,
) -> list[StemAuditDiagnostic]:
    diagnostics = []
    for field_name, code in (
        ("display", "route-display-collision"),
        ("filename_tag", "route-tag-collision"),
    ):
        grouped: dict[str, list[str]] = defaultdict(list)
        for output in outputs:
            if not isinstance(output.role, StemRoleId):
                continue
            definition = registry.roles.get(output.role)
            if definition is None:
                continue
            grouped[_audit_key(getattr(definition, field_name))].append(str(output.role))
        for normalized, roles in grouped.items():
            role_ids = tuple(sorted(set(roles), key=str.casefold))
            if len(role_ids) < 2:
                continue
            diagnostics.append(
                StemAuditDiagnostic(
                    code=code,
                    model_ids=(model_id,),
                    context=context,
                    message=(
                        f"routes {', '.join(role_ids)} share normalized {field_name} "
                        f"{normalized!r} in one rendered context"
                    ),
                    actual=role_ids,
                )
            )
    return diagnostics


def _pair_diagnostics(
    registry: StemSemanticsRegistry,
    catalogue_model_ids: tuple[str, ...],
    context_projections: Sequence[_ContextRoleProjection],
) -> list[StemAuditDiagnostic]:
    users = _role_users(registry)
    diagnostics = []
    pair_ids_by_role: dict[str, list[str]] = defaultdict(list)
    for pair_id, pair in registry.pairs.items():
        roles = tuple(pair.roles)
        for role in roles:
            pair_ids_by_role[str(role)].append(pair_id)
        present = tuple(role for role in roles if role in registry.roles)
        definition_is_complete = len(roles) == 2 and roles[0] != roles[1] and len(present) == 2
        if not definition_is_complete:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="pair-incomplete",
                    model_ids=_affected_role_users(roles, users, catalogue_model_ids),
                    message=f"{pair_id} must define two distinct existing roles",
                    expected=tuple(str(role) for role in roles),
                    actual=tuple(str(role) for role in present),
                )
            )
            continue
        expected_roles = tuple(str(role) for role in roles)
        expected_role_set = frozenset(expected_roles)
        for projection in context_projections:
            if not expected_role_set.issubset(projection.declared_roles):
                continue
            if expected_role_set.issubset(projection.resolved_roles):
                continue
            diagnostics.append(
                StemAuditDiagnostic(
                    code="pair-context-incomplete",
                    model_ids=(projection.model_id,),
                    context=projection.context,
                    message=f"{pair_id} resolved without every declared pair role",
                    expected=expected_roles,
                    actual=tuple(
                        role for role in expected_roles if role in projection.resolved_roles
                    ),
                )
            )
    for role, pair_ids in pair_ids_by_role.items():
        if len(pair_ids) < 2:
            continue
        diagnostics.append(
            StemAuditDiagnostic(
                code="pair-role-collision",
                model_ids=_affected_role_users((role,), users, catalogue_model_ids),
                message=f"role {role} belongs to multiple pairs",
                expected=("one pair",),
                actual=tuple(sorted(pair_ids, key=str.casefold)),
            )
        )
    return diagnostics


def _target_projection_diagnostics(
    model_id: str,
    declaration: Any,
    runtime_signature: tuple[str, ...],
) -> list[StemAuditDiagnostic]:
    diagnostics = []
    for raw_context, declared_context in declaration.contexts.items():
        context = _context_value(raw_context)
        if not _signature_matches(declaration.native_signature, runtime_signature):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="target-runtime-signature",
                    model_ids=(model_id,),
                    context=context,
                    message="target-instrument declaration does not match runtime inventory",
                    expected=tuple(declaration.native_signature),
                    actual=runtime_signature,
                )
            )
        native = _native_outputs(declared_context)
        native_names = tuple(output.native.raw for output in native)
        native_is_valid = (
            len(native) == 1
            and native[0].production is StemProduction.NATIVE
            and _signature_matches(native_names, runtime_signature)
        )
        if not native_is_valid:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="target-native-output",
                    model_ids=(model_id,),
                    context=context,
                    message="target context must expose exactly one native runtime source",
                    expected=runtime_signature,
                    actual=native_names,
                )
            )
        derived = _derived_outputs(declared_context)
        native_role = _output_role(native[0]) if len(native) == 1 else ""
        dependency_is_valid = (
            len(derived) == 1
            and str(derived[0].complement_of or "") == native_role
            and not derived[0].derived_from
        )
        if (
            len(derived) != 1
            or derived[0].production is not StemProduction.DERIVED
            or not dependency_is_valid
        ):
            actual_dependencies = tuple(
                str(role)
                for output in derived
                for role in (
                    (output.complement_of,)
                    if output.complement_of is not None
                    else output.derived_from
                )
            )
            diagnostics.append(
                StemAuditDiagnostic(
                    code="target-derived-complement",
                    model_ids=(model_id,),
                    context=context,
                    message=(
                        "target context must expose one derived complement with an explicit "
                        "dependency on its native role"
                    ),
                    expected=(native_role,) if native_role else (),
                    actual=actual_dependencies,
                )
            )
    return diagnostics


def _context_diagnostics(
    model_id: str,
    declaration: Any,
    runtime_signature: tuple[str, ...],
    semantics_by_context: Mapping[StemProcessingContext, Any],
    registry: StemSemanticsRegistry,
) -> tuple[list[StemAuditDiagnostic], bool, list[_ContextRoleProjection]]:
    diagnostics = []
    full_mix_reviewed = False
    projections = []
    if StemProcessingContext.FULL_MIX not in declaration.contexts:
        diagnostics.append(
            StemAuditDiagnostic(
                code="missing-full-mix",
                model_ids=(model_id,),
                context=StemProcessingContext.FULL_MIX,
                message="reviewed declaration has no full_mix context",
            )
        )
    for raw_context, declared_context in declaration.contexts.items():
        context = _context_value(raw_context)
        if context is None:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-invalid",
                    model_ids=(model_id,),
                    message=f"declaration contains invalid context {raw_context!r}",
                    actual=(str(raw_context),),
                )
            )
            continue
        roles = tuple(_output_role(output) for output in declared_context.outputs)
        if len(set(roles)) != len(roles):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-duplicate-role",
                    model_ids=(model_id,),
                    context=context,
                    message="processing context maps more than one output to the same role",
                    actual=roles,
                )
            )
        logical_primary = str(declared_context.logical_primary)
        primary_count = sum(role == logical_primary for role in roles)
        if primary_count != 1:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-logical-primary",
                    model_ids=(model_id,),
                    context=context,
                    message="processing context must contain its logical primary exactly once",
                    expected=(logical_primary,),
                    actual=tuple(role for role in roles if role == logical_primary),
                )
            )
        logical_secondary_value = getattr(declared_context, "logical_secondary", None)
        if logical_secondary_value is not None:
            logical_secondary = str(logical_secondary_value)
            secondary_matches = tuple(role for role in roles if role == logical_secondary)
            if logical_secondary == logical_primary or len(secondary_matches) != 1:
                diagnostics.append(
                    StemAuditDiagnostic(
                        code="context-logical-secondary",
                        model_ids=(model_id,),
                        context=context,
                        message=(
                            "processing context logical secondary must be distinct from "
                            "primary and occur exactly once"
                        ),
                        expected=(logical_secondary,),
                        actual=secondary_matches,
                    )
                )
        if declaration.intent == "karaoke" and str(logical_secondary_value or "") != "vocal.lead":
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-logical-secondary-required",
                    model_ids=(model_id,),
                    context=context,
                    message="karaoke contexts must declare vocal.lead as logical secondary",
                    expected=("vocal.lead",),
                    actual=(str(logical_secondary_value),) if logical_secondary_value else (),
                )
            )
        native_names = tuple(output.native.raw for output in _native_outputs(declared_context))
        if not _signature_matches(declaration.native_signature, native_names):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-native-signature",
                    model_ids=(model_id,),
                    context=context,
                    message="context native outputs do not match the declaration signature",
                    expected=tuple(declaration.native_signature),
                    actual=native_names,
                )
            )
        resolved = semantics_by_context.get(context)
        if resolved is None:
            projections.append(
                _ContextRoleProjection(
                    model_id,
                    context,
                    frozenset(roles),
                    frozenset(),
                    None,
                )
            )
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-resolution-error",
                    model_ids=(model_id,),
                    context=context,
                    message="reconciled snapshot has no projection for the declared context",
                )
            )
            continue
        projections.append(
            _ContextRoleProjection(
                model_id,
                context,
                frozenset(roles),
                frozenset(
                    str(output.role)
                    for output in resolved.outputs
                    if isinstance(output.role, StemRoleId)
                ),
                resolved,
            )
        )
        declared_by_role = {_output_role(output): output for output in declared_context.outputs}
        resolved_by_role = {_output_role(output): output for output in resolved.outputs}
        if tuple(declared_by_role) != tuple(resolved_by_role):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="reference-route-set",
                    model_ids=(model_id,),
                    context=context,
                    message="resolved reference routes differ from declared routes or order",
                    expected=tuple(declared_by_role),
                    actual=tuple(resolved_by_role),
                )
            )
        expected_secondary_role = str(logical_secondary_value or "")
        actual_secondary_role = str(resolved.logical_secondary_role or "")
        if expected_secondary_role != actual_secondary_role:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="reference-logical-secondary",
                    model_ids=(model_id,),
                    context=context,
                    message="resolved context has stale logical-secondary role evidence",
                    expected=(expected_secondary_role,) if expected_secondary_role else (),
                    actual=(actual_secondary_role,) if actual_secondary_role else (),
                )
            )
        for output in resolved.outputs:
            role_id = _output_role(output)
            declared_output = declared_by_role.get(role_id)
            if declared_output is None:
                continue
            expected_native = declared_output.native.raw if declared_output.native else ""
            actual_native = output.native.raw if output.native else ""
            expected_route = (
                expected_native,
                declared_output.production.value,
                str(declared_output.complement_of or ""),
                *(str(role) for role in declared_output.derived_from),
            )
            actual_route = (
                actual_native,
                output.production.value,
                str(output.complement_of or ""),
                *(str(role) for role in output.derived_from),
            )
            if expected_route != actual_route:
                diagnostics.append(
                    StemAuditDiagnostic(
                        code="reference-route-data",
                        model_ids=(model_id,),
                        context=context,
                        message="resolved reference route differs from its declaration",
                        expected=expected_route,
                        actual=actual_route,
                    )
                )
            expected_primary = role_id == logical_primary
            if type(output.logical_primary) is not bool or (
                output.logical_primary is not expected_primary
            ):
                diagnostics.append(
                    StemAuditDiagnostic(
                        code="reference-logical-primary",
                        model_ids=(model_id,),
                        context=context,
                        message="resolved route has stale logical-primary evidence",
                        expected=(str(expected_primary).lower(),),
                        actual=(str(output.logical_primary).lower(),),
                    )
                )
            expected_secondary = logical_secondary_value is not None and role_id == str(
                logical_secondary_value
            )
            if type(output.logical_secondary) is not bool or (
                output.logical_secondary is not expected_secondary
            ):
                diagnostics.append(
                    StemAuditDiagnostic(
                        code="reference-logical-secondary",
                        model_ids=(model_id,),
                        context=context,
                        message="resolved route has stale logical-secondary evidence",
                        expected=(str(expected_secondary).lower(),),
                        actual=(str(output.logical_secondary).lower(),),
                    )
                )
            expected_default = declared_output.selected_by_default
            if (
                type(expected_default) is not bool
                or type(output.selected_by_default) is not bool
                or (output.selected_by_default is not expected_default)
            ):
                diagnostics.append(
                    StemAuditDiagnostic(
                        code="reference-selected-by-default",
                        model_ids=(model_id,),
                        context=context,
                        message="resolved route has stale default-selection evidence",
                        expected=(str(expected_default).lower(),),
                        actual=(str(output.selected_by_default).lower(),),
                    )
                )
        native_role_ids = {
            _output_role(output) for output in declared_context.outputs if output.native is not None
        }
        for output in declared_context.outputs:
            complement = str(output.complement_of or "")
            dependencies = tuple(str(role) for role in output.derived_from)
            native_recipe_valid = (
                output.production is StemProduction.NATIVE and not complement and not dependencies
            )
            complement_recipe_valid = (
                output.production is StemProduction.DERIVED
                and bool(complement)
                and not dependencies
                and complement in native_role_ids
            )
            derived_recipe_valid = (
                output.production is StemProduction.DERIVED
                and not complement
                and len(dependencies) >= 2
                and len(set(dependencies)) == len(dependencies)
                and set(dependencies).issubset(native_role_ids)
            )
            recipe_valid = (
                native_recipe_valid
                if output.native is not None
                else complement_recipe_valid or derived_recipe_valid
            )
            if recipe_valid:
                continue
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-recipe-invalid",
                    model_ids=(model_id,),
                    context=context,
                    message="route does not satisfy the schema-2 production recipe",
                    expected=(
                        (
                            "native route without recipe"
                            if output.native is not None
                            else "two-or-more native role dependencies"
                            if dependencies
                            else "complement_of one native role"
                        ),
                    ),
                    actual=tuple(filter(None, (complement, *dependencies))),
                )
            )
        if resolved.status is not StemReviewStatus.REVIEWED:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-unreviewed",
                    model_ids=(model_id,),
                    context=context,
                    message=resolved.warning or "processing context resolved without review",
                )
            )
        elif context is StemProcessingContext.FULL_MIX:
            full_mix_reviewed = True
    fully_reviewed = (
        full_mix_reviewed
        and len(projections) == len(declaration.contexts)
        and all(
            projection.semantics is not None
            and projection.semantics.status is StemReviewStatus.REVIEWED
            for projection in projections
        )
    )
    return diagnostics, fully_reviewed, projections


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


def audit_catalogue_stems(
    entries: Sequence[ModelEntry],
    context: CatalogueContext,
    *,
    expected_reference_text: str = "",
    actual_reference_text: str | None = None,
    registry: StemSemanticsRegistry,
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
    declaration_ids = set(selected_registry.models)
    waiver_ids = set(selected_registry.waivers)
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

    for model_id, declaration in selected_registry.models.items():
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
        context_findings, model_reviewed, model_context_projections = _context_diagnostics(
            model_id,
            declaration,
            runtime_signature,
            {semantics.context: semantics for semantics in reconciled.contexts},
            selected_registry,
        )
        diagnostics.extend(context_findings)
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
    if actual_evidence != _PINNED_EVIDENCE_COUNTS:
        diagnostics.append(
            StemAuditDiagnostic(
                code="evidence-count",
                model_ids=catalogue_model_ids,
                message="catalogue evidence vocabulary differs from the reviewed baseline",
                expected=tuple(str(value) for value in _PINNED_EVIDENCE_COUNTS),
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


# The confidence audit is intentionally separate from the strict local audit
# above. The latter validates one already-collected publication snapshot;
# this optional review traverses remote mvsepless entries and range-reads
# checkpoints to establish whether karaoke metadata is curated or guessed.


@dataclass(frozen=True, slots=True)
class HashLookup:
    """Outcome of one remote checkpoint-tail fingerprint attempt."""

    digest: str = ""
    status: str = "no_url"
    error: str = ""


class HashCache:
    """Persistent successful checkpoint hashes keyed by their source URL."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._records: dict[str, dict[str, Any]] = {}
        self._dirty = False
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                self._records = {
                    str(key): value for key, value in payload.items() if isinstance(value, dict)
                }
        except (OSError, ValueError):
            pass

    def get(self, url: str) -> HashLookup | None:
        record = self._records.get(url)
        if not record or record.get("status") != "ok" or not record.get("digest"):
            return None
        return HashLookup(digest=str(record["digest"]), status="ok")

    def put(self, url: str, lookup: HashLookup) -> None:
        if lookup.status != "ok" or not lookup.digest:
            return
        self._records[url] = {
            "digest": lookup.digest,
            "status": "ok",
            "fetched_at": time.time(),
        }
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        from core.json_store import write_json_atomic

        try:
            write_json_atomic(self.path, self._records)
            self._dirty = False
        except OSError:
            pass


def default_hash_cache_path() -> str:
    from scripts.model_tool_support import cache_dir

    return os.path.join(cache_dir(), "checkpoint_tail_hashes.json")


@dataclass(slots=True)
class StemConfidenceEntry:
    """One human-review row from the optional remote confidence audit."""

    entry_id: str
    label: str
    stems: list[str] = field(default_factory=list)
    is_karaoke: bool = False
    is_karaoke_curated: bool = False
    is_bv: bool = False
    buckets: list[str] = field(default_factory=list)
    error: str = ""
    hash_status: str = ""
    hash_error: str = ""


def _confidence_access_policy(policy: Any) -> Any:
    from core.access_policy import AccessPolicy

    return AccessPolicy(
        allow_network=bool(policy.allow_network),
        allow_metadata_writes=False,
        allow_cache_writes=bool(policy.allow_cache_writes),
    )


def _confidence_targets(policy: Any) -> list[Any]:
    """Load mvsepless targets with the generator's exact network policy."""
    from core.catalogue_coordinator import CatalogueCoordinator
    from core.catalogue_types import RefreshMode, SourceId
    from scripts.model_tool_support import iter_catalogue_targets

    coordinator = CatalogueCoordinator()
    try:
        source = coordinator.source(SourceId.MVSEPLESS)
        access = _confidence_access_policy(policy)
        # Audits need a complete target list now, unlike the UI's
        # stale-while-revalidate path. Read disk cache first; only a cold
        # online miss blocks for a fetch. Explicit --refresh remains FORCE.
        source.load(mode=RefreshMode.OFFLINE, policy=access)
        if policy.allow_network and (policy.refresh or source.state.content is None):
            source.load(mode=RefreshMode.FORCE, policy=access)
        content = source.state.content
        payload = dict(content.payload) if content is not None else {}
        return list(iter_catalogue_targets(payload, unsupported_only=False))
    finally:
        coordinator.close()


def _remote_checkpoint_hash(
    checkpoint_url: str,
    *,
    cache: HashCache | None = None,
    allow_network: bool = True,
    refresh: bool = False,
) -> HashLookup:
    if not checkpoint_url:
        return HashLookup(status="no_url")
    if cache is not None and not refresh:
        cached = cache.get(checkpoint_url)
        if cached is not None:
            return cached
    if not allow_network:
        return HashLookup(status="offline")
    from scripts.model_tool_support import checkpoint_tail_hash

    try:
        digest = checkpoint_tail_hash(checkpoint_url)
    except Exception as exc:  # noqa: BLE001 - one unreachable checkpoint is a finding, not a crash
        return HashLookup(status="fetch_failed", error=f"{type(exc).__name__}: {exc}")
    result = HashLookup(digest=digest, status="ok")
    if cache is not None:
        cache.put(checkpoint_url, result)
    return result


def _curated_hash_table() -> dict[str, dict[str, Any]]:
    from core import paths
    from core.model_data import load_model_hash_data

    table: dict[str, dict[str, Any]] = {}
    for path in (paths.VR_HASH_JSON, paths.MDX_HASH_JSON):
        try:
            table.update(load_model_hash_data(path))
        except (FileNotFoundError, ValueError, OSError):
            pass
    return table


def _confidence_config(target: Any, policy: Any) -> dict[str, Any]:
    """Read a target config through the catalogue cache and access policy."""
    from catalogue.collect import _fetch_yaml_bytes
    from core.model_data import load_mdx_c_config, load_mdx_c_config_data
    from scripts.model_tool_support import cache_dir, cache_name

    url = str(getattr(target, "config_url", ""))
    name = str(getattr(target, "config_name", "")) or "config.yaml"
    # Preserve the old standalone command's warm config cache while moving its
    # refresh-aware future fetches onto the catalogue cache policy.
    legacy_path = os.path.join(cache_dir(), cache_name(url, name))
    if not policy.refresh and os.path.isfile(legacy_path):
        return load_mdx_c_config(legacy_path)
    data, _path = _fetch_yaml_bytes(url, name, policy=policy)
    if data is None:
        mode = "offline" if not policy.allow_network else "cache/network"
        raise OSError(f"configuration unavailable from {mode}: {url or name}")
    return load_mdx_c_config_data(data)


def _confidence_entry_for_target(
    target: Any,
    curated_table: Mapping[str, dict[str, Any]],
    *,
    policy: Any,
    cache: HashCache | None,
) -> StemConfidenceEntry:
    try:
        config = _confidence_config(target, policy)
    except Exception as exc:  # noqa: BLE001 - retain one-row-per-target review output
        return StemConfidenceEntry(
            entry_id=str(target.entry_id), label=str(target.label), error=str(exc)
        )

    training = config.get("training") or {}
    stems = [str(stem) for stem in (training.get("instruments") or [])]
    lookup = _remote_checkpoint_hash(
        str(getattr(target, "checkpoint_url", "")),
        cache=cache,
        allow_network=bool(policy.allow_network),
        refresh=bool(policy.refresh),
    )
    curated_data = curated_table.get(lookup.digest) if lookup.status == "ok" else None
    hash_status = (
        "matched"
        if lookup.status == "ok" and curated_data
        else "unmatched"
        if lookup.status == "ok"
        else lookup.status
    )
    from core.model_stem_semantics import confident_stem_bucket, resolve_karaoke_confidence

    is_bv = bool((curated_data or {}).get("is_bv_model") or getattr(target, "is_bv_model", False))
    is_karaoke, is_curated = resolve_karaoke_confidence(
        model_data=curated_data,
        model_name=str(target.label),
        config_yaml=str(getattr(target, "config_url", "")),
        weight_basename=str(getattr(target, "checkpoint_url", "")),
    )
    buckets = [
        confident_stem_bucket(
            stem,
            stem_count=len(stems) or 2,
            is_karaoke=is_karaoke,
            is_karaoke_curated=is_curated,
            is_bv=is_bv,
        )
        for stem in stems
    ]
    return StemConfidenceEntry(
        entry_id=str(target.entry_id),
        label=str(target.label),
        stems=stems,
        is_karaoke=is_karaoke,
        is_karaoke_curated=is_curated,
        is_bv=is_bv,
        buckets=buckets,
        hash_status=hash_status,
        hash_error=lookup.error,
    )


def select_confidence_targets(
    targets: Sequence[Any], *, only: str = "", limit: int | None = None
) -> list[Any]:
    picked = list(targets)
    if only:
        needle = only.casefold()
        picked = [
            target
            for target in picked
            if needle in str(getattr(target, "entry_id", "")).casefold()
            or needle in str(getattr(target, "label", "")).casefold()
        ]
    if limit is not None and limit >= 0:
        picked = picked[:limit]
    return picked


def iter_stem_confidence_entries(
    *,
    policy: Any,
    guessed_only: bool = False,
    show_progress: bool = False,
    only: str = "",
    limit: int | None = None,
    cache: HashCache | None = None,
) -> Iterator[StemConfidenceEntry]:
    targets = select_confidence_targets(_confidence_targets(policy), only=only, limit=limit)
    curated_table = _curated_hash_table()
    total = len(targets)
    for index, target in enumerate(targets, 1):
        if show_progress:
            print(
                f"[{index:>{len(str(total))}}/{total}] {target.entry_id}: {target.label}",
                file=sys.stderr,
                flush=True,
            )
        entry = _confidence_entry_for_target(target, curated_table, policy=policy, cache=cache)
        if guessed_only and entry.is_karaoke_curated:
            continue
        yield entry


def render_stem_confidence_table(entries: Sequence[StemConfidenceEntry]) -> str:
    lines = []
    for entry in entries:
        if entry.error:
            lines.append(f"{entry.entry_id:40s} ERROR={entry.error}")
            continue
        confidence = "curated" if entry.is_karaoke_curated else "guessed"
        lines.append(
            f"{entry.entry_id:40s} karaoke={entry.is_karaoke!s:5s} ({confidence:7s}) "
            f"hash={entry.hash_status:12s} bv={entry.is_bv!s:5s} "
            f"stems={entry.stems} buckets={entry.buckets}"
        )
    return "\n".join(lines)


def render_stem_confidence_summary(entries: Sequence[StemConfidenceEntry]) -> str:
    from collections import Counter

    statuses = Counter(entry.hash_status for entry in entries if not entry.error)
    curated = sum(1 for entry in entries if not entry.error and entry.is_karaoke_curated)
    guessed = sum(1 for entry in entries if not entry.error and not entry.is_karaoke_curated)
    config_errors = sum(1 for entry in entries if entry.error)
    parts = [f"{len(entries)} entries", f"{curated} curated", f"{guessed} guessed"]
    for status in ("matched", "unmatched", "no_url", "offline", "fetch_failed"):
        if statuses.get(status):
            parts.append(f"{statuses[status]} {status}")
    if config_errors:
        parts.append(f"{config_errors} config error")
    return "  ".join(parts)


def write_stem_confidence_json(path: str, entries: Sequence[StemConfidenceEntry]) -> None:
    """Atomically replace a requested JSON report after a complete audit."""
    tmp_path = f"{path}.part"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump([asdict(entry) for entry in entries], handle, indent=2)
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def run_stem_confidence_audit(
    *,
    policy: Any,
    guessed_only: bool = False,
    only: str = "",
    limit: int | None = None,
    json_path: str | None = None,
    quiet: bool = False,
    no_hash_cache: bool = False,
) -> int:
    """Run the optional remote review without touching publication artifacts."""
    cache = None if no_hash_cache else HashCache(default_hash_cache_path())
    try:
        entries = list(
            iter_stem_confidence_entries(
                policy=policy,
                guessed_only=guessed_only,
                show_progress=not quiet,
                only=only,
                limit=limit,
                cache=cache,
            )
        )
    except KeyboardInterrupt:
        if cache is not None:
            cache.save()
        print("\nStem-confidence audit interrupted; no report was written.", file=sys.stderr)
        return 130
    if cache is not None:
        cache.save()
    entries.sort(key=lambda entry: entry.is_karaoke_curated)
    print(render_stem_confidence_table(entries))
    print(render_stem_confidence_summary(entries), file=sys.stderr)
    if json_path:
        write_stem_confidence_json(json_path, entries)
    return 0


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
    "StemConfidenceEntry",
    "audit_catalogue_stems",
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
