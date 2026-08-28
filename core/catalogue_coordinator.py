"""Sole owner of catalogue source snapshots, projections, and publication."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Mapping

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    DOWNLOAD_CHECKS,
    MDX_ARCH_TYPE,
    VR_ARCH_TYPE,
)

from .access_policy import AccessPolicy, current_access_policy
from .catalogue_types import (
    ADAPTER_SCHEMA,
    UPSTREAM_DEMUCS_KEYS,
    UPSTREAM_DEMUCS_VIP_KEYS,
    UPSTREAM_MDX_KEYS,
    UPSTREAM_MDX_VIP_KEYS,
    UPSTREAM_VR_KEYS,
    UPSTREAM_VR_VIP_KEYS,
    CatalogueDelta,
    DeltaKind,
    RefreshMode,
    RefreshReport,
    RevisionVector,
    SourceContent,
    SourceId,
)
from .debug_log import log_event
from .remote_catalog_cache import RemoteJsonSource

DeltaCallback = Callable[[CatalogueDelta], None]


def flatten_upstream_lists(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Flatten every public and legacy-gated upstream download list.

    Later keys overwrite values but keep the original insertion slot
    (``dict.update``). Legacy ``*_vip_list`` names are compatibility-only;
    their entries are part of the sole public projection.
    """
    vr: dict[str, Any] = {}
    for key in (*UPSTREAM_VR_KEYS, *UPSTREAM_VR_VIP_KEYS):
        catalogue = payload.get(key)
        if isinstance(catalogue, dict):
            vr.update(catalogue)
    mdx: dict[str, Any] = {}
    for key in (*UPSTREAM_MDX_KEYS, *UPSTREAM_MDX_VIP_KEYS):
        catalogue = payload.get(key)
        if isinstance(catalogue, dict):
            mdx.update(catalogue)
    demucs: dict[str, Any] = {}
    for key in (*UPSTREAM_DEMUCS_KEYS, *UPSTREAM_DEMUCS_VIP_KEYS):
        catalogue = payload.get(key)
        if isinstance(catalogue, dict):
            demucs.update(catalogue)
    return vr, mdx, demucs


def yaml_basename_from_ref(ref: object) -> str | None:
    """Return a basename-only YAML reference from a compact catalogue value."""
    if not isinstance(ref, str):
        return None
    if "/" in ref or "\\" in ref:
        return None
    if not ref.casefold().endswith((".yaml", ".yml")):
        return None
    return ref


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


