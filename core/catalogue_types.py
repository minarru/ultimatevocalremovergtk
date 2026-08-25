"""Shared types for revisioned catalogue sources, snapshots, and deltas."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

ENVELOPE_SCHEMA = 1
ADAPTER_SCHEMA = 2

UPSTREAM_VR_KEYS = ("vr_download_list",)
UPSTREAM_VR_VIP_KEYS = ("vr_download_vip_list",)
UPSTREAM_DEMUCS_KEYS = ("demucs_download_list",)
UPSTREAM_DEMUCS_VIP_KEYS = ("demucs_download_vip_list",)
UPSTREAM_MDX_KEYS = (
    "mdx_download_list",
    "mdx23_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
)
UPSTREAM_MDX_VIP_KEYS = (
    "mdx_download_vip_list",
    "mdx23_download_vip_list",
    "mdx23c_download_vip_list",
    "roformer_download_vip_list",
    "scnet_download_vip_list",
    "bandit_download_vip_list",
)

#: Labels whose extras copies previously won Download Center rows because live
#: upstream SCNet/Bandit keys were omitted from ``_rebuild_catalogues``. With
#: those keys flattened first, a live upstream payload that defines the same
#: selectable keeps the upstream files instead.
PRIOR_EXTRAS_SCNET_BANDIT_WINNERS = (
    "SCnet: 4-stems Huge SCNet v1.2 by Aname",
    "SCnet: 4-stems Huge SCNet Bleedless by Aname",
    "SCnet: 4-stems Huge SCNet Fullness by Aname",
    "SCnet: 4-stems Huge SCNet Strong Fullness by Aname",
)


class SourceId(str, Enum):
    UPSTREAM = "upstream"
    POLITREES = "politrees"
    EXTRAS = "extras"
    MVSEPLESS = "mvsepless"


class RefreshMode(str, Enum):
    OFFLINE = "offline"
    STALE_WHILE_REVALIDATE = "swr"
    FORCE = "force"


class DeltaKind(str, Enum):
    SOURCES_CHANGED = "sources_changed"
    IDENTITY_REFINED = "identity_refined"
    METADATA_CHANGED = "metadata_changed"


def freeze_files(model: object) -> tuple[tuple[str, str], ...]:
    """Preserve source file insertion order as an immutable tuple."""
    if isinstance(model, dict):
        return tuple((str(name), str(ref)) for name, ref in model.items())
    text = str(model)
    if not text:
        return ()
    return ((text, ""),)


def thaw_files(files: Sequence[tuple[str, str]]) -> dict[str, str] | str:
    if len(files) == 1 and files[0][1] == "":
        return files[0][0]
    return {name: ref for name, ref in files}


def files_mapping(files: Sequence[tuple[str, str]]) -> dict[str, str]:
    if len(files) == 1 and files[0][1] == "":
        return {files[0][0]: ""}
    return {name: ref for name, ref in files}


def ordered_payload_items(
    payload: Mapping[str, Any],
) -> tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...]:
    items: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
    for key, catalogue in payload.items():
        if not isinstance(catalogue, dict) or str(key).startswith("_"):
            continue
        for label, model in catalogue.items():
            items.append((str(key), str(label), freeze_files(model)))
    return tuple(items)


def semantic_digest(payload: Mapping[str, Any], *, adapter_schema: int = ADAPTER_SCHEMA) -> str:
    """Hash ordered canonical entries; insertion order is part of identity."""
    hasher = hashlib.sha256()
    hasher.update(f"{int(adapter_schema)}\n".encode("utf-8"))
    for item in ordered_payload_items(payload):
        hasher.update(json.dumps(item, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def readonly_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if isinstance(value, MappingProxyType):
        return value
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True)
class StemSemanticRoute:
    """JSON-safe presentation of one exact semantic output route.

    ``native`` is always the backend key.  ``role``, ``display`` and
    ``filename_tag`` are one-way reviewed presentation data; callers must not
    feed any of them back into model resolution.
    """

    native: str | None
    role: str | None
    display: str
    filename_tag: str
    production: str
    logical_primary: bool
    derived_from: tuple[str, ...] = ()
    complement_of: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {
            "native": self.native,
            "role": self.role,
            "display": self.display,
            "filename_tag": self.filename_tag,
            "production": self.production,
            "logical_primary": self.logical_primary,
        }
        if self.derived_from:
            result["derived_from"] = list(self.derived_from)
        if self.complement_of is not None:
            result["complement_of"] = self.complement_of
        return result


@dataclass(frozen=True)
class StemSemanticProjection:
    """Consumer-safe view of raw backend values beside reviewed semantics."""

    backend_primary_stem: str | None
    backend_target_stem: str | None
    logical_primary_role: str | None
    status: str
    context: str
    routes: tuple[StemSemanticRoute, ...]
    canonical_roles: tuple[str, ...] = ()
    evidence: str = ""
    warning: str = ""

    def as_dict(self) -> dict[str, Any]:
        result = {
            "backend_primary_stem": self.backend_primary_stem,
            "backend_target_stem": self.backend_target_stem,
            "logical_primary_role": self.logical_primary_role,
            "stem_semantics_status": self.status,
            "stem_context": self.context,
            "stem_routes": [route.as_dict() for route in self.routes],
        }
        if self.warning:
            result["stem_semantics_warning"] = self.warning
        return result


@dataclass(frozen=True)
class CatalogueEntry:
    source_id: SourceId
    entry_id: str
    family: str
    label: str
    files: tuple[tuple[str, str], ...]
    list_key: str = ""
    stem_semantics: StemSemanticProjection | None = None


@dataclass(frozen=True)
class SourceContent:
    source_id: SourceId
    payload: Mapping[str, Any]
    semantic_digest: str
    adapter_schema: int
    fetched_at: float
    etag: str | None = None
    last_modified: str | None = None

    @property
    def revision(self) -> str:
        return self.semantic_digest


@dataclass
class SourceStatus:
    checked_at: float = 0.0
    last_success_at: float | None = None
    error: str | None = None
    backoff_until: float = 0.0
    failures: int = 0
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class SourceState:
    content: SourceContent | None = None
    status: SourceStatus = field(default_factory=SourceStatus)

    @property
    def fetched_at(self) -> float:
        return 0.0 if self.content is None else self.content.fetched_at


@dataclass(frozen=True)
class RevisionVector:
    upstream: str = ""
    politrees: str = ""
    extras: str = ""
    mvsepless: str = ""
    identity: str = ""
    adapter_schema: int = ADAPTER_SCHEMA

    def digest(self) -> str:
        return "|".join(
            (
                self.upstream,
                self.politrees,
                self.extras,
                self.mvsepless,
                self.identity,
                str(self.adapter_schema),
            )
        )


@dataclass(frozen=True)
class CatalogueDelta:
    kind: DeltaKind
    added: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    removed: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    changed: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def removal_only(self) -> bool:
        return (
            self.kind == DeltaKind.IDENTITY_REFINED
            and not self.added
            and not self.changed
            and bool(self.removed)
        )


@dataclass(frozen=True)
class RefreshReport:
    mode: RefreshMode
    succeeded: tuple[SourceId, ...] = ()
    failed: tuple[tuple[SourceId, str], ...] = ()
    stale: tuple[SourceId, ...] = ()
    mixed_age: bool = False
    upstream_live: bool = False
    usable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "succeeded": [item.value for item in self.succeeded],
            "failed": [[item.value, message] for item, message in self.failed],
            "stale": [item.value for item in self.stale],
            "mixed_age": self.mixed_age,
            "upstream_live": self.upstream_live,
            "usable": self.usable,
            "partial": bool(self.failed) and self.usable,
        }


__all__ = [
    "ADAPTER_SCHEMA",
    "CatalogueDelta",
    "CatalogueEntry",
    "DeltaKind",
    "ENVELOPE_SCHEMA",
    "PRIOR_EXTRAS_SCNET_BANDIT_WINNERS",
    "RefreshMode",
    "RefreshReport",
    "RevisionVector",
    "SourceContent",
    "SourceId",
    "SourceState",
    "SourceStatus",
    "UPSTREAM_DEMUCS_KEYS",
    "UPSTREAM_DEMUCS_VIP_KEYS",
    "UPSTREAM_MDX_KEYS",
    "UPSTREAM_MDX_VIP_KEYS",
    "UPSTREAM_VR_KEYS",
    "UPSTREAM_VR_VIP_KEYS",
    "files_mapping",
    "freeze_files",
    "ordered_payload_items",
    "readonly_mapping",
    "semantic_digest",
    "thaw_files",
]
