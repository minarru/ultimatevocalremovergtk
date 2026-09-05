"""GTK-free catalogue projection, selection and pinned enqueue source."""

from __future__ import annotations

import typing
from dataclasses import dataclass

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    NO_CONNECTION,
    NO_NEW_MODELS,
    VR_ARCH_TYPE,
)
from core.catalogue_coordinator import CatalogueSnapshot
from core.model_catalogue import (
    catalogue_label_matches,
    filter_catalogue_labels,
    project_catalogue_display,
)
from core.model_identity import FAMILY_BY_ARCH
from core.model_naming import canonical_display_name
from core.model_scores import (
    ARCH_FILTER_ALL,
    MDX_NETWORK_SUBTYPES,
    NETWORK_FILTER_OPTIONS,
    PURPOSE_ALL,
    PURPOSE_FILTER_OPTIONS,
    PURPOSE_INSTRUMENTAL,
    PURPOSE_PAGE_OPTIONS,
    PURPOSE_VOCALS,
    SORT_NAME,
    SORT_SDR,
    catalogue_network_id,
    family_arch_for_network_filter,
    label_matches_purpose,
    network_filter_matches,
    parse_sdr_score,
    purpose_for_label,
    purpose_pages_for_label,
    purpose_roles_from_meta,
    purpose_roles_from_projection,
)


def catalogue_semantics_subtitle(meta: typing.Any) -> str:
    """Render reviewed route labels, or an explicit raw-output fallback."""
    projection = getattr(meta, "stem_semantics", None)
    routes = tuple(getattr(projection, "routes", ()) or ())
    evidence = getattr(meta, "catalogue_evidence_status", "unavailable")
    evidence_value = str(getattr(evidence, "value", evidence) or "")
    if evidence_value == "not_applicable":
        return "Restoration · output details not applicable"
    if (
        getattr(projection, "status", "raw") == "reviewed"
        and routes
        and evidence_value in {"ready", "stale"}
    ):
        ordered = sorted(routes, key=lambda route: not route.logical_primary)
        stems = ", ".join(route.display for route in ordered)
        intent = str(getattr(meta, "intent", "") or "")
        primary_role, output_roles = purpose_roles_from_projection(projection)
        pages = purpose_pages_for_label(
            str(getattr(meta, "label", "") or ""),
            intent=intent,
            arch=str(getattr(meta, "arch", "") or ""),
            primary_role=primary_role,
            output_roles=output_roles,
        )
        if pages == frozenset({PURPOSE_VOCALS, PURPOSE_INSTRUMENTAL}):
            purpose = "Vocals & instrumental"
        else:
            page = next(iter(pages), "")
            purpose = next(
                (label for value, label in PURPOSE_PAGE_OPTIONS if value == page),
                next(
                    (
                        label
                        for value, label in PURPOSE_FILTER_OPTIONS
                        if value
                        == purpose_for_label(
                            str(getattr(meta, "label", "") or ""),
                            intent=intent,
                        )
                    ),
                    "Reviewed",
                ),
            )
        return f"{purpose} · {stems}"
    if evidence_value == "pending":
        return "Loading output details…"
    files = getattr(meta, "files", {}) or {}
    has_config = any(str(name).casefold().endswith((".yaml", ".yml")) for name in files)
    if evidence_value == "unavailable" and has_config:
        return "Output details unavailable"
    stems = ", ".join(str(stem) for stem in (getattr(meta, "stems", ()) or ()))
    return f"Raw outputs · {stems}" if stems else "Raw outputs"


def catalogue_evidence_detail(meta: typing.Any) -> str:
    """Return non-destructive evidence detail for a row tooltip."""
    return str(getattr(meta, "catalogue_evidence_warning", "") or "")


def catalogue_matches(
    names: list[str],
    query: str,
    *,
    purpose: str = PURPOSE_ALL,
    intents: typing.Mapping[str, str] | None = None,
    arches: typing.Mapping[str, str] | None = None,
    primary_roles: typing.Mapping[str, str] | None = None,
    output_roles: typing.Mapping[str, typing.Sequence[str]] | None = None,
) -> list[str]:
    """Return selectable catalogue names matching query and purpose filter.

    Matching covers both the raw catalogue label and its canonical rendering,
    so a user typing what the row *shows* finds it.
    """
    return filter_catalogue_labels(
        names,
        query,
        purpose=purpose,
        intents=dict(intents or {}),
        arches=dict(arches or {}),
        primary_roles=dict(primary_roles or {}),
        output_roles={label: tuple(roles) for label, roles in (output_roles or {}).items()},
        sentinels=(NO_NEW_MODELS, NO_CONNECTION),
    )


