"""Types for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import (
    Dict,
    List,
    Tuple,
)

from core.stem_roles import (
    ModelStemSemantics,
)


@dataclass
class CommunityRef:
    filename: str
    arch: str
    primary_stem: str
    stems_text: str
    friendly_name: str
    intent: str = ""


@dataclass
class CatalogueContext:
    community_by_file: Dict[str, CommunityRef] = field(default_factory=dict)
    #: Required supplements that could not be read at all. An empty but valid
    #: response is evidence too; callers must not confuse zero rows with an
    #: unavailable source and reject a coherent snapshot on that basis.
    unavailable_supplemental_evidence: Tuple[str, ...] = ()
    #: Per-model configs required by the collected membership but unavailable
    #: or unparseable in the checked-in seed plus URL-keyed generator cache.
    #: A set keeps duplicate catalogue aliases from inflating the diagnostic.
    unavailable_yaml_evidence: set[str] = field(default_factory=set)


@dataclass
class ModelEntry:
    source: str
    family: str
    catalogue_label: str
    weight_file: str
    config_yaml: str = ""
    config_url: str = ""
    config_sha256: str = ""
    arch: str = ""
    primary_stem: str = ""
    secondary_stem: str = ""
    instruments: List[str] = field(default_factory=list)
    target_instrument: str = ""
    stem_count: int = 0
    is_karaoke: bool = False
    name_intent: str = ""
    best_result: str = ""
    backend_focus: str = ""
    ui_export_note: str = ""
    metadata_source: str = ""
    flags: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Family-specific prose that should win over the generic derivation in
    # _best_result. Set by a family overlay *before* _finalize_entry runs.
    best_result_override: str = ""
    # Attached once, after collection, from exact canonical identity plus the
    # reconciled runtime signature. Renderers and audit consume this frozen
    # evidence instead of independently resolving the same entry again.
    stem_semantics: ReconciledStemEvidence | None = None


@dataclass(frozen=True, slots=True)
class ReconciledStemEvidence:
    """Exact semantic evidence attached to one collected catalogue row."""

    model_id: str
    model_display: str
    native_signature: tuple[str, ...]
    runtime_warning: str
    reviewed: bool
    contexts: tuple[ModelStemSemantics, ...]
    guessed_intent: str = ""
    guessed_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewedResultProjection:
    """Human-facing result fields derived only from exact reviewed routes."""

    intent: str
    best_result: str
    ui_export_note: str
