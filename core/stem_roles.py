"""Immutable native and reviewed stem-semantic value objects.

Native stem names remain opaque backend keys.  Reviewed roles are separate,
namespaced identifiers that can safely be used for semantic presentation and
compatibility once an exact model declaration has selected them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

ROLE_ID_RE = re.compile(
    r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
    r"(?:\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*)+$"
)


class StemProcessingContext(str, Enum):
    """Closed input contexts whose reviewed meanings may differ."""

    FULL_MIX = "full_mix"
    VOCAL_SPLIT = "vocal_split"


class StemProduction(str, Enum):
    """Whether a reviewed output is emitted directly or calculated."""

    NATIVE = "native"
    DERIVED = "derived"


class StemReviewStatus(str, Enum):
    """Trust status of a semantic projection."""

    REVIEWED = "reviewed"
    WAIVED = "waived"
    RAW = "raw"


class StemRoleFamily(str, Enum):
    """Closed broad families for data-defined semantic roles."""

    VOCAL = "vocal"
    MIX = "mix"
    INSTRUMENT = "instrument"
    EFFECT = "effect"
    SPATIAL = "spatial"
    CINEMATIC = "cinematic"
    RESIDUAL = "residual"


@dataclass(frozen=True, slots=True, order=True)
class StemRoleId:
    """A validated, namespaced semantic role identifier."""

    value: str

    def __post_init__(self) -> None:
        if not ROLE_ID_RE.fullmatch(self.value):
            raise ValueError(f"invalid stem role id: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class StemLiteral:
    """An unreviewed output name that remains isolated from known roles."""

    tag: str


@dataclass(frozen=True, slots=True)
class StemId:
    """Opaque model-output key retaining its exact runtime spelling."""

    raw: str

    def casefold(self) -> str:
        return str(self.raw or "").strip().casefold()

    def matches(self, other: str | StemId) -> bool:
        if isinstance(other, StemId):
            return self.casefold() == other.casefold()
        return self.casefold() == str(other or "").strip().casefold()

    def __str__(self) -> str:
        return self.raw


@dataclass(frozen=True, slots=True)
class StemRoleDefinition:
    """Reviewed presentation and grouping data for one semantic role."""

    id: StemRoleId
    display: str
    filename_tag: str
    family: StemRoleFamily
    removed_of: StemRoleId | None = None


@dataclass(frozen=True, slots=True)
class SemanticStemOutput:
    """A native or derived output projected into a reviewed semantic role."""

    native: StemId | None
    role: StemRoleId | StemLiteral
    production: StemProduction
    backend_primary: bool
    logical_primary: bool
    derived_from: tuple[StemRoleId, ...] = ()
    complement_of: StemRoleId | None = None
    selected_by_default: bool = True
    logical_secondary: bool = False


@dataclass(frozen=True, slots=True)
class ModelStemSemantics:
    """The reviewed or raw semantic projection selected for one model run."""

    model_id: str
    context: StemProcessingContext
    intent: str
    outputs: tuple[SemanticStemOutput, ...]
    status: StemReviewStatus
    evidence: str
    warning: str = ""
    logical_secondary_role: StemRoleId | StemLiteral | None = None