@dataclass(frozen=True)
class CatalogueSnapshot:
    """Deeply immutable published catalogue view."""

    revision: RevisionVector
    vr: Mapping[str, Any]
    mdx: Mapping[str, Any]
    demucs: Mapping[str, Any]
    apollo: Mapping[str, Any]
    meta: Mapping[str, Any]
    meta_by_family: Mapping[str, Mapping[str, Any]]
    pre_dedupe_vr: Mapping[str, Any]
    pre_dedupe_mdx: Mapping[str, Any]
    pre_dedupe_demucs: Mapping[str, Any]
    pre_dedupe_apollo: Mapping[str, Any]
    unsupported: Mapping[str, Any]
    display_index_vr: Mapping[str, str]
    display_index_mdx: Mapping[str, str]
    display_index_demucs: Mapping[str, str]
    checkpoint_yaml_index: Mapping[str, str]
    entry_sources: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    report: RefreshReport | None = None
    checkpoint_yaml_url_index: Mapping[tuple[str, str], str] = field(default_factory=dict)

    def download_lists(
        self,
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        return self.vr, self.mdx, self.demucs, self.apollo


def _readonly_catalogue(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


def build_meta_by_family(
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
    apollo: Mapping[str, Any],
    extra_meta: Mapping[str, Any],
    alias_meta: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    from .catalog_sources import _build_meta, _metadata_alias_index

    aliases = alias_meta if alias_meta is not None else _metadata_alias_index(extra_meta)
    return {
        "vr": _build_meta(vr, VR_ARCH_TYPE, extra_meta, aliases),
        "mdx": _build_meta(mdx, MDX_ARCH_TYPE, extra_meta, aliases),
        "demucs": _build_meta(demucs, DEMUCS_ARCH_TYPE, extra_meta, aliases),
        "apollo": _build_meta(apollo, APOLLO_ARCH_TYPE, extra_meta, aliases),
    }


class CatalogueCoordinator:
    """Thread-safe owner of source state and revisioned projections.

    Construct one per application or CLI command. Do not share a hidden
    process-global instance between tests.
    """

    def __init__(
        self,
        *,
        sources: Mapping[SourceId, RemoteJsonSource] | None = None,
        policy: AccessPolicy | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._policy = policy
        self._sources = dict(sources) if sources is not None else _default_sources()
        for source in self._sources.values():
            source._on_update = self._on_source_updated
        self._snapshots: dict[str, CatalogueSnapshot] = {}
        self._latest: CatalogueSnapshot | None = None
        self._delta_subscribers: list[DeltaCallback] = []
        self._identity_subscribers: list[Callable[[], None]] = []
        self._pending_force: threading.Event | None = None
        self._last_report: RefreshReport | None = None
        self._builds = 0
        self._bundled_parses = 0
        self._index_builds = 0

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._delta_subscribers.clear()
            self._identity_subscribers.clear()
            pending = self._pending_force
        if pending is not None:
            pending.set()
        for source in self._sources.values():
            source.close()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def builds(self) -> int:
        return self._builds

    def source(self, source_id: SourceId) -> RemoteJsonSource:
        return self._sources[source_id]

    def subscribe_delta(self, callback: DeltaCallback) -> None:
        with self._lock:
            if callback not in self._delta_subscribers:
                self._delta_subscribers.append(callback)

    def unsubscribe_delta(self, callback: DeltaCallback) -> None:
        with self._lock:
            try:
                self._delta_subscribers.remove(callback)
            except ValueError:
                pass

    def subscribe_identity_removal(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if callback not in self._identity_subscribers:
                self._identity_subscribers.append(callback)

    def unsubscribe_identity_removal(self, callback: Callable[[], None]) -> None:
        with self._lock:
            try:
                self._identity_subscribers.remove(callback)
            except ValueError:
                pass

    def captured_policy(self, policy: AccessPolicy | None = None) -> AccessPolicy:
        if policy is not None:
            return policy
        if self._policy is not None:
            return self._policy
        return current_access_policy()

    def snapshot(
        self,
        *,
        mode: RefreshMode = RefreshMode.OFFLINE,
        policy: AccessPolicy | None = None,
    ) -> CatalogueSnapshot:
        report = self.refresh(mode=mode, policy=policy, wait=mode is RefreshMode.FORCE)
        snap = self._latest
        if snap is None:
            snap = self._publish(report=report)
        return snap

    def ensure(
        self,
        *,
        allow_network: bool = True,
        policy: AccessPolicy | None = None,
    ) -> CatalogueSnapshot:
        captured = self.captured_policy(policy)
        if not allow_network:
            captured = AccessPolicy(
                allow_network=False,
                allow_metadata_writes=captured.allow_metadata_writes,
                allow_cache_writes=captured.allow_cache_writes,
            )
        mode = RefreshMode.STALE_WHILE_REVALIDATE if captured.allow_network else RefreshMode.OFFLINE
        return self.snapshot(mode=mode, policy=captured)

    def refresh(
        self,
        *,
        mode: RefreshMode = RefreshMode.FORCE,
        policy: AccessPolicy | None = None,
        wait: bool | None = None,
    ) -> RefreshReport:
        captured = self.captured_policy(policy)
        log_event(
            "download",
            "catalogue_refresh_started",
            mode=mode.value,
            allow_network=captured.allow_network,
            allow_cache_writes=captured.allow_cache_writes,
        )
        if self._closed:
            report = RefreshReport(mode=mode, usable=self._latest is not None)
            self._log_refresh_completed(report)
            return report
        if mode is RefreshMode.OFFLINE or not captured.allow_network:
            self._load_sources(RefreshMode.OFFLINE, captured)
            snapshot = self._publish(report=None)
            report = RefreshReport(
                mode=RefreshMode.OFFLINE,
                usable=bool(snapshot.vr or snapshot.mdx or snapshot.demucs or snapshot.apollo),
            )
            self._log_refresh_completed(report, snapshot)
            return report

        if mode is RefreshMode.STALE_WHILE_REVALIDATE:
            self._load_sources(RefreshMode.STALE_WHILE_REVALIDATE, captured)
            snapshot = self._publish(report=None)
            report = RefreshReport(
                mode=mode,
                usable=bool(snapshot.vr or snapshot.mdx or snapshot.demucs or snapshot.apollo),
            )
            self._log_refresh_completed(report, snapshot)
            return report

        report = self._coalesced_force(captured)
        self._log_refresh_completed(report)
        return report

    def _log_refresh_completed(
        self,
        report: RefreshReport,
        snapshot: CatalogueSnapshot | None = None,
    ) -> None:
        published = snapshot or self._latest
        log_event(
            "download",
            "catalogue_refresh_completed",
            level="warning" if report.failed else "debug",
            mode=report.mode.value,
            usable=report.usable,
            upstream_live=report.upstream_live,
            succeeded_sources=tuple(source.value for source in report.succeeded),
            failed_sources=tuple(source.value for source, _error in report.failed),
            failure_details={source.value: error for source, error in report.failed},
            stale_sources=tuple(source.value for source in report.stale),
            vr_count=len(published.vr) if published is not None else 0,
            mdx_count=len(published.mdx) if published is not None else 0,
            demucs_count=len(published.demucs) if published is not None else 0,
            apollo_count=len(published.apollo) if published is not None else 0,
        )

    def _on_source_updated(self) -> None:
        if self._closed:
            return
        report = self._last_report
        self._publish(report=report)

    def _coalesced_force(self, policy: AccessPolicy) -> RefreshReport:
        owner = False
        with self._lock:
            inflight = self._pending_force
            if inflight is None:
                inflight = threading.Event()
                self._pending_force = inflight
                owner = True
        if not owner:
            inflight.wait(timeout=120)
            return self._last_report or RefreshReport(
                mode=RefreshMode.FORCE, usable=self._latest is not None
            )
        try:
            report = self._force_refresh(policy)
            self._last_report = report
            return report
        finally:
            inflight.set()
            with self._lock:
                if self._pending_force is inflight:
                    self._pending_force = None

    def _force_refresh(self, policy: AccessPolicy) -> RefreshReport:
        errors: dict[SourceId, str] = {}
        succeeded: list[SourceId] = []
        stale: list[SourceId] = []
        upstream_live = False
        result_lock = threading.Lock()

        def run_source(source_id: SourceId) -> None:
            nonlocal upstream_live
            source = self._sources[source_id]
            state = source.load(mode=RefreshMode.FORCE, policy=policy)
            after = state.content
            with result_lock:
                if state.status.error:
                    errors[source_id] = state.status.error
                    if after is not None:
                        stale.append(source_id)
                else:
                    succeeded.append(source_id)
                    if source_id is SourceId.UPSTREAM and after is not None:
                        upstream_live = after.fetched_at > 0
                if after is not None and source._stale(after.fetched_at, source._now()):
                    if source_id not in stale:
                        stale.append(source_id)

        remotes = [
            SourceId.UPSTREAM,
            SourceId.POLITREES,
            SourceId.MVSEPLESS,
        ]
        threads: list[threading.Thread] = []
        extras = self._sources.get(SourceId.EXTRAS)
        if extras is not None:
            extras.load(mode=RefreshMode.FORCE, policy=policy)
            succeeded.append(SourceId.EXTRAS)
        for source_id in remotes:
            if source_id not in self._sources:
                continue
            thread = threading.Thread(
                target=run_source,
                args=(source_id,),
                name=f"uvr-catalogue-force-{source_id.value}",
                daemon=True,
            )
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        snapshot = self._publish(report=None)
        report = RefreshReport(
            mode=RefreshMode.FORCE,
            succeeded=tuple(succeeded),
            failed=tuple((key, errors[key]) for key in errors),
            stale=tuple(stale),
            mixed_age=bool(stale or errors),
            upstream_live=upstream_live and SourceId.UPSTREAM not in errors,
            usable=bool(snapshot.vr or snapshot.mdx or snapshot.demucs or snapshot.apollo),
        )
        snapshot = replace(snapshot, report=report)
        with self._lock:
            self._snapshots[snapshot.revision.digest()] = snapshot
            self._latest = snapshot
        return report

    def _load_sources(self, mode: RefreshMode, policy: AccessPolicy) -> None:
        for source in self._sources.values():
            source.load(mode=mode, policy=policy)

    def _contents(self) -> dict[SourceId, SourceContent | None]:
        return {source_id: source.state.content for source_id, source in self._sources.items()}

    def _revision(
        self,
        contents: Mapping[SourceId, SourceContent | None],
        *,
        identity: str,
    ) -> RevisionVector:
        def digest(source_id: SourceId) -> str:
            content = contents.get(source_id)
            return "" if content is None else content.semantic_digest

        return RevisionVector(
            upstream=digest(SourceId.UPSTREAM),
            politrees=digest(SourceId.POLITREES),
            extras=digest(SourceId.EXTRAS),
            mvsepless=digest(SourceId.MVSEPLESS),
            identity=identity,
            adapter_schema=ADAPTER_SCHEMA,
        )

    def _publish(self, *, report: RefreshReport | None) -> CatalogueSnapshot:
        from .catalog_dedupe import dedupe_download_catalogue
        from .catalog_sources import (
            EntryMeta,
            _checkpoint_urls,
            _metadata_alias_index,
        )
        from .download_sizes import trusted_content_ids_from_cache
        from .extra_catalog import apollo_download_list
        from .mvsepless_catalog import unsupported_mvsepless_downloads
        from .politrees_catalog import merge_politrees_catalogues, merge_supplemental_list

        if self._closed and self._latest is not None:
            return self._latest
        contents = self._contents()
        identity_map = trusted_content_ids_from_cache(_identity_urls_from_contents(contents))
        identity = _identity_digest(identity_map)
        revision = self._revision(contents, identity=identity)
        cache_key = revision.digest()
        with self._lock:
            cached = self._snapshots.get(cache_key)
            # Same digest can be republished with a later RefreshReport
            # (FORCE used to cache usable=False, then SWR returned it).
            if cached is not None and (report is None or cached.report == report):
                return cached

        snapshot = self._build_snapshot(
            contents,
            revision=revision,
            identity_map=identity_map,
            report=report,
            merge_politrees_catalogues=merge_politrees_catalogues,
            merge_supplemental_list=merge_supplemental_list,
            apollo_download_list=apollo_download_list,
            unsupported_mvsepless_downloads=unsupported_mvsepless_downloads,
            EntryMeta=EntryMeta,
            _checkpoint_urls=_checkpoint_urls,
            _metadata_alias_index=_metadata_alias_index,
            dedupe_download_catalogue=dedupe_download_catalogue,
        )
        previous = self._latest
        with self._lock:
            self._snapshots[cache_key] = snapshot
            self._latest = snapshot
            self._builds += 1
        if previous is not None:
            delta = _delta_between(previous, snapshot)
            if delta is not None:
                self._notify(delta)
        return snapshot

    def _build_snapshot(
        self,
        contents: Mapping[SourceId, SourceContent | None],
        *,
        revision: RevisionVector,
        identity_map: Mapping[str, str],
        report: RefreshReport | None,
        merge_politrees_catalogues: Any,
        merge_supplemental_list: Any,
        apollo_download_list: Any,
        unsupported_mvsepless_downloads: Any,
        EntryMeta: Any,
        _checkpoint_urls: Any,
        _metadata_alias_index: Any,
        dedupe_download_catalogue: Any,
    ) -> CatalogueSnapshot:
        upstream = contents.get(SourceId.UPSTREAM)
        politrees = contents.get(SourceId.POLITREES)
        extras = contents.get(SourceId.EXTRAS)
        mvsepless = contents.get(SourceId.MVSEPLESS)

        upstream_payload = dict(upstream.payload) if upstream is not None else {}
        vr, mdx, demucs = flatten_upstream_lists(upstream_payload)
        source_owners: dict[str, dict[str, str]] = {
            "vr": {str(label): SourceId.UPSTREAM.value for label in vr},
            "mdx": {str(label): SourceId.UPSTREAM.value for label in mdx},
            "demucs": {str(label): SourceId.UPSTREAM.value for label in demucs},
            "apollo": {},
        }

        def track_source(
            family: str,
            before: Mapping[str, Any],
            after: Mapping[str, Any],
            source_id: SourceId,
        ) -> None:
            owners = source_owners[family]
            for label, model in after.items():
                if label not in before or before[label] != model:
                    owners[str(label)] = source_id.value

        if politrees is not None:
            before = (dict(vr), dict(mdx), dict(demucs))
            vr, mdx, demucs = merge_politrees_catalogues(vr, mdx, demucs, dict(politrees.payload))
            for family, old, merged in zip(
                ("vr", "mdx", "demucs"), before, (vr, mdx, demucs), strict=True
            ):
                track_source(family, old, merged, SourceId.POLITREES)
        if extras is not None:
            from .extra_catalog import merge_extra_catalogues

            before = (dict(vr), dict(mdx), dict(demucs))
            vr, mdx, demucs = merge_extra_catalogues(vr, mdx, demucs, extra=dict(extras.payload))
            for family, old, merged in zip(
                ("vr", "mdx", "demucs"), before, (vr, mdx, demucs), strict=True
            ):
                track_source(family, old, merged, SourceId.EXTRAS)
        extra_meta: dict[str, Any] = {}
        converted: dict[str, Any] | None = None
        if mvsepless is not None:
            from .mvsepless_catalog import (
                convert_mvsepless_catalog,
                merge_mvsepless_catalogues,
            )

            raw = dict(mvsepless.payload)
            if "unsupported" in raw or "mdx_download_list" in raw:
                converted = raw
            else:
                converted = convert_mvsepless_catalog(raw)
            before = (dict(vr), dict(mdx), dict(demucs))
            vr, mdx, demucs = merge_mvsepless_catalogues(
                vr, mdx, demucs, converted, allow_network=False
            )
            for family, old, merged in zip(
                ("vr", "mdx", "demucs"), before, (vr, mdx, demucs), strict=True
            ):
                track_source(family, old, merged, SourceId.MVSEPLESS)
            extra_meta = dict(converted.get("metadata") or {})

        apollo = apollo_download_list(extra=dict(extras.payload) if extras is not None else None)
        source_owners["apollo"] = {str(label): SourceId.EXTRAS.value for label in apollo}
        alias_meta = _metadata_alias_index(extra_meta)
        yaml_index = _checkpoint_yaml_index(vr, mdx, demucs, apollo)
        yaml_url_index = _checkpoint_yaml_url_index(upstream_payload)
        meta_by_family = build_meta_by_family(
            _metadata_catalogue_with_config_evidence(vr, yaml_index, yaml_url_index),
            _metadata_catalogue_with_config_evidence(mdx, yaml_index, yaml_url_index),
            _metadata_catalogue_with_config_evidence(demucs, yaml_index, yaml_url_index),
            _metadata_catalogue_with_config_evidence(apollo, yaml_index, yaml_url_index),
            extra_meta,
            alias_meta,
        )
        meta: dict[str, Any] = {}
        for family_meta in meta_by_family.values():
            meta.update(family_meta)  # transitional; identity must not use this

        from .download_sizes import trusted_content_ids_from_cache

        content_ids = trusted_content_ids_from_cache(_checkpoint_urls(vr, mdx, apollo))
        vr_out = dedupe_download_catalogue(vr, content_ids=content_ids)
        mdx_out = dedupe_download_catalogue(mdx, content_ids=content_ids)
        demucs_out = dedupe_download_catalogue(demucs, demucs_bags=True)
        apollo_out = dedupe_download_catalogue(apollo, content_ids=content_ids)

        existing = {**vr_out, **mdx_out, **demucs_out, **apollo_out}
        unsupported = unsupported_mvsepless_downloads(
            converted=converted,
            existing_labels=existing,
            allow_network=False,
        )
        self._index_builds += 1
        display_vr = _basename_index(meta_by_family["vr"], VR_ARCH_TYPE)
        display_mdx = _basename_index(meta_by_family["mdx"], MDX_ARCH_TYPE)
        display_demucs = _basename_index(meta_by_family["demucs"], DEMUCS_ARCH_TYPE)
        return CatalogueSnapshot(
            revision=revision,
            vr=_readonly_catalogue(vr_out),
            mdx=_readonly_catalogue(mdx_out),
            demucs=_readonly_catalogue(demucs_out),
            apollo=_readonly_catalogue(apollo_out),
            meta=MappingProxyType(meta),
            meta_by_family=MappingProxyType(
                {family: MappingProxyType(entries) for family, entries in meta_by_family.items()}
            ),
            pre_dedupe_vr=_readonly_catalogue(vr),
            pre_dedupe_mdx=_readonly_catalogue(mdx),
            pre_dedupe_demucs=_readonly_catalogue(demucs),
            pre_dedupe_apollo=_readonly_catalogue(apollo),
            unsupported=MappingProxyType(dict(unsupported)),
            display_index_vr=MappingProxyType(display_vr),
            display_index_mdx=MappingProxyType(display_mdx),
            display_index_demucs=MappingProxyType(display_demucs),
            checkpoint_yaml_index=MappingProxyType(yaml_index),
            entry_sources=MappingProxyType(
                {
                    family: MappingProxyType(
                        {
                            str(selection): source
                            for selection, source in source_owners[family].items()
                        }
                    )
                    for family in ("vr", "mdx", "demucs", "apollo")
                }
            ),
            report=report,
            checkpoint_yaml_url_index=MappingProxyType(yaml_url_index),
        )

    def apply_trusted_identities(self, content_ids: Mapping[str, str]) -> CatalogueDelta | None:
        """Rebuild download projections for the current sources with new ids."""
        if self._closed:
            return None
        identity = _identity_digest(content_ids)
        previous = self._latest
        if previous is not None and previous.revision.identity == identity:
            return None
        # Drop cached projections so identity revision is visible.
        with self._lock:
            self._snapshots.clear()
        snapshot = self._publish(report=previous.report if previous else None)
        if previous is None:
            return None
        delta = _delta_between(previous, snapshot)
        if delta is not None and delta.removal_only:
            delta = CatalogueDelta(
                kind=DeltaKind.IDENTITY_REFINED,
                added=delta.added,
                removed=delta.removed,
                changed=delta.changed,
            )
            self._notify(delta)
        elif delta is not None and (delta.added or delta.changed):
            delta = CatalogueDelta(
                kind=DeltaKind.SOURCES_CHANGED,
                added=delta.added,
                removed=delta.removed,
                changed=delta.changed,
            )
            self._notify(delta)
        return delta

    def notify_metadata(self, labels: Mapping[str, tuple[str, ...]] | None = None) -> None:
        """Publish a metadata-only delta without remeshing sources."""
        if self._closed:
            return
        delta = CatalogueDelta(
            kind=DeltaKind.METADATA_CHANGED,
            changed=dict(labels or {}),
        )
        self._notify(delta)

    def _notify(self, delta: CatalogueDelta) -> None:
        if self._closed:
            return
        with self._lock:
            typed = list(self._delta_subscribers)
            identity = list(self._identity_subscribers)
        for callback in typed:
            try:
                callback(delta)
            except Exception as exc:
                log_event(
                    "download",
                    "catalogue_subscriber_failed",
                    level="warning",
                    subscriber_kind="delta",
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
        if delta.removal_only:
            for callback in identity:
                try:
                    callback()
                except Exception as exc:
                    log_event(
                        "download",
                        "catalogue_subscriber_failed",
                        level="warning",
                        subscriber_kind="identity",
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )


def _basename_index(meta: Mapping[str, Any], arch: str) -> dict[str, str]:
    import os

    from .model_display import _is_checkpoint_name

    index: dict[str, str] = {}
    for entry in meta.values():
        if getattr(entry, "arch", None) != arch:
            continue
        display = str(getattr(entry, "display", "") or "")
        files = getattr(entry, "files", {}) or {}
        if arch == DEMUCS_ARCH_TYPE:
            yaml_names = [name for name in files if str(name).lower().endswith((".yaml", ".yml"))]
            if yaml_names:
                for yaml_name in yaml_names:
                    stem = os.path.splitext(os.path.basename(str(yaml_name)))[0]
                    index.setdefault(stem, display)
                continue
            names = [name for name in files if _is_checkpoint_name(str(name))]
        else:
            checkpoint = getattr(entry, "checkpoint", None)
            names = (
                [checkpoint]
                if checkpoint
                else [name for name in files if _is_checkpoint_name(str(name))]
            )
        for filename in names:
            if not filename:
                continue
            stem = os.path.splitext(os.path.basename(str(filename)))[0]
            index.setdefault(stem, display)
    return index


def _checkpoint_yaml_index(*catalogues: Mapping[str, Any]) -> dict[str, str]:
    import os

    from .model_display import _is_checkpoint_name

    index: dict[str, str] = {}
    for catalogue in catalogues:
        for model in catalogue.values():
            if not isinstance(model, dict):
                continue
            checkpoint = None
            yaml_name = None
            for name, ref in model.items():
                text = str(name)
                if _is_checkpoint_name(text):
                    checkpoint = os.path.basename(text)
                    compact_yaml = yaml_basename_from_ref(ref)
                    if compact_yaml:
                        index.setdefault(checkpoint, compact_yaml)
                elif text.casefold().endswith((".yaml", ".yml")):
                    yaml_name = os.path.basename(text)
            if checkpoint and yaml_name:
                index.setdefault(checkpoint, yaml_name)
    return index


def _checkpoint_yaml_url_index(
    upstream_payload: Mapping[str, Any],
) -> dict[tuple[str, str], str]:
    """Index YAML URLs from the non-selectable upstream evidence list."""
    import os

    from .model_display import _is_checkpoint_name

    evidence = upstream_payload.get("other_network_list")
    if not isinstance(evidence, dict):
        return {}
    index: dict[tuple[str, str], str] = {}
    for model in evidence.values():
        if not isinstance(model, dict):
            continue
        checkpoints: list[str] = []
        yaml_urls: list[tuple[str, str]] = []
        for name, ref in model.items():
            basename = os.path.basename(str(name))
            if (
                _is_checkpoint_name(basename)
                and isinstance(ref, str)
                and ref.startswith(("http://", "https://"))
            ):
                checkpoints.append(basename)
            elif (
                basename.casefold().endswith((".yaml", ".yml"))
                and isinstance(ref, str)
                and ref.startswith(("http://", "https://"))
            ):
                yaml_urls.append((basename, ref))
        if len(checkpoints) != 1 or len(yaml_urls) != 1:
            continue
        yaml_name, yaml_url = yaml_urls[0]
        index.setdefault((checkpoints[0], yaml_name), yaml_url)
    return index


def _metadata_catalogue_with_config_evidence(
    catalogue: Mapping[str, Any],
    checkpoint_yaml_index: Mapping[str, str],
    checkpoint_yaml_url_index: Mapping[tuple[str, str], str],
) -> dict[str, Any]:
    """Add exact compact config associations to metadata-only entry copies."""
    import os

    from .model_display import _is_checkpoint_name

    enriched: dict[str, Any] = {}
    for label, model in catalogue.items():
        if not isinstance(model, dict):
            enriched[str(label)] = model
            continue
        files = dict(model)
        for name, ref in model.items():
            checkpoint = os.path.basename(str(name))
            if not _is_checkpoint_name(checkpoint):
                continue
            compact_yaml = yaml_basename_from_ref(ref)
            if compact_yaml is None or checkpoint_yaml_index.get(checkpoint) != compact_yaml:
                continue
            config_ref = checkpoint_yaml_url_index.get((checkpoint, compact_yaml), compact_yaml)
            files.setdefault(compact_yaml, config_ref)
        enriched[str(label)] = files
    return enriched


def _delta_between(
    previous: CatalogueSnapshot, current: CatalogueSnapshot
) -> CatalogueDelta | None:
    added: dict[str, tuple[str, ...]] = {}
    removed: dict[str, tuple[str, ...]] = {}
    changed: dict[str, tuple[str, ...]] = {}
    for arch, old_map, new_map in (
        ("vr", previous.vr, current.vr),
        ("mdx", previous.mdx, current.mdx),
        ("demucs", previous.demucs, current.demucs),
        ("apollo", previous.apollo, current.apollo),
    ):
        old_keys = set(old_map)
        new_keys = set(new_map)
        add = tuple(sorted(new_keys - old_keys))
        drop = tuple(sorted(old_keys - new_keys))
        chg = tuple(
            sorted(label for label in old_keys & new_keys if old_map[label] != new_map[label])
        )
        if add:
            added[arch] = add
        if drop:
            removed[arch] = drop
        if chg:
            changed[arch] = chg
    if not added and not removed and not changed:
        return None
    kind = DeltaKind.IDENTITY_REFINED if not added and not changed else DeltaKind.SOURCES_CHANGED
    return CatalogueDelta(kind=kind, added=added, removed=removed, changed=changed)


def _identity_digest(content_ids: Mapping[str, str]) -> str:
    hasher = hashlib.sha256()
    for key in sorted(content_ids):
        hasher.update(f"{key}={content_ids[key]}\n".encode("utf-8"))
    return hasher.hexdigest() if content_ids else ""


def _identity_urls_from_contents(
    contents: Mapping[SourceId, SourceContent | None],
) -> tuple[str, ...]:
    from .catalog_dedupe import primary_checkpoint_url

    urls: list[str] = []
    for content in contents.values():
        if content is None:
            continue
        for key, catalogue in content.payload.items():
            if str(key).startswith("_") or not isinstance(catalogue, dict):
                continue
            for model in catalogue.values():
                url = primary_checkpoint_url(model)
                if url:
                    urls.append(url)
    return tuple(urls)


def _default_sources() -> dict[SourceId, RemoteJsonSource]:
    from bundled.constants import MVSEPLESS_MODELS_JSON_URL, POLITREES_MODEL_LINKS_URL

    from . import extra_catalog, mvsepless_catalog, paths, politrees_catalog

    def politrees_open(target: str | Any) -> Any:
        return politrees_catalog._urlopen(target)

    def mvsepless_open(target: str | Any) -> Any:
        return mvsepless_catalog._urlopen(target)

    def downloads_open(target: str | Any) -> Any:
        from . import downloads

        return downloads._urlopen(target)  # type: ignore[arg-type]

    def bundled_upstream() -> Mapping[str, Any] | None:
        from .downloads import DownloadManager

        payload = DownloadManager._load_cache()
        return payload or None

    def extras_loader() -> Mapping[str, Any] | None:
        data = extra_catalog.load_extra_models()
        return data or None

    return {
        SourceId.UPSTREAM: RemoteJsonSource(
            source_id=SourceId.UPSTREAM,
            url=DOWNLOAD_CHECKS,
            cache_filename="upstream_download_checks.json",
            cache_path=paths.UPSTREAM_CATALOGUE_CACHE_FILE,
            opener=downloads_open,
            bundled_fallback=bundled_upstream,
        ),
        SourceId.POLITREES: RemoteJsonSource(
            source_id=SourceId.POLITREES,
            url=POLITREES_MODEL_LINKS_URL,
            cache_filename="politrees_model_links.json",
            cache_path=paths.POLITREES_CACHE_FILE,
            opener=politrees_open,
            enabled=politrees_catalog.politrees_enabled,
        ),
        SourceId.EXTRAS: RemoteJsonSource(
            source_id=SourceId.EXTRAS,
            local_loader=extras_loader,
            enabled=extra_catalog.extra_catalog_enabled,
        ),
        SourceId.MVSEPLESS: RemoteJsonSource(
            source_id=SourceId.MVSEPLESS,
            url=MVSEPLESS_MODELS_JSON_URL,
            cache_filename="mvsepless_models.json",
            cache_path=paths.MVSEPLESS_CACHE_FILE,
            opener=mvsepless_open,
            enabled=mvsepless_catalog.mvsepless_enabled,
        ),
    }


__all__ = [
    "CatalogueCoordinator",
    "CatalogueSnapshot",
    "SourceId",
    "build_meta_by_family",
    "flatten_upstream_lists",
    "yaml_basename_from_ref",
]
