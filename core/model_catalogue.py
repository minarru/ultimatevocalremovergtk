"""Frontend-neutral model catalogue discovery, filtering, and resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote, unquote

from bundled.constants import APOLLO_ARCH_TYPE, DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE

from .downloads import DownloadManager
from .model_naming import canonical_display_name
from .model_scores import (
    PURPOSE_ALL, filter_labels_by_purpose, parse_sdr_score, primary_sdr,
    purpose_for_label, sdr_for_files,
)

FAMILY_ARCH = {
    "vr": VR_ARCH_TYPE,
    "mdx": MDX_ARCH_TYPE,
    "demucs": DEMUCS_ARCH_TYPE,
    "apollo": APOLLO_ARCH_TYPE,
}


@dataclass(frozen=True)
class CatalogEntryId:
    family: str
    selection: str

    @property
    def value(self) -> str:
        return f"catalog:{self.family}:{quote(self.selection, safe='')}"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: str) -> "CatalogEntryId":
        prefix, separator, remainder = str(value).partition(":")
        family, separator_two, encoded = remainder.partition(":")
        if prefix != "catalog" or not separator or not separator_two or family not in FAMILY_ARCH:
            raise ValueError(f"invalid catalogue entry ID: {value!r}")
        return cls(family, unquote(encoded))


@dataclass(frozen=True)
class ModelCatalogueRecord:
    id: str
    family: str
    selection: str
    display: str
    purpose: str
    supported: bool
    installed: bool
    unsupported_reason: str | None = None
    score: float | None = None
    size: str | None = None
    intent: str | None = None


def catalogue_label_matches(label: str, query: str, *, extra: str = "") -> bool:
    folded = query.strip().casefold()
    return not folded or any(
        folded in value.casefold()
        for value in (label, canonical_display_name(label), extra) if value
    )


def filter_catalogue_labels(
    names: Iterable[str], query: str, *, purpose: str = PURPOSE_ALL,
    intents: dict[str, str] | None = None, sentinels: Iterable[str] = (),
) -> list[str]:
    blocked = set(sentinels)
    selectable = [name for name in names if name not in blocked]
    selectable = filter_labels_by_purpose(selectable, purpose, intents=intents)
    return [name for name in selectable if catalogue_label_matches(name, query)]


class ModelCatalogueService:
    def __init__(self, manager: DownloadManager | None = None):
        self.manager = manager or DownloadManager()
        self._records: tuple[ModelCatalogueRecord, ...] | None = None
        self._records_key: object = None

    def refresh(self, *, offline: bool = False) -> bool:
        self._records = None
        self._records_key = None
        if offline:
            return self.manager.ensure_catalogues(allow_network=False)
        live = self.manager.refresh()
        if live:
            return True
        return self.manager.ensure_catalogues(allow_network=False)

    def _snapshot_key(self) -> object:
        coordinator = getattr(self.manager, "_coordinator", None)
        snapshot = getattr(coordinator, "_latest", None) if coordinator is not None else None
        revision = getattr(snapshot, "revision", None)
        digest = revision.digest() if revision is not None and hasattr(revision, "digest") else None
        return (
            digest,
            self.manager.decoded_vip_link,
            len(self.manager.vr_download_list),
            len(self.manager.mdx_download_list),
            len(self.manager.demucs_download_list),
            len(self.manager.apollo_download_list),
        )

    def records(self) -> tuple[ModelCatalogueRecord, ...]:
        from core.download_sizes import describe_cached_download_size

        key = self._snapshot_key()
        if self._records is not None and self._records_key == key:
            return self._records

        rows: list[ModelCatalogueRecord] = []
        catalogues = {
            "vr": self.manager.vr_download_list,
            "mdx": self.manager.mdx_download_list,
            "demucs": self.manager.demucs_download_list,
            "apollo": self.manager.apollo_download_list,
        }
        unsupported = {
            (arch, label): reason
            for arch, values in self.manager.unsupported_download_list.items()
            for label, reason in values
        }
        for family, values in catalogues.items():
            arch = FAMILY_ARCH[family]
            for selection, model in values.items():
                meta = self.manager.catalogue_meta.get(selection)
                intent = str(getattr(meta, "intent", "") or "") or None
                reason = unsupported.get((arch, selection))
                jobs = self.manager.resolve(selection, arch, fetch_config=False)
                installed = bool(jobs) and all(os.path.isfile(path) for _url, path in jobs)
                scored = (
                    primary_sdr(
                        sdr_for_files(getattr(meta, "files", ()) or ()),
                        getattr(meta, "target_instrument", None),
                        stem_count=len(getattr(meta, "stems", ()) or ()) or 2,
                    )
                    if meta is not None else None
                )
                score = scored[1] if scored is not None else parse_sdr_score(selection)
                rows.append(ModelCatalogueRecord(
                    str(CatalogEntryId(family, selection)), family, selection,
                    canonical_display_name(selection),
                    purpose_for_label(selection, intent=intent), reason is None,
                    installed, reason, score,
                    describe_cached_download_size(jobs) if jobs else "—",
                    intent,
                ))
        self._records = tuple(rows)
        self._records_key = key
        return self._records

    def filter(
        self, *, family: str | None = None, query: str = "",
        purpose: str = PURPOSE_ALL, supported: bool | None = None,
        installed: bool | None = None,
    ) -> tuple[ModelCatalogueRecord, ...]:
        return tuple(
            row for row in self.records()
            if (family is None or row.family == family)
            and (purpose in {"", PURPOSE_ALL} or row.purpose == purpose)
            and (supported is None or row.supported is supported)
            and (installed is None or row.installed is installed)
            and catalogue_label_matches(row.selection, query, extra=row.unsupported_reason or "")
        )

    def resolve(self, reference: str) -> ModelCatalogueRecord:
        raw = str(reference).strip()
        records = self.records()
        if raw.startswith("catalog:"):
            parsed = CatalogEntryId.parse(raw)
            matches = [row for row in records if row.family == parsed.family and row.selection == parsed.selection]
        else:
            matches = [row for row in records if raw.casefold() in {row.selection.casefold(), row.display.casefold()}]
            if not matches:
                matches = [row for row in records if catalogue_label_matches(row.selection, raw)]
        if len(matches) != 1:
            candidates = ", ".join(row.id for row in matches[:8]) or "none"
            raise ValueError(f"unknown or ambiguous catalogue entry {reference!r}; matches: {candidates}")
        return matches[0]

    def jobs(self, records: Iterable[ModelCatalogueRecord]) -> tuple[tuple[ModelCatalogueRecord, tuple[tuple[str, str], ...]], ...]:
        return tuple(
            (record, tuple(self.manager.resolve(record.selection, FAMILY_ARCH[record.family])))
            for record in records
        )


__all__ = [
    "CatalogEntryId", "FAMILY_ARCH", "ModelCatalogueRecord",
    "ModelCatalogueService", "catalogue_label_matches", "filter_catalogue_labels",
]