CatalogueKey = tuple[str, str]
_ARCH_ORDER = {
    value: index
    for index, (value, _) in enumerate(NETWORK_FILTER_OPTIONS)
    if value != ARCH_FILTER_ALL
}


@dataclass(frozen=True)
class BrowserFilters:
    purpose: str = PURPOSE_ALL
    network: str = ARCH_FILTER_ALL
    query: str = ""
    hide_unsupported: bool = False
    sort_mode: str = SORT_NAME


@dataclass(frozen=True)
class BrowserRow:
    key: CatalogueKey
    display: str
    network: str
    reason: str | None = None
    intent: str | None = None
    primary_role: str | None = None
    output_roles: tuple[str, ...] = ()
    sdr_stem: str | None = None
    sdr: float | None = None
    semantics: str = ""
    evidence_detail: str = ""
    count_roles: tuple[str | None, tuple[str, ...]] | None = None

    def purpose_kwargs(self) -> dict[str, typing.Any]:
        return dict(
            intent=self.intent,
            arch=self.key[0],
            primary_role=self.primary_role,
            output_roles=self.output_roles,
        )

    def sort_key(self, mode: str) -> tuple[int, int, int, float, str]:
        unsupported = self.reason is not None
        arch_index = _ARCH_ORDER.get(self.network, 99)
        if mode == SORT_SDR and not unsupported:
            return (
                int(unsupported),
                arch_index,
                int(self.sdr is None),
                -(self.sdr or 0.0),
                self.display.casefold(),
            )
        return int(unsupported), arch_index, 0, 0.0, self.display.casefold()


def project_row(
    arch: str,
    name: str,
    *,
    raw: typing.Any,
    meta: typing.Any,
    intent: str | None = None,
    reason: str | None = None,
    score: tuple[str | None, float | None] | None = None,
    display_meta: typing.Any = None,
) -> BrowserRow:
    family = FAMILY_BY_ARCH.get(arch)
    display = (
        project_catalogue_display(
            family, name, raw, display_meta if display_meta is not None else meta
        )
        if family
        else canonical_display_name(name)
    )
    files = getattr(meta, "files", {}) or {}
    network = catalogue_network_id(
        family_arch=arch, files=tuple(str(key) for key in files), label=name
    )
    primary_role, output_roles = purpose_roles_from_meta(meta)
    stem = None
    if score is not None:
        stem, score_value = score
    else:
        score_value = parse_sdr_score(name)
    return BrowserRow(
        (arch, name),
        display,
        network,
        reason,
        intent,
        primary_role,
        tuple(output_roles or ()),
        stem,
        score_value,
        catalogue_semantics_subtitle(meta) if meta is not None and reason is None else "",
        catalogue_evidence_detail(meta) if meta is not None else "",
    )


