"""Canonical model identities shared by the GTK and command-line frontends.

The processing engine still accepts the historical ``"Architecture: Display"``
ensemble-member form.  This module owns the adapters so neither frontend has
to duplicate model-family inference or exact-identity lookup rules.
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
            record = self._records[key]
        except KeyError:
            raise ValueError(f"unknown model {model_id!r}") from None
        if (record.identity_error or "").startswith("identity collision between "):
            raise ValueError(f"unavailable model {model_id!r}: {record.identity_error}")
        return record

    def records(self) -> tuple[ModelRecord, ...]:
        return tuple(self._records.values())


class _ModelInventory:
    """Resolve model references against one :class:`ModelRepository`."""

    def __init__(self, repo: Any):
        self.repo = repo
        self._identity_cache_key: tuple[int, str, int] | None = None
        self._identity_cache: IdentityIndex | None = None

    def records(self) -> tuple[ModelRecord, ...]:
        from .model_repository import ModelRepository

        if isinstance(self.repo, ModelRepository) or hasattr(self.repo, "_inventory_lock"):
            return self._published_index().records()
        return self._legacy_records()

    def _legacy_records(self) -> tuple[ModelRecord, ...]:
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

    def _snapshot(self) -> Any | None:
        coordinator = getattr(self.repo, "catalogue", None)
        if coordinator is None:
            return None
        latest = getattr(coordinator, "_latest", None)
        if latest is not None:
            return latest
        ensure = getattr(coordinator, "ensure", None)
        if not callable(ensure):
            return None
        return ensure(vip=True, allow_network=False)

    def _published_index(self) -> IdentityIndex:
        from .model_inventory import build_identity_index

        repo = self.repo
        lock = getattr(repo, "_inventory_lock", None)
        if lock is None:
            return build_identity_index(repo, snapshot=self._snapshot())
        with lock:
            generation = repo.inventory_generation
            catalogue_revision = repo.catalogue_revision
            naming_revision = repo.naming_revision
            key = (generation, catalogue_revision, naming_revision)
            if self._identity_cache_key == key and self._identity_cache is not None:
                return self._identity_cache
            index = build_identity_index(repo, snapshot=self._snapshot())
            if (
                repo.inventory_generation != generation
                or repo.catalogue_revision != catalogue_revision
                or repo.naming_revision != naming_revision
            ):
                return self._published_index()
            self._identity_cache_key = key
            self._identity_cache = index
            return index

    @property
    def index(self) -> IdentityIndex:
        return self._published_index()

    def lookup(self, model_id: str) -> ModelRecord:
        from .model_repository import ModelRepository

        if isinstance(self.repo, ModelRepository) or hasattr(self.repo, "_inventory_lock"):
            return self._published_index().lookup(model_id)
        return resolve_model_record(model_id, self.records())

    def _cached_index(self, name: str) -> dict[str, str]:
        provider = getattr(self.repo, name)
        try:
            return provider(allow_network=False)
        except TypeError:
            return provider()

    def resolve(
        self, query: str, *, family: str | None = None,
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
        return resolve_model_record(raw, records)


def resolve_model_record(
    query: str, records: Iterable[ModelRecord]
) -> ModelRecord:
    """Resolve ``query`` against an already-enumerated model inventory.

    Accepts a canonical ``family:basename`` id, or -- for the command-line
    convenience paths -- a basename with or without a family qualifier. Never a
    display label: see the comment on the basename comparison below.
    """
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
    # Basename only. Matching ``record.display`` or ``record.backend_name`` here
    # would make a catalogue label change able to alter which model a stored or
    # typed reference selects, which spec invariant 4 forbids: display text is a
    # one-way projection of an identity, never an input to resolving one.
    exact = tuple(
        record
        for record in candidates
        if term.casefold() == record.basename.casefold()
    )
    if len(exact) == 1:
        return exact[0]
    if exact:
        names = ", ".join(sorted(record.id for record in exact)[:8])
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
        """Resolve an ensemble member reference to its canonical id.

        Accepts canonical ``family:basename`` ids, and legacy ``Arch: Name``
        tags whose name half is the model's basename. A legacy tag carrying a
        catalogue *display* label no longer resolves: inverting display text is
        what lets a catalogue rename change model selection. Such a member stays
        on disk as written until the user re-picks it.
        """
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
