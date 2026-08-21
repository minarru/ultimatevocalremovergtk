"""Canonical model identities shared by the GTK and command-line frontends.

The processing engine still accepts the historical display-name and
``"Architecture: Display"`` forms.  This module owns the adapters so neither
frontend has to duplicate model-family inference or fuzzy lookup rules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

FAMILIES = ("vr", "mdx", "demucs", "apollo")
METHOD_BY_FAMILY = {
    "vr": VR_ARCH_PM,
    "mdx": MDX_ARCH_TYPE,
    "demucs": DEMUCS_ARCH_TYPE,
    "apollo": APOLLO_ARCH_TYPE,
}
ARCH_BY_FAMILY = {
    "vr": VR_ARCH_TYPE,
    "mdx": MDX_ARCH_TYPE,
    "demucs": DEMUCS_ARCH_TYPE,
    "apollo": APOLLO_ARCH_TYPE,
}
FAMILY_BY_ARCH = {value: key for key, value in ARCH_BY_FAMILY.items()}
FAMILY_BY_ARCH[VR_ARCH_PM] = "vr"
_LEGACY_FAMILIES = {
    VR_ARCH_TYPE.casefold(): "vr",
    VR_ARCH_PM.casefold(): "vr",
    MDX_ARCH_TYPE.casefold(): "mdx",
    DEMUCS_ARCH_TYPE.casefold(): "demucs",
}


def _qualified_family(token: str) -> str | None:
    """Return the model family if ``token`` already carries a family or arch prefix."""
    prefix, separator, _rest = str(token or "").strip().partition(":")
    if not separator:
        return None
    folded = prefix.casefold()
    if folded in FAMILIES:
        return folded
    return _LEGACY_FAMILIES.get(folded)


@dataclass(frozen=True, order=True)
class ModelId:
    family: str
    basename: str

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"unknown model family {self.family!r}")
        if not self.basename or ":" in self.basename:
            raise ValueError(f"invalid model basename {self.basename!r}")

    @property
    def value(self) -> str:
        return f"{self.family}:{self.basename}"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: str) -> "ModelId":
        return parse_stored_model_id(value)


def parse_stored_model_id(value: str) -> ModelId:
    """Parse an exact ``family:basename`` stored model identifier."""
    text = str(value or "").strip()
    family, separator, basename = text.partition(":")
    if not separator or family not in FAMILIES or not basename or ":" in basename:
        raise ValueError(f"not a canonical model ID: {value!r}")
    return ModelId(family, basename)


@dataclass(frozen=True)
class ModelArtifacts:
    primary_filename: str
    supporting_filenames: tuple[str, ...] = ()


@dataclass(frozen=True)
class DemucsSpec:
    version: Literal["v1", "v2", "v3", "v4"]
    source_layout: Literal["2_stem", "4_stem", "6_stem"]


@dataclass(frozen=True)
class MdxSpec:
    kind: Literal[
        "classic_onnx",
        "mdx23c",
        "mel_band_roformer",
        "bs_roformer",
        "scnet",
        "scnet_masked",
        "scnet_tran",
        "bandit",
        "bandit_v2",
    ]


@dataclass(frozen=True)
class CatalogueRef:
    family: str
    selection: str


@dataclass(frozen=True)
class ModelRecord:
    id: str
    family: str
    basename: str
    display: str
    backend_name: str
    artifacts: ModelArtifacts
    installed: bool
    catalogue_entry: CatalogueRef | None = None
    identity_complete: bool = True
    identity_error: str | None = None
    demucs: DemucsSpec | None = None
    mdx: MdxSpec | None = None

    @property
    def model_id(self) -> ModelId:
        return ModelId(self.family, self.basename)

    @property
    def method(self) -> str:
        return METHOD_BY_FAMILY[self.family]

    @property
    def arch(self) -> str:
        return ARCH_BY_FAMILY[self.family]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "family": self.family,
            "basename": self.basename,
            "display": self.display,
            "backend_name": self.backend_name,
            "primary_artifact": self.artifacts.primary_filename,
            "supporting_artifacts": list(self.artifacts.supporting_filenames),
            "installed": self.installed,
            "identity_complete": self.identity_complete,
        }
        if self.identity_error:
            payload["identity_error"] = self.identity_error
        if self.demucs is not None:
            payload["demucs_version"] = self.demucs.version
            payload["source_layout"] = self.demucs.source_layout
        if self.mdx is not None:
            payload["mdx_kind"] = self.mdx.kind
        return payload


class IdentityIndex:
    def __init__(self, records: Mapping[str, ModelRecord]):
        self._records = dict(records)

    def lookup(self, model_id: str) -> ModelRecord:
        key = parse_stored_model_id(model_id).value
        try:
            return self._records[key]
        except KeyError:
            raise ValueError(f"unknown model {model_id!r}") from None

    def records(self) -> tuple[ModelRecord, ...]:
        return tuple(self._records.values())


def _normalize(value: str) -> str:
    return "".join(ch for ch in str(value).casefold() if ch.isalnum())


class _ModelInventory:
    """Resolve model references against one :class:`ModelRepository`."""

    def __init__(self, repo: Any):
        self.repo = repo

    def records(self) -> tuple[ModelRecord, ...]:
        from .model_display import map_basenames_to_display

        result: dict[str, ModelRecord] = {}
        for family, lister in (
            ("vr", self.repo.list_vr_models),
            ("mdx", self.repo.list_mdx_models),
            ("demucs", self.repo.list_demucs_models),
        ):
            basenames = list(lister())
            displays = map_basenames_to_display(
                basenames, ARCH_BY_FAMILY[family], self.repo,
                allow_network=False,
            )
            for basename, display in zip(basenames, displays):
                model_id = str(ModelId(family, basename))
                result[model_id] = ModelRecord(
                    id=model_id,
                    family=family,
                    basename=basename,
                    display=display or basename,
                    backend_name=basename,
                    artifacts=ModelArtifacts(primary_filename=basename),
                    installed=True,
                )
        from .apollo import list_apollo_models

        for filename in list_apollo_models():
            basename = os.path.splitext(filename)[0]
            model_id = str(ModelId("apollo", basename))
            result[model_id] = ModelRecord(
                id=model_id,
                family="apollo",
                basename=basename,
                display=basename,
                backend_name=filename,
                artifacts=ModelArtifacts(primary_filename=filename),
                installed=True,
            )
        # Installed basenames, casefolded per family. The setdefault below only
        # defers to an installed model on an exact-case key, so a catalogue
        # label differing only in case became a second, uninstallable record
        # for the same checkpoint -- and made the real one unresolvable.
        installed_folded = {
            (record.family, record.basename.casefold()) for record in result.values()
        }
        for family, index in (
            ("vr", self._cached_index("vr_catalogue_display_index")),
            ("mdx", self._cached_index("mdx_catalogue_display_index")),
            ("demucs", self._cached_index("demucs_catalogue_display_index")),
        ):
            for basename, display in index.items():
                if (family, str(basename).casefold()) in installed_folded:
                    continue
                model_id = str(ModelId(family, str(basename)))
                result.setdefault(
                    model_id,
                    ModelRecord(
                        id=model_id,
                        family=family,
                        basename=str(basename),
                        display=str(display),
                        backend_name=str(basename),
                        artifacts=ModelArtifacts(primary_filename=str(basename)),
                        installed=False,
                    ),
                )
        return tuple(result.values())

    def _cached_index(self, name: str) -> dict[str, str]:
        provider = getattr(self.repo, name)
        try:
            return provider(allow_network=False)
        except TypeError:
            return provider()

    def resolve(
        self, query: str, *, fuzzy: bool = True, family: str | None = None,
        allowed_families: Iterable[str] | None = None,
    ) -> ModelRecord:
        raw = str(query or "").strip()
        token_family = _qualified_family(raw)
        if family is not None:
            family = family.casefold()
            if family not in FAMILIES:
                raise ValueError(f"unknown model family {family!r}")
            if token_family is not None:
                if token_family != family:
                    raise ValueError(
                        f"model {raw!r} does not belong to required family {family}"
                    )
            elif raw:
                raw = f"{family}:{raw}"
        records = self.records()
        if allowed_families is not None:
            allowed = frozenset(str(value).casefold() for value in allowed_families)
            invalid = allowed.difference(FAMILIES)
            if invalid:
                raise ValueError(f"unknown model family {sorted(invalid)[0]!r}")
            if token_family is not None and token_family not in allowed:
                raise ValueError(f"model {query!r} is not eligible for this setting")
            records = tuple(record for record in records if record.family in allowed)
        return resolve_model_record(raw, records, fuzzy=fuzzy)


def resolve_model_record(
    query: str, records: Iterable[ModelRecord], *, fuzzy: bool = True
) -> ModelRecord:
    """Resolve ``query`` against an already-enumerated model inventory."""
    raw = str(query or "").strip()
    if not raw:
        raise ValueError("model value is empty")
    records = tuple(records)
    family = _qualified_family(raw)
    prefix, separator, _basename = raw.partition(":")
    if separator and prefix in FAMILIES:
        canonical_id = ModelId.parse(raw).value
        for record in records:
            if record.id == canonical_id:
                return record
        raise ValueError(f"unknown model {raw!r}")
    term = raw.partition(":")[2].strip() if family is not None else raw
    candidates = tuple(
        record for record in records if family is None or record.family == family
    )
    # An exact id is unambiguous by construction, so it must be tried on its
    # own. Folding it in with the casefold comparisons below let a
    # case-variant sibling (two records for one checkpoint) dilute a
    # character-for-character match into "ambiguous".
    by_id = tuple(record for record in candidates if raw == record.id)
    if len(by_id) == 1:
        return by_id[0]
    exact = tuple(
        record
        for record in candidates
        if term.casefold() == record.basename.casefold()
        or term.casefold() == record.display.casefold()
        or term.casefold() == record.backend_name.casefold()
    )
    if len(exact) == 1:
        return exact[0]
    if not fuzzy:
        raise ValueError(f"unknown model {raw!r}")
    needle = _normalize(os.path.splitext(os.path.basename(term))[0])
    matched = {
        record.id: record
        for record in candidates
        if needle
        and (
            needle in _normalize(record.basename)
            or needle in _normalize(record.display)
            or needle in _normalize(record.backend_name)
        )
    }
    if len(matched) == 1:
        return next(iter(matched.values()))
    if matched:
        names = ", ".join(sorted(matched)[:8])
        raise ValueError(f"ambiguous model {raw!r}; matches: {names}")
    qualifier = f" in family {family}" if family else ""
    raise ValueError(f"unknown or unregistered model {raw!r}{qualifier}")


class ModelIdentityService(_ModelInventory):

    def display_label(self, reference: str) -> str:
        return self.resolve(reference).display

    def legacy_member_tag(self, reference: str | ModelRecord) -> str:
        record = reference if isinstance(reference, ModelRecord) else self.resolve(reference)
        if record.family == "apollo":
            raise ValueError("Apollo restoration models cannot be ensemble members")
        return f"{record.arch}: {record.display}"

    def canonical_id_from_member_tag(self, tag: str) -> str:
        from .model_display import parse_model_tag, resolve_model_basename

        arch, name = parse_model_tag(str(tag))
        family = FAMILY_BY_ARCH.get(arch)
        if family is None:
            return self.resolve(str(tag)).id
        basename = resolve_model_basename(arch, name, self.repo)
        # The mapper may resolve an uninstalled but known model.  Preserve that
        # stable identity; execution validation remains responsible for proving
        # that its checkpoint exists.
        if basename:
            return str(ModelId(family, basename))
        return self.resolve(str(tag)).id

    def engine_value(
        self, reference: str, *, member: bool = False, family: str | None = None
    ) -> str:
        """Convert a canonical/legacy reference to the value legacy engines consume."""
        record = self.resolve(reference, family=family)
        return self.legacy_member_tag(record) if member else record.backend_name


def iter_model_records(repo: Any) -> Iterable[ModelRecord]:
    return ModelIdentityService(repo).records()


def resolve_model_id(query: str, repo: Any) -> ModelRecord:
    return ModelIdentityService(repo).resolve(query)


def canonical_member_tag(record: ModelRecord) -> str:
    return f"{record.arch}: {record.display}"


def canonical_id_from_member_tag(tag: str, repo: Any) -> str:
    return ModelIdentityService(repo).canonical_id_from_member_tag(tag)


__all__ = [
    "ARCH_BY_FAMILY",
    "CatalogueRef",
    "DemucsSpec",
    "FAMILIES",
    "FAMILY_BY_ARCH",
    "IdentityIndex",
    "MdxSpec",
    "METHOD_BY_FAMILY",
    "ModelArtifacts",
    "ModelId",
    "ModelIdentityService",
    "ModelRecord",
    "canonical_id_from_member_tag",
    "canonical_member_tag",
    "iter_model_records",
    "parse_stored_model_id",
    "resolve_model_id",
    "resolve_model_record",
]