class CatalogueBrowserState:
    def __init__(self) -> None:
        self.rows: dict[CatalogueKey, BrowserRow] = {}
        self.available: dict[str, list[str]] = {}
        self.unsupported: dict[str, list[tuple[str, str]]] = {}
        self._selected: set[CatalogueKey] = set()
        self.snapshot: CatalogueSnapshot | None = None
        self.pending_source = False
        self.generation = 0
        self.filters = BrowserFilters()

    def pin(self, snapshot: CatalogueSnapshot | None) -> None:
        self.snapshot = snapshot

    def pinned_catalogue(self, arch: str) -> dict | None:
        if self.snapshot is None:
            return None
        family = FAMILY_BY_ARCH.get(arch)
        return dict(getattr(self.snapshot, family)) if family else None

    def replace_rows(self, rows: typing.Iterable[BrowserRow]) -> None:
        self.generation += 1
        self.rows = {row.key: row for row in rows}
        self._selected.intersection_update(
            key for key, row in self.rows.items() if row.reason is None
        )

    def remove_missing(self, live: set[CatalogueKey]) -> tuple[CatalogueKey, ...]:
        removed = tuple(key for key in self.rows if key not in live)
        for key in removed:
            del self.rows[key]
            self._selected.discard(key)
        return removed

    def set_selected(self, key: CatalogueKey, selected: bool) -> None:
        if selected and key in self.rows and self.rows[key].reason is None:
            self._selected.add(key)
        else:
            self._selected.discard(key)

    def selected_keys(self) -> tuple[CatalogueKey, ...]:
        return tuple(key for key in self.rows if key in self._selected)

    def selected_counts(self) -> dict[str, int]:
        counts = {value: 0 for value, _ in PURPOSE_PAGE_OPTIONS}
        for key in self.selected_keys():
            row = self.rows[key]
            for purpose in purpose_pages_for_label(key[1], **row.purpose_kwargs()):
                if purpose in counts:
                    counts[purpose] += 1
        return counts

    @staticmethod
    def matches(row: BrowserRow, filters: BrowserFilters, *, display_search: bool = True) -> bool:
        if filters.hide_unsupported and row.reason is not None:
            return False
        if not network_filter_matches(filters.network, family_arch=row.key[0], network=row.network):
            return False
        purpose_kwargs = row.purpose_kwargs()
        if not display_search and row.reason is None and row.count_roles is not None:
            purpose_kwargs['primary_role'], purpose_kwargs['output_roles'] = row.count_roles
        if not label_matches_purpose(row.key[1], filters.purpose, **purpose_kwargs):
            return False
        extra = f"{row.display} {row.reason or ''}".strip() if display_search else row.reason or ""
        return catalogue_label_matches(row.key[1], filters.query, extra=extra)

    def names_matching_network(self, arch: str, network: str) -> list[str]:
        names = list(self.available.get(arch) or [])
        if network not in MDX_NETWORK_SUBTYPES:
            return names
        return [
            name
            for name in names
            if (row := self.rows.get((arch, name))) is not None
            and network_filter_matches(network, family_arch=arch, network=row.network)
        ]

    @staticmethod
    def filter_archs(network: str) -> list[str]:
        family = family_arch_for_network_filter(network)
        return (
            [family]
            if family not in ('', ARCH_FILTER_ALL, None)
            else [VR_ARCH_TYPE, MDX_ARCH_TYPE, DEMUCS_ARCH_TYPE, APOLLO_ARCH_TYPE]
        )

    def matching_count(self, arch: str, filters: BrowserFilters) -> int:
        return sum(
            self.matches(row, filters, display_search=False)
            for row in self.rows.values()
            if row.key[0] == arch
        )

    def available_count(self) -> int:
        return sum(
            name not in (NO_NEW_MODELS, NO_CONNECTION)
            for names in self.available.values()
            for name in names
        )

    def unsupported_count(self, *, hide: bool = False) -> int:
        return 0 if hide else sum(len(rows) for rows in self.unsupported.values())


@dataclass(frozen=True)
class BrowserView:
    visible_keys: tuple[CatalogueKey, ...]
    placeholder_count: int
    title: str
    description: str = ''
    offline: bool = False


def project_browser(
    state: CatalogueBrowserState, filters: BrowserFilters, *, online: bool | None
) -> BrowserView:
    visible = tuple(
        row.key
        for row in sorted(state.rows.values(), key=lambda row: row.sort_key(filters.sort_mode))
        if state.matches(row, filters)
    )
    from dataclasses import replace

    placeholder = sum(
        state.matching_count(arch, replace(filters, query=''))
        for arch in state.filter_archs(filters.network)
    )
    if online is False and not state.available:
        return BrowserView(
            visible,
            placeholder,
            'Catalogue unavailable',
            'Check your connection and try again.',
            True,
        )
    if online is None:
        return BrowserView(visible, placeholder, 'Catalogue is still loading…', 'Please wait.')
    count = sum(
        state.matching_count(arch, filters)
        for arch in state.filter_archs(filters.network)
        if arch in FAMILY_BY_ARCH
    )
    any_rows = any(
        state.names_matching_network(arch, filters.network) or state.unsupported.get(arch)
        for arch in state.filter_archs(filters.network)
        if arch in FAMILY_BY_ARCH
    )
    if (filters.query or filters.purpose not in ('', PURPOSE_ALL, None)) and not count:
        description = (
            f'Try a broader search than “{filters.query}”.'
            if filters.query
            else 'No models match this purpose filter.'
        )
        return BrowserView(visible, placeholder, 'No matching models', description)
    if not any_rows:
        return BrowserView(
            visible,
            placeholder,
            'All installed',
            'All models for this purpose are already installed.',
        )
    return BrowserView(visible, placeholder, '')
