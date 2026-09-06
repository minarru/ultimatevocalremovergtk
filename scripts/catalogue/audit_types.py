"""Audit types for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Mapping,
)

from core.stem_roles import (
    StemProcessingContext,
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


# Reviewed 2026-08-27 unified snapshot, including exact config evidence served
# from the bundled manifest when live/cache bytes are unavailable.
_PINNED_EVIDENCE_COUNTS = (155, 123, 92)


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
class ManifestCandidateResult:
    """A normalized unified manifest plus exact reconciliation findings."""

    document: dict[str, object]
    diagnostics: tuple[StemAuditDiagnostic, ...]
    current_model_ids: tuple[str, ...]
    retired_model_ids: tuple[str, ...]
    evidence_states: Mapping[str, int]
    reference_drift_model_ids: tuple[str, ...] = ()
    presentation: Mapping[str, Any] | None = None

    @property
    def structurally_valid(self) -> bool:
        return not any(diagnostic.structural for diagnostic in self.diagnostics)

    @property
    def degraded(self) -> bool:
        return any(diagnostic.code.endswith("evidence-missing") for diagnostic in self.diagnostics)

    @property
    def same_semantics_digest_drift_count(self) -> int:
        return sum(diagnostic.code == "config-digest-drift" for diagnostic in self.diagnostics)

    @property
    def semantic_mismatch_count(self) -> int:
        return sum(diagnostic.code == "config-semantic-mismatch" for diagnostic in self.diagnostics)

    @property
    def lifecycle_drift_count(self) -> int:
        return sum(diagnostic.code.startswith("manifest-") for diagnostic in self.diagnostics)

    @property
    def reference_drift_count(self) -> int:
        return len(self.reference_drift_model_ids)


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
    def reviewed_context_count(self) -> int:
        """Distinct reviewed ``(model, context)`` pairs owned by audit rows."""
        return len(
            {
                (row.model_id, row.processing_context)
                for row in self.reference_rows
                if row.review_status == "reviewed"
            }
        )

    @property
    def reviewed_karaoke_declaration_count(self) -> int:
        """Distinct reviewed karaoke model declarations owned by audit rows."""
        return len(
            {
                row.model_id
                for row in self.reference_rows
                if row.review_status == "reviewed" and row.intent == "karaoke"
            }
        )

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


@dataclass(frozen=True, slots=True)
class ContextAssessment:
    diagnostics: tuple[StemAuditDiagnostic, ...]
    projection: _ContextRoleProjection
    full_mix_reviewed: bool


@dataclass(frozen=True, slots=True)
class ModelContextAssessment:
    diagnostics: tuple[StemAuditDiagnostic, ...]
    fully_reviewed: bool
    projections: tuple[_ContextRoleProjection, ...]
