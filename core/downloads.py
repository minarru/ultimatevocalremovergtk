"""Tk-free backend for the Download Center, model-data refresh and updates.

This is the framework-agnostic port of ``UVR.py``'s "Download Center Methods"
(``online_data_refresh`` / ``download_list_fill`` / ``download_model_select`` /
``download_item`` / ``download_model_settings``). It reuses the upstream
model-list JSON schema and routes public artifacts from both model repositories
into the same model directories.

Everything here is import-safe without ``torch`` and uses only the standard
library. Network and disk work happens on caller-supplied worker threads; this module
never touches any UI toolkit and reports progress through plain callbacks.
"""

import dataclasses
import errno
import json
import os
import ssl
import tempfile
import threading
import time
import typing
import urllib.request
import warnings
from contextlib import ExitStack
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from bundled.constants import (
    ADDITIONAL_MODEL_REPO,
    ALL_TYPES,
    APOLLO_ARCH_TYPE,
    BULLETIN_CHECK,
    DEMUCS_ARCH_TYPE,
    DEMUCS_MODEL_NAME_DATA_LINK,
    DEMUCS_NEWER_ARCH_TYPES,
    INFO_UNAVAILABLE_TEXT,
    LEGACY_ADDITIONAL_REPO_SELECTION,
    MDX_ARCH_TYPE,
    MDX_MODEL_DATA_LINK,
    MDX_MODEL_NAME_DATA_LINK,
    NO_MODEL,
    NO_NEW_MODELS,
    NORMAL_REPO,
    OPERATING_SYSTEM,
    VR_ARCH_TYPE,
    VR_MODEL_DATA_LINK,
)

from . import paths
from .catalog_dedupe import normalize_catalogue_label
from .debug_log import debug, log_event
from .download_sizes import (
    content_ids_from_cache,
    describe_download_size,
    estimate_jobs_size,
    format_download_size,
    prefetch_remote_sizes,
    prefetch_same_size_identity,
)
from .json_store import locked_json_path
from .mdx_config_fetch import ensure_mdx_c_config
from .model_identity import FAMILY_BY_ARCH
from .mvsepless_catalog import (
    unsupported_mvsepless_downloads,
    unsupported_reason_for_label,
)
from .politrees_catalog import (
    apollo_checkpoint_filename,
    hf_fallback_url,
    manual_links_for_model,
    mdx_checkpoint_filename,
    resolve_apollo_jobs,
    resolve_demucs_jobs,
    resolve_mdx_jobs,
    resolve_vr_jobs,
)
from .version_info import release_update_status

DOWNLOAD_MODEL_CACHE = paths.DOWNLOAD_MODEL_CACHE_PATH
# Minimum interval between byte-count status strings shown in the queue UI.
_INFO_UPDATE_INTERVAL_S = 0.25


@dataclasses.dataclass(frozen=True)
class CatalogueEvidenceSummary:
    """Aggregate semantic-review and exact-evidence availability counts."""

    reviewed: int = 0
    raw: int = 0
    waived: int = 0
    pending: int = 0
    unavailable: int = 0
    stale: int = 0


# Mapper JSON download links paired with their on-disk destinations (the exact
# four files ``download_model_settings`` refreshes).
_MODEL_DATA_URLS = [
    (VR_MODEL_DATA_LINK, paths.VR_HASH_JSON),
    (MDX_MODEL_DATA_LINK, paths.MDX_HASH_JSON),
    (MDX_MODEL_NAME_DATA_LINK, paths.MDX_MODEL_NAME_SELECT),
    (DEMUCS_MODEL_NAME_DATA_LINK, paths.DEMUCS_MODEL_NAME_SELECT),
]

#: Name mappers merge remote over local so fork/local-only keys survive refresh.
_NAME_MAPPER_DESTS = frozenset(
    {
        paths.MDX_MODEL_NAME_SELECT,
        paths.DEMUCS_MODEL_NAME_SELECT,
    }
)


@dataclasses.dataclass(frozen=True)
class ManualDownloadRow:
    """One projected Manual Downloads row with its raw selection intact."""

    arch_type: str
    selection: str
    display: str
    model: Any

    def resolve_links(self) -> List[Tuple[str, str]]:
        return DownloadManager.manual_links(
            self.arch_type,
            self.model,
            selection=self.selection,
        )


def _attempt_presentation_backfill(
    repo: Any | None,
    snapshot: Any | None,
    *,
    operation: str,
) -> None:
    if repo is None:
        return
    if snapshot is not None and not all(
        isinstance(getattr(snapshot, family, None), Mapping)
        for family in ("vr", "mdx", "demucs", "apollo")
    ):
        return
    try:
        from .model_inventory import backfill_installed_presentations

        backfill_installed_presentations(repo, snapshot)
    except (OSError, ValueError) as exc:
        message = (
            f"model presentation backfill failed after successful {operation}; "
            "the live catalogue remains active and the next successful refresh "
            f"will retry: {type(exc).__name__}: {exc}"
        )
        from .debug_log import log_event

        log_event(
            "download",
            "presentation_backfill_failed",
            level="warning",
            operation=operation,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        warnings.warn(message, RuntimeWarning, stacklevel=2)


def _latest_version_key() -> str:
    if OPERATING_SYSTEM == "Darwin":
        return "current_version_mac"
    if OPERATING_SYSTEM == "Linux":
        return "current_version_linux"
    return "current_version"


_DOWNLOAD_TIMEOUT_SECONDS = 30


def _ssl_context() -> ssl.SSLContext:
    """Return a TLS context; set ``UVR_INSECURE_DOWNLOADS=1`` to disable verification."""
    if os.environ.get("UVR_INSECURE_DOWNLOADS") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _urlopen(url: str | urllib.request.Request):
    return urllib.request.urlopen(url, context=_ssl_context(), timeout=_DOWNLOAD_TIMEOUT_SECONDS)


def _json_file_matches(path: str, payload: Mapping[str, Any]) -> bool:
    """True when ``path`` already holds an equivalent JSON object."""
    if not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, ValueError, TypeError):
        return False
    return existing == payload


def _transactional_json_refresh(
    writes: Mapping[str, Mapping[str, Any]],
    *,
    locked_paths: typing.Iterable[str] = (),
    prepare_locked: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None,
) -> tuple[bool, bool]:
    """Stage and commit a set of JSON files, rolling back on commit failure."""
    transaction_paths = set(writes)
    transaction_paths.update(locked_paths)
    with ExitStack() as locks:
        for path in sorted(transaction_paths, key=os.path.abspath):
            locks.enter_context(locked_json_path(path))
        prepared = prepare_locked() if prepare_locked is not None else {}
        if not set(prepared).issubset(transaction_paths):
            raise ValueError("prepared JSON write does not hold its destination lock")
        return _transactional_json_refresh_locked({**writes, **prepared})


def _transactional_json_refresh_locked(
    writes: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, bool]:
    staged: Dict[str, str] = {}
    backups: Dict[str, Optional[str]] = {}
    committed: List[str] = []
    try:
        for path, payload in writes.items():
            if _json_file_matches(path, payload):
                continue
            text = json.dumps(payload, indent=4)
            directory = os.path.dirname(path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            staged[path] = tmp_path

        if not staged:
            return True, False

        # Keep rollback copies in the same directories so restoration remains
        # an atomic rename even when model-data files live in different roots.
        for path in staged:
            if not os.path.isfile(path):
                backups[path] = None
                continue
            directory = os.path.dirname(path) or "."
            fd, backup_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(path)}.", suffix=".bak", dir=directory
            )
            try:
                with open(path, "rb") as source, os.fdopen(fd, "wb") as backup:
                    backup.write(source.read())
            except Exception:
                try:
                    os.unlink(backup_path)
                except OSError:
                    pass
                raise
            backups[path] = backup_path

        for path, tmp_path in staged.items():
            os.replace(tmp_path, path)
            committed.append(path)
    except Exception as exc:
        from .debug_log import log_event

        log_event(
            "download",
            "model_data_commit_failed",
            level="error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        for path in reversed(committed):
            backup_path = backups.get(path)
            try:
                if backup_path is None:
                    if os.path.isfile(path):
                        os.unlink(path)
                else:
                    os.replace(backup_path, path)
            except OSError:
                pass
        return False, False
    finally:
        for tmp_path in list(staged.values()) + list(backups.values()):
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
    return True, True


class DownloadManager:
    """Holds the online model catalogue and performs downloads / update checks.

    A single instance is shared by the Download Center and the update view. All
    network calls are synchronous and meant to be driven from a worker thread;
    callers marshal the supplied callbacks onto the GTK main loop.
    """

    def __init__(self, coordinator: Any = None, *, repo: Any = None):
        self.online_data: Dict = {}
        self.bulletin_data: str = INFO_UNAVAILABLE_TEXT
        self.is_online: bool = False
        self.latest_version: str = ""

        # Public, on-disk-aware catalogues (populated by ``refresh``).
        self.vr_download_list: Dict[str, Any] = {}
        self.mdx_download_list: Dict[str, Any] = {}
        self.demucs_download_list: Dict[str, Any] = {}
        # Apollo restoration models are fork-curated only (no upstream list).
        self.apollo_download_list: Dict[str, Any] = {}
        # mvsepless entries we index but cannot run yet: {arch: [(label, reason), ...]}.
        self.unsupported_download_list: Dict[str, List[Tuple[str, str]]] = {}
        # {label: EntryMeta} from the last merge. Annotated loosely so
        # ``catalog_sources`` stays out of this module's import time.
        self.catalogue_meta: Dict[str, Any] = {}
        # Family-keyed metadata is the authoritative association for exact
        # identity/display projection. The flat map remains presentation-only
        # compatibility state for older consumers.
        self.catalogue_meta_by_family: Dict[str, Dict[str, Any]] = {}
        self._size_warmup_lock = threading.Lock()
        self._size_warmup_done_for: Optional[frozenset[str]] = None
        self._catalogue_changed_subscribers: List[Callable[[], None]] = []
        self._catalogue_changed_lock = threading.Lock()
        self._catalogue_evidence_lock = threading.Lock()
        self._catalogue_evidence_pending: set[str] = set()
        self._catalogue_evidence_force_pending: set[str] = set()
        self._catalogue_evidence_callbacks: list[Callable[[CatalogueEvidenceSummary], None]] = []
        self._catalogue_evidence_url_entries: Dict[str, list[tuple[str, str]]] = {}
        self._catalogue_evidence_subscribed = False
        self._coordinator = None
        self._repo = repo
        self._last_refresh_report: Any = None
        if coordinator is not None:
            self._bind_coordinator(coordinator)

    def _bind_coordinator(self, coordinator: Any) -> None:
        self._coordinator = coordinator
        coordinator.subscribe_identity_removal(self._notify_catalogue_changed)
        coordinator.subscribe_delta(self._on_source_delta)

    def _on_source_delta(self, delta: Any) -> None:
        from .catalogue_types import DeltaKind

        if getattr(delta, "kind", None) is not DeltaKind.SOURCES_CHANGED:
            return
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is None:
            return
        snapshot = getattr(coordinator, "_latest", None)
        if snapshot is not None:
            self._apply_snapshot(snapshot)

    # -- Catalogue change notification ------------------------------------------

    def subscribe_catalogue_changed(self, callback: Callable[[], None]) -> None:
        """Call ``callback`` when the in-memory catalogue lists lose entries.

        Fired from the size-warmup thread, so listeners must marshal to their
        own loop. Mirrors ``catalogue_stem_cache.subscribe`` deliberately —
        one notification shape for both background catalogue refinements.
        """
        with self._catalogue_changed_lock:
            if callback not in self._catalogue_changed_subscribers:
                self._catalogue_changed_subscribers.append(callback)

    def subscribe_delta(self, callback: Callable[[Any], None]) -> None:
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is not None:
            coordinator.subscribe_delta(callback)

    def unsubscribe_delta(self, callback: Callable[[Any], None]) -> None:
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is not None:
            coordinator.unsubscribe_delta(callback)

    def unsubscribe_catalogue_changed(self, callback: Callable[[], None]) -> None:
        with self._catalogue_changed_lock:
            try:
                self._catalogue_changed_subscribers.remove(callback)
            except ValueError:
                pass

    def _notify_catalogue_changed(self) -> None:
        with self._catalogue_changed_lock:
            callbacks = list(self._catalogue_changed_subscribers)
        for callback in callbacks:
            try:
                callback()
            except Exception:
                # A listener raising here would kill the warmup thread mid-wave
                # and strand the rest of the identity pass.
                debug("download", "catalogue_changed subscriber raised")

    # -- Catalogue + size cache -------------------------------------------------

    def _has_any_catalogue(self) -> bool:
        return bool(
            self.vr_download_list
            or self.mdx_download_list
            or self.demucs_download_list
            or self.apollo_download_list
        )

    def _ensure_coordinator(self) -> Any:
        coordinator = getattr(self, "_coordinator", None)
        if coordinator is None:
            from .catalogue_coordinator import CatalogueCoordinator

            self._bind_coordinator(CatalogueCoordinator())
            coordinator = self._coordinator
        return coordinator

    def _apply_snapshot(self, snapshot: Any) -> None:
        self.vr_download_list = dict(snapshot.vr)
        self.mdx_download_list = dict(snapshot.mdx)
        self.demucs_download_list = dict(snapshot.demucs)
        self.apollo_download_list = dict(snapshot.apollo)
        self.catalogue_meta = dict(snapshot.meta)
        self.catalogue_meta_by_family = {
            str(family): dict(entries)
            for family, entries in getattr(snapshot, "meta_by_family", {}).items()
        }
        self.unsupported_download_list = dict(snapshot.unsupported)
        from .catalogue_types import SourceId

        coordinator = getattr(self, "_coordinator", None)
        if coordinator is None:
            return
        content = coordinator.source(SourceId.UPSTREAM).state.content
        if content is not None:
            self.online_data = dict(content.payload)

    def ensure_catalogues(self, *, allow_network: bool = True) -> bool:
        """Populate download catalogues from in-memory, bundled, or Politrees data."""
        if self._has_any_catalogue():
            return True
        from .access_policy import AccessPolicy, current_access_policy

        policy = current_access_policy()
        if not allow_network:
            policy = AccessPolicy(
                allow_network=False,
                allow_metadata_writes=policy.allow_metadata_writes,
                allow_cache_writes=policy.allow_cache_writes,
            )
        coordinator = self._ensure_coordinator()
        snapshot = coordinator.ensure(allow_network=policy.allow_network, policy=policy)
        self._apply_snapshot(snapshot)
        if self._has_any_catalogue():
            return True
        # Compatibility fallback when the coordinator has nothing usable.
        self.online_data = self._load_cache()
        if self.online_data:
            self._rebuild_catalogues()
            self._merge_politrees_supplement(allow_network=allow_network)
        else:
            self._merge_politrees_supplement(allow_network=allow_network)
        return self._has_any_catalogue()

    def catalogue_urls(self) -> List[str]:
        """Unique remote URLs for every catalogue entry."""
        urls: set[str] = set()
        for arch_type, catalogue in (
            (VR_ARCH_TYPE, self.vr_download_list),
            (MDX_ARCH_TYPE, self.mdx_download_list),
            (DEMUCS_ARCH_TYPE, self.demucs_download_list),
            (APOLLO_ARCH_TYPE, self.apollo_download_list),
        ):
            for name in catalogue:
                for url, _path in self.resolve(name, arch_type):
                    urls.add(url)
        return sorted(urls)

    def catalogue_checkpoint_urls(self) -> List[str]:
        """Checkpoint URLs only (skip config YAML) for size/identity warmup."""
        urls: set[str] = set()
        for arch_type, catalogue in (
            (VR_ARCH_TYPE, self.vr_download_list),
            (MDX_ARCH_TYPE, self.mdx_download_list),
            (DEMUCS_ARCH_TYPE, self.demucs_download_list),
            (APOLLO_ARCH_TYPE, self.apollo_download_list),
        ):
            for name in catalogue:
                for url, path in self.resolve(name, arch_type):
                    lower = path.casefold()
                    if lower.endswith((".yaml", ".yml")):
                        continue
                    urls.add(url)
        return sorted(urls)

    def _reapply_content_dedupe(self) -> None:
        """Re-run etag dedupe on in-memory lists after identity HEADs fill."""
        from .catalog_dedupe import dedupe_download_catalogue, primary_checkpoint_url

        urls: List[str] = []
        for catalogue in (
            self.vr_download_list,
            self.mdx_download_list,
            self.apollo_download_list,
        ):
            for model in catalogue.values():
                url = primary_checkpoint_url(model)
                if url:
                    urls.append(url)
        content_ids = content_ids_from_cache(urls)
        if not content_ids:
            return
        before = (
            len(self.vr_download_list)
            + len(self.mdx_download_list)
            + len(self.apollo_download_list)
        )
        self.vr_download_list = dedupe_download_catalogue(
            self.vr_download_list, content_ids=content_ids
        )
        self.mdx_download_list = dedupe_download_catalogue(
            self.mdx_download_list, content_ids=content_ids
        )
        self.apollo_download_list = dedupe_download_catalogue(
            self.apollo_download_list, content_ids=content_ids
        )
        after = (
            len(self.vr_download_list)
            + len(self.mdx_download_list)
            + len(self.apollo_download_list)
        )
        dropped = before - after
        if dropped:
            debug("download", f"content dedupe dropped {dropped} download row(s)")
            # The merged catalogue is memoized on the display generation, and
            # its key covers the caller's label set but not the content-id map
            # dedupe runs on. On a fresh install the merge is built before any
            # etag exists, so when the identity pass fills them the inputs are
            # unchanged and the pre-dedupe row set would be served all session.
            # Bump the generation rather than widening the key -- one
            # invalidation story, not two.
            from .model_display import clear_display_cache

            clear_display_cache()
            self._notify_catalogue_changed()

    def warm_size_cache(self) -> Dict[str, int]:
        """Prefetch remote sizes for catalogue checkpoint URLs (7-day TTL)."""
        if not self.ensure_catalogues():
            debug("download", "size_cache_warmup skip no catalogues")
            return {"total": 0, "fresh": 0, "fetched": 0, "failed": 0}

        urls = self.catalogue_checkpoint_urls()
        signature = frozenset(urls)
        if self._size_warmup_done_for == signature:
            debug("download", "size_cache_warmup skip already warm")
            return {"total": len(urls), "fresh": len(urls), "fetched": 0, "failed": 0}

        if not self._size_warmup_lock.acquire(blocking=False):
            debug("download", "size_cache_warmup skip already running")
            return {"total": 0, "fresh": 0, "fetched": 0, "failed": 0}

        from .debug_log import debug_elapsed

        try:
            debug("download", f"size_cache_warmup start urls={len(urls)}")
            started = time.perf_counter()
            stats = prefetch_remote_sizes(urls)
            identity = prefetch_same_size_identity(urls)
            coordinator = getattr(self, "_coordinator", None)
            if coordinator is not None:
                from .download_sizes import trusted_content_ids_from_cache

                coordinator.apply_trusted_identities(trusted_content_ids_from_cache(urls))
                from .access_policy import current_access_policy
                from .catalogue_types import RefreshMode

                snapshot = coordinator.snapshot(
                    mode=RefreshMode.OFFLINE,
                    policy=current_access_policy(),
                )
                self._apply_snapshot(snapshot)
            else:
                self._reapply_content_dedupe()
            # Only mark the URL set warm once the identity pass has nothing
            # left; it HEADs at most _IDENTITY_HEAD_CAP per call, and latching
            # here would strand the remainder for the rest of the session.
            # Re-running is cheap — the size pass skips every fresh entry.
            if identity.get("capped"):
                self._size_warmup_done_for = None
            else:
                self._size_warmup_done_for = signature
            debug_elapsed(
                "download",
                "size_cache_warmup done "
                f"total={stats['total']} fresh={stats['fresh']} "
                f"fetched={stats['fetched']} failed={stats['failed']} "
                f"identity_fetched={identity.get('fetched', 0)}",
                started,
            )
            return stats
        finally:
            self._size_warmup_lock.release()

    def schedule_size_cache_warmup(self) -> None:
        """Kick off a background size-cache refresh (idempotent per URL set)."""
        threading.Thread(target=self.warm_size_cache, daemon=True).start()

    @property
    def last_refresh_report(self) -> Any:
        """Most recent catalogue refresh report for user-facing diagnostics."""
        return self._last_refresh_report

    # -- Online refresh ---------------------------------------------------------

    def refresh(self) -> bool:
        """Fetch the catalogue + bulletin. Returns ``True`` when live upstream succeeded.

        Partial remote failures keep the last good snapshot. Bulletin/release
        stay outside catalogue projections.
        """
        from .access_policy import current_access_policy
        from .catalogue_types import RefreshMode

        debug("download", "refresh start")
        policy = current_access_policy()
        coordinator = self._ensure_coordinator()
        report = coordinator.refresh(mode=RefreshMode.FORCE, policy=policy)
        self._last_refresh_report = report
        snapshot = coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        self._apply_snapshot(snapshot)
        if report.upstream_live:
            _attempt_presentation_backfill(
                self._repo, snapshot, operation="online catalogue refresh"
            )
        self.is_online = bool(report.upstream_live)
        try:
            with _urlopen(BULLETIN_CHECK) as response:
                bulletin = response.read().decode("utf-8")
            self.bulletin_data = bulletin.replace("~", "\u2022")
        except Exception:
            self.bulletin_data = INFO_UNAVAILABLE_TEXT

        self.latest_version = self.online_data.get(_latest_version_key(), "")
        debug(
            "download",
            "refresh "
            f"online={self.is_online} "
            f"vr={len(self.vr_download_list)} "
            f"mdx={len(self.mdx_download_list)} "
            f"demucs={len(self.demucs_download_list)} "
            f"latest={self.latest_version!r}",
        )
        if report.usable:
            self.schedule_size_cache_warmup()
        return bool(report.upstream_live)

    def _rebuild_catalogues(self) -> None:
        """Build public catalogues from ``online_data`` (no disk filter)."""
        from .catalogue_coordinator import flatten_upstream_lists

        vr, mdx, demucs = flatten_upstream_lists(self.online_data)
        self.vr_download_list = vr
        self.mdx_download_list = mdx
        self.demucs_download_list = demucs

    def _merge_politrees_supplement(self, *, allow_network: bool = True) -> None:
        """Merge every supplemental catalogue source over the upstream lists.

        The merge itself lives in :mod:`core.catalog_sources` so the runtime
        display index reads exactly the same result. Keeping a second copy here
        is what let the two drift, leaving mvsepless/extras models rendering as
        raw basenames in the method pickers.
        """
        from .catalog_sources import merged_catalogues

        merged = merged_catalogues(
            vr=self.vr_download_list,
            mdx=self.mdx_download_list,
            demucs=self.demucs_download_list,
            allow_network=allow_network,
        )
        self.vr_download_list = merged.vr
        self.mdx_download_list = merged.mdx
        self.demucs_download_list = merged.demucs
        self.apollo_download_list = merged.apollo
        self.catalogue_meta = merged.meta
        self.catalogue_meta_by_family = merged.meta_by_family
        existing_labels = {
            **self.vr_download_list,
            **self.mdx_download_list,
            **self.demucs_download_list,
            **self.apollo_download_list,
        }
        self.unsupported_download_list = unsupported_mvsepless_downloads(
            existing_labels=existing_labels,
            allow_network=allow_network,
        )

    def apply_catalogue_stem_cache(
        self,
        urls: typing.Iterable[str] | None = None,
    ) -> set[str]:
        """Patch family-scoped metadata from completed exact config evidence."""
        from .catalog_sources import (
            _needs_catalogue_config_evidence,
            _yaml_config_url,
            reconcile_catalogue_evidence,
        )
        from .catalogue_stem_cache import lookup_stems

        allowed_urls = set(urls or ())
        scoped = self._family_catalogue_meta()
        targets = [
            (family, label, meta)
            for family, metadata in scoped.items()
            for label, meta in list(metadata.items())
        ]
        if not targets:
            targets = [
                (FAMILY_BY_ARCH.get(meta.arch, ""), label, meta)
                for label, meta in list(self.catalogue_meta.items())
            ]
        updated: set[str] = set()
        updated_by_family: Dict[str, list[str]] = {}
        for family, label, meta in targets:
            url = _yaml_config_url(meta.files)
            if not url:
                continue
            if url not in allowed_urls and not _needs_catalogue_config_evidence(meta):
                continue
            hit = lookup_stems(url)
            if hit is None:
                continue
            # Legacy successes without a digest are not exact byte evidence.
            if hit.usable and not hit.content_sha256:
                continue
            reconciled = reconcile_catalogue_evidence(
                meta,
                live_stems=list(hit.stems),
                live_target_instrument=hit.target_instrument,
                live_config_sha256=hit.content_sha256,
                live_usable=hit.usable,
                live_stale=hit.stale,
                live_failed=hit.last_error is not None and not hit.usable,
                live_warning=hit.warning,
            )
            if reconciled != meta:
                flat = getattr(self, "catalogue_meta", {})
                if flat.get(label) is meta or label not in flat:
                    flat[label] = reconciled
                family_meta = scoped.get(family)
                if family_meta is not None and label in family_meta:
                    family_meta[label] = reconciled
                updated.add(label)
                updated_by_family.setdefault(family, []).append(label)
        if updated:
            coordinator = getattr(self, "_coordinator", None)
            notify = getattr(coordinator, "notify_metadata", None)
            if callable(notify):
                notify(
                    {family: tuple(sorted(labels)) for family, labels in updated_by_family.items()}
                )
        return updated

    def _ensure_catalogue_evidence_listener(self) -> None:
        """Subscribe once to incremental config-validation cache changes."""
        if getattr(self, "_catalogue_evidence_subscribed", False):
            return
        from .catalogue_stem_cache import subscribe

        subscribe(self._on_catalogue_evidence_cache_update)
        self._catalogue_evidence_subscribed = True

    def _on_catalogue_evidence_cache_update(self) -> None:
        """Apply completed config evidence while leaving queued work pending."""
        from .catalogue_stem_cache import pending_urls

        lock = getattr(self, "_catalogue_evidence_lock", None)
        if lock is None:
            return
        with lock:
            tracked = set(self._catalogue_evidence_pending)
        self.apply_catalogue_stem_cache(tracked)
        active = pending_urls()
        callbacks: list[Callable[[CatalogueEvidenceSummary], None]] = []
        completed_force: set[str] = set()
        with lock:
            self._catalogue_evidence_pending.intersection_update(active)
            before_force = set(self._catalogue_evidence_force_pending)
            self._catalogue_evidence_force_pending.intersection_update(active)
            if before_force and not self._catalogue_evidence_force_pending:
                completed_force = before_force
                callbacks = list(self._catalogue_evidence_callbacks)
                self._catalogue_evidence_callbacks.clear()
        if not completed_force:
            return
        summary = self.catalogue_evidence_summary()
        self._log_catalogue_evidence_failures(completed_force)
        log_event(
            "download",
            "catalogue_evidence_batch_completed",
            level="debug",
            **dataclasses.asdict(summary),
        )
        for callback in callbacks:
            try:
                callback(summary)
            except Exception as exc:
                log_event(
                    "download",
                    "catalogue_evidence_subscriber_failed",
                    level="warning",
                    subscriber_type=type(callback).__name__,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )

    def _family_catalogue_meta(self) -> Dict[str, Dict[str, Any]]:
        """Return the authoritative family-scoped catalogue metadata."""
        scoped = getattr(self, "catalogue_meta_by_family", None)
        return scoped if isinstance(scoped, dict) else {}

    def _public_family_catalogue_meta(self) -> Dict[str, Dict[str, Any]]:
        """Resolve post-deduplication public rows through exact family metadata."""
        scoped = self._family_catalogue_meta()
        catalogues = {
            "vr": getattr(self, "vr_download_list", {}),
            "mdx": getattr(self, "mdx_download_list", {}),
            "demucs": getattr(self, "demucs_download_list", {}),
            "apollo": getattr(self, "apollo_download_list", {}),
        }
        return {
            family: {
                str(label): metadata[str(label)] for label in catalogue if str(label) in metadata
            }
            for family, catalogue in catalogues.items()
            if isinstance(catalogue, dict)
            for metadata in (scoped.get(family, {}),)
        }

    def catalogue_evidence_summary(self) -> CatalogueEvidenceSummary:
        """Count semantic review and evidence availability without flattening IDs."""
        semantic = {"reviewed": 0, "raw": 0, "waived": 0}
        evidence = {"pending": 0, "unavailable": 0, "stale": 0}
        for metadata in self._public_family_catalogue_meta().values():
            for meta in metadata.values():
                projection = getattr(meta, "stem_semantics", None)
                review = str(getattr(projection, "status", "raw") or "raw")
                if review in semantic:
                    semantic[review] += 1
                state = getattr(meta, "catalogue_evidence_status", "unavailable")
                state_value = str(getattr(state, "value", state) or "")
                if state_value in evidence:
                    evidence[state_value] += 1
        return CatalogueEvidenceSummary(**semantic, **evidence)

    def _log_catalogue_evidence_failures(self, urls: typing.Iterable[str]) -> None:
        """Log batch failures with exact identities and bounded cache diagnostics."""
        from .catalogue_identity import catalogue_model_id
        from .catalogue_stem_cache import lookup_stems

        scoped = self._family_catalogue_meta()
        url_entries = getattr(self, "_catalogue_evidence_url_entries", {})
        for url in urls:
            hit = lookup_stems(url)
            error = getattr(hit, "last_error", None) if hit is not None else None
            if error is None:
                continue
            for family, label in url_entries.get(url, ()):
                meta = scoped.get(family, {}).get(label)
                catalogue = getattr(self, f"{family}_download_list", {})
                raw = catalogue.get(label) if isinstance(catalogue, dict) else None
                model_id = catalogue_model_id(family, label, raw, meta) or f"{family}:{label}"
                log_event(
                    "download",
                    "catalogue_evidence_validation_failed",
                    level="warning",
                    model_id=model_id,
                    url=url,
                    error_type=getattr(error, "kind", type(error).__name__),
                    message=getattr(error, "message", str(error)),
                )

    def queue_catalogue_evidence(
        self,
        entries: typing.Iterable[tuple[str, str]] | None = None,
        *,
        priority: bool = False,
        force: bool = False,
        on_complete: Callable[[CatalogueEvidenceSummary], None] | None = None,
    ) -> tuple[str, ...]:
        """Queue exact config evidence and expose pending state immediately.

        ``entries`` contains canonical ``(family, catalogue selection)`` pairs.
        Omitting it selects every current family-scoped entry. Force bypasses
        both success and failure TTLs without deleting last-known-good cache
        evidence.
        """
        from .catalog_sources import _needs_catalogue_config_evidence, _yaml_config_url
        from .catalogue_stem_cache import (
            enqueue_missing,
            ensure_worker_started,
            lookup_stems,
        )
        from .catalogue_types import CatalogueEvidenceState

        scoped = self._family_catalogue_meta()
        public_scoped = self._public_family_catalogue_meta()
        requested = (
            tuple(entries)
            if entries is not None
            else tuple(
                (family, label) for family, metadata in public_scoped.items() for label in metadata
            )
        )
        selected: list[tuple[str, str, Any, str]] = []
        seen_entries: set[tuple[str, str, str]] = set()
        for family, label in requested:
            metadata = scoped.get(str(family), {})
            meta = metadata.get(str(label))
            if meta is None or str(family) != "mdx":
                continue
            url = _yaml_config_url(meta.files)
            if not url:
                continue
            entry_key = (str(family), str(label), url)
            if entry_key in seen_entries:
                continue
            if not force:
                hit = lookup_stems(url)
                if hit is not None:
                    if not (hit.ok and not hit.content_sha256) and not hit.revalidation_due:
                        continue
                elif not _needs_catalogue_config_evidence(meta) and not meta.config_sha256:
                    continue
            seen_entries.add(entry_key)
            selected.append((str(family), str(label), meta, url))

        urls = tuple(sorted({item[3] for item in selected}))
        if not urls:
            return ()
        published_urls: tuple[str, ...] = ()

        def publish_reserved(accepted: tuple[str, ...]) -> None:
            nonlocal published_urls
            accepted_set = set(accepted)
            published_urls = tuple(url for url in urls if url in accepted_set)
            accepted_entries = [item for item in selected if item[3] in accepted_set]
            changed: Dict[str, list[str]] = {}
            for family, label, meta, _url in accepted_entries:
                status = getattr(meta, "catalogue_evidence_status", None)
                if status is not CatalogueEvidenceState.UNAVAILABLE:
                    continue
                pending_meta = dataclasses.replace(
                    meta,
                    catalogue_evidence_status=CatalogueEvidenceState.PENDING,
                    catalogue_evidence_warning="",
                )
                scoped[family][label] = pending_meta
                flat = getattr(self, "catalogue_meta", {})
                if flat.get(label) is meta:
                    flat[label] = pending_meta
                changed.setdefault(family, []).append(label)

            lock = getattr(self, "_catalogue_evidence_lock", None)
            if lock is None:
                self._catalogue_evidence_lock = threading.Lock()
                lock = self._catalogue_evidence_lock
                self._catalogue_evidence_pending = set()
            with lock:
                self._catalogue_evidence_pending.update(published_urls)
                if force:
                    self._catalogue_evidence_force_pending.update(published_urls)
                    if on_complete is not None:
                        self._catalogue_evidence_callbacks.append(on_complete)
                for family, label, _meta, url in accepted_entries:
                    associations = self._catalogue_evidence_url_entries.setdefault(url, [])
                    association = (family, label)
                    if association not in associations:
                        associations.append(association)
            if force:
                summary = self.catalogue_evidence_summary()
                log_event(
                    "download",
                    "catalogue_evidence_batch_started",
                    urls=len(published_urls),
                    force=True,
                    **dataclasses.asdict(summary),
                )
            coordinator = getattr(self, "_coordinator", None)
            notify = getattr(coordinator, "notify_metadata", None)
            if changed and callable(notify):
                notify({family: tuple(labels) for family, labels in changed.items()})
            self._ensure_catalogue_evidence_listener()

        accepted = enqueue_missing(
            urls,
            priority=priority,
            force=force,
            on_reserved=publish_reserved,
        )
        if not accepted:
            return ()
        ensure_worker_started()
        return published_urls

    def force_revalidate_catalogue_evidence(
        self,
        on_complete: Callable[[CatalogueEvidenceSummary], None] | None = None,
    ) -> tuple[str, ...]:
        """Conditionally revalidate every current config without clearing LKG."""
        return self.queue_catalogue_evidence(force=True, on_complete=on_complete)

    # -- Download lists ---------------------------------------------------------

    def _installed_mdx_alias_keys(self) -> set[str]:
        """Return logical catalogue identities with any checkpoint on disk.

        ``catalogue_meta`` deliberately retains rows removed by catalogue
        deduplication. That makes it the authoritative alias inventory when
        two sources give the same model different local filenames.
        """
        installed: set[str] = set()
        for meta in self.catalogue_meta.values():
            if getattr(meta, "arch", None) != MDX_ARCH_TYPE:
                continue
            checkpoint = getattr(meta, "checkpoint", None)
            label = getattr(meta, "label", None)
            if not checkpoint or not label:
                continue
            if os.path.isfile(os.path.join(paths.MDX_MODELS_DIR, checkpoint)):
                key = normalize_catalogue_label(label)
                if key:
                    installed.add(key)
        return installed

    def available_downloads(self, model_type: str = ALL_TYPES) -> Dict[str, List[str]]:
        """Return ``{arch_type: [selectable, ...]}`` of not-yet-downloaded models.

        Faithful port of ``download_list_fill``: filters each catalogue entry by
        whether the target file already exists on disk. Config YAMLs are fetched
        when a model is resolved for download, not while building this list.
        """
        result: Dict[str, List[str]] = {}

        if model_type in (VR_ARCH_TYPE, ALL_TYPES):
            vr_list = [
                selectable
                for selectable, model in self.vr_download_list.items()
                if not os.path.isfile(
                    os.path.join(
                        paths.VR_MODELS_DIR,
                        mdx_checkpoint_filename(model) if isinstance(model, dict) else model,
                    )
                )
            ]
            result[VR_ARCH_TYPE] = vr_list or [NO_NEW_MODELS]

        if model_type in (MDX_ARCH_TYPE, ALL_TYPES):
            mdx_list: List[str] = []
            installed_alias_keys = self._installed_mdx_alias_keys()
            for selectable, model in self.mdx_download_list.items():
                if isinstance(model, dict):
                    model_name = mdx_checkpoint_filename(model)
                else:
                    model_name = str(model)
                alias_key = normalize_catalogue_label(selectable)
                if (
                    not os.path.isfile(os.path.join(paths.MDX_MODELS_DIR, model_name))
                    and alias_key not in installed_alias_keys
                ):
                    mdx_list.append(selectable)
            result[MDX_ARCH_TYPE] = mdx_list or [NO_NEW_MODELS]

        if model_type in (DEMUCS_ARCH_TYPE, ALL_TYPES):
            demucs_list: List[str] = []
            for selectable, model in self.demucs_download_list.items():
                for file_name in model.keys():
                    if any(x in selectable for x in DEMUCS_NEWER_ARCH_TYPES):
                        target = os.path.join(paths.DEMUCS_NEWER_REPO_DIR, file_name)
                    else:
                        target = os.path.join(paths.DEMUCS_MODELS_DIR, file_name)
                    if not os.path.isfile(target):
                        demucs_list.append(selectable)
            # Preserve order while de-duplicating (matches dict.fromkeys in UVR).
            demucs_list = list(dict.fromkeys(demucs_list))
            result[DEMUCS_ARCH_TYPE] = demucs_list or [NO_NEW_MODELS]

        if model_type in (APOLLO_ARCH_TYPE, ALL_TYPES):
            apollo_list = [
                selectable
                for selectable, model in self.apollo_download_list.items()
                if not os.path.isfile(
                    os.path.join(paths.APOLLO_MODELS_DIR, apollo_checkpoint_filename(model))
                )
            ]
            result[APOLLO_ARCH_TYPE] = apollo_list or [NO_NEW_MODELS]

        return result

    def unsupported_downloads(
        self, model_type: str = ALL_TYPES
    ) -> Dict[str, List[Tuple[str, str]]]:
        """Return ``{arch_type: [(label, reason), ...]}`` for non-runnable catalogue rows."""
        if model_type == ALL_TYPES:
            return {
                arch: list(rows) for arch, rows in self.unsupported_download_list.items() if rows
            }
        rows = self.unsupported_download_list.get(model_type) or []
        return {model_type: list(rows)} if rows else {}

    def _ensure_mdx_c_config(self, config: str) -> None:
        ensure_mdx_c_config(config)

    # -- Resolve a selection to concrete download jobs --------------------------

    def resolve(
        self,
        selection: str,
        arch_type: str,
        *,
        fetch_config: bool = True,
        catalogue: Mapping[str, Any] | None = None,
    ) -> List[Tuple[str, str]]:
        """Return ``[(url, save_path), ...]`` for ``selection``.

        Port of ``download_model_select`` + the per-arch branches of
        ``download_item``. VR/MDX yield a single job; Demucs v3/v4 ("newer") yield
        one job per checkpoint/yaml file.
        """
        if not selection or selection in (NO_MODEL, NO_NEW_MODELS):
            return []

        model_repo = (
            ADDITIONAL_MODEL_REPO if LEGACY_ADDITIONAL_REPO_SELECTION in selection else NORMAL_REPO
        )

        if arch_type == VR_ARCH_TYPE:
            model = (catalogue or self.vr_download_list).get(selection)
            if model:
                return resolve_vr_jobs(model, model_repo)
        elif arch_type == MDX_ARCH_TYPE:
            model = (catalogue or self.mdx_download_list).get(selection)
            if model is not None:
                return resolve_mdx_jobs(model, model_repo, fetch_config=fetch_config)
        elif arch_type == DEMUCS_ARCH_TYPE:
            model = (catalogue or self.demucs_download_list).get(selection)
            if model:
                return resolve_demucs_jobs(model, selection)
        elif arch_type == APOLLO_ARCH_TYPE:
            model = (catalogue or self.apollo_download_list).get(selection)
            if model:
                return resolve_apollo_jobs(model)
        else:
            return []

        reason = self._unsupported_reason(selection)
        if reason:
            raise ValueError(f"model is listed but not downloadable yet: {reason}")
        return []

    def _unsupported_reason(self, selection: str) -> Optional[str]:
        """Classify a catalogue miss from already-merged state.

        Resolving an unknown label must not FORCE-fetch mvsepless just to
        decide between ``[]`` and ``ValueError``. After ``ensure_catalogues``
        / ``_merge_politrees_supplement`` the manager already has
        ``unsupported_download_list``; the helper only consults the in-memory
        or disk snapshot.
        """
        for rows in self.unsupported_download_list.values():
            for label, why in rows:
                if label == selection:
                    return why
        return unsupported_reason_for_label(selection, allow_network=False)

    def describe_selection_download_size(self, selection: str, arch_type: str) -> str:
        """Human-readable size estimate for a catalogue selection."""
        jobs = self.resolve(selection, arch_type)
        if not jobs:
            return "—"
        return describe_download_size(jobs)

    # -- Downloading ------------------------------------------------------------

    def download(
        self,
        jobs: List[Tuple[str, str]],
        on_progress: Optional[Callable[[float], None]] = None,
        on_info: Optional[Callable[[str], None]] = None,
        stop_event: typing.Any = None,
    ) -> str:
        """Download every ``(url, save_path)`` job sequentially.

        Transfer only. Registration, usability verification and repository
        publication belong to ``core.model_install.finalize_downloaded_model``,
        which both frontends call once per logical model -- doing any of it here
        published models before all of their artifacts had landed.

        Reports overall progress in ``[0, 1]`` via ``on_progress`` and a short
        status string via ``on_info``. Honours a ``threading.Event``-style
        ``stop_event`` for cooperative cancellation (checked between chunks).
        Returns one of ``"complete"`` / ``"stopped"`` / ``"exists"``; raises on
        network/IO error so the caller can surface it through the error log.
        """
        from .debug_log import debug, debug_elapsed

        if not jobs:
            if on_info:
                on_info(NO_MODEL)
            return "exists"

        started = time.perf_counter()
        debug("download", f"download start jobs={len(jobs)}")
        pending_jobs = [(url, path) for url, path in jobs if not os.path.isfile(path)]
        total_bytes, file_count, known = estimate_jobs_size(pending_jobs)

        # Weight the bar by bytes, not by file count. A model is typically a
        # ~400 MB checkpoint plus a ~4 KB config; splitting the bar evenly
        # between them pins it at 50% for the whole transfer. Sizes have to be
        # known for *every* pending file or the denominator is short and the
        # fraction runs past 1.0, so fall back to counting pending files —
        # already-present ones never report and must stay out of both halves.
        byte_weighted = bool(total_bytes) and known == file_count and file_count > 0
        pending_total = max(1, file_count)
        bytes_done = 0
        pending_index = 0

        def report(downloaded: int, file_total: int) -> None:
            if on_progress is None:
                return
            if byte_weighted and total_bytes:
                overall = (bytes_done + downloaded) / total_bytes
            elif file_total:
                overall = (pending_index + downloaded / file_total) / pending_total
            else:
                return
            on_progress(max(0.0, min(1.0, overall)))

        any_downloaded = False
        for _index, (url, save_path) in enumerate(jobs):
            if stop_event is not None and stop_event.is_set():
                debug("download", "download stopped by user")
                return "stopped"
            if os.path.isfile(save_path):
                continue
            any_downloaded = True
            if on_info:
                if total_bytes is not None:
                    on_info(f"Downloading ({format_download_size(total_bytes)})")
                else:
                    on_info("Downloading…")
            self._download_file(url, save_path, report, stop_event, on_info)
            if stop_event is not None and stop_event.is_set():
                # Remove the partial file so a retry restarts cleanly.
                if os.path.isfile(save_path):
                    try:
                        os.remove(save_path)
                    except OSError:
                        pass
                return "stopped"
            # Advance the baseline by what actually landed on disk, so a
            # short read or an HF-fallback retry cannot double-count.
            try:
                bytes_done += os.path.getsize(save_path)
            except OSError:
                pass
            pending_index += 1

        if on_progress:
            on_progress(1.0)
        result = "complete" if any_downloaded else "exists"
        debug_elapsed("download", f"download done status={result}", started)
        return result

    @staticmethod
    def _download_stopped(stop_event: typing.Any) -> bool:
        return stop_event is not None and stop_event.is_set()

    def _finalize_part_file(self, tmp_path: str, save_path: str, stop_event: typing.Any) -> None:
        """Rename a completed ``.part`` file unless the download was cancelled."""
        if self._download_stopped(stop_event):
            return
        if not os.path.isfile(tmp_path):
            raise FileNotFoundError(
                errno.ENOENT,
                os.strerror(errno.ENOENT),
                tmp_path,
            )
        os.replace(tmp_path, save_path)

    def _download_file(
        self,
        url: typing.Any,
        save_path: typing.Any,
        report: typing.Any,
        stop_event: typing.Any,
        on_info: typing.Any = None,
    ) -> None:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        tmp_path = f"{save_path}.part"
        try:
            self._download_file_url(url, tmp_path, report, stop_event, on_info)
            if self._download_stopped(stop_event):
                return
            self._finalize_part_file(tmp_path, save_path, stop_event)
        except Exception:
            if self._download_stopped(stop_event):
                return
            fallback = hf_fallback_url(url)
            if fallback and fallback != url:
                debug("download", f"hf fallback {os.path.basename(save_path)}")
                try:
                    if os.path.isfile(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    pass
                self._download_file_url(fallback, tmp_path, report, stop_event, on_info)
                if self._download_stopped(stop_event):
                    return
                self._finalize_part_file(tmp_path, save_path, stop_event)
                return
            if os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def _download_file_url(
        self,
        url: typing.Any,
        tmp_path: typing.Any,
        report: typing.Any,
        stop_event: typing.Any,
        on_info: typing.Any = None,
    ) -> None:
        try:
            with _urlopen(url) as response:
                length_header = response.getheader("Content-Length")
                file_total = (
                    int(length_header)
                    if isinstance(length_header, str) and length_header.isdigit()
                    else 0
                )
                downloaded = 0
                last_info_at = 0.0
                last_info_text = ""
                with open(tmp_path, "wb") as out_file:
                    while True:
                        if stop_event is not None and stop_event.is_set():
                            out_file.close()
                            if os.path.isfile(tmp_path):
                                try:
                                    os.remove(tmp_path)
                                except OSError:
                                    pass
                            return
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if report is not None:
                            report(downloaded, file_total)
                        if on_info and file_total:
                            info_text = (
                                f"{format_download_size(downloaded)} / "
                                f"{format_download_size(file_total)}"
                            )
                            now = time.monotonic()
                            if info_text != last_info_text and (
                                now - last_info_at >= _INFO_UPDATE_INTERVAL_S
                                or downloaded >= file_total
                            ):
                                last_info_at = now
                                last_info_text = info_text
                                on_info(info_text)
                if file_total and downloaded != file_total:
                    raise OSError(
                        f"Incomplete download: received {downloaded} bytes, expected {file_total}"
                    )
        except Exception:
            if os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    # -- Model-data mapper refresh ----------------------------------------------

    def update_model_settings(self, repo: typing.Any = None) -> bool:
        """Download and persist the four model-data mapper JSON files.

        Port of ``download_model_settings``; on any failure existing local files
        are left untouched. Returns ``True`` on a successful refresh.

        Name mappers are written as a pure upstream mirror; fork-local keys
        live in a sibling ``*_local.json`` overlay (see :mod:`core.name_mapper`)
        and are merged on read, so an upstream deletion propagates instead of
        surviving forever in a union file. Hash maps replace. Unchanged payloads
        are not rewritten; stem-check invalidation runs only when a file changes.

        When ``repo`` is supplied, its stem-check cache is invalidated after a
        successful refresh that actually changed on-disk data.
        """
        debug("download", "update_model_settings start")
        try:
            fetched = []
            for url, _dest in _MODEL_DATA_URLS:
                with _urlopen(url) as response:
                    fetched.append(json.load(response))
        except Exception as exc:
            debug(
                "download",
                f"update_model_settings fetch failed error={type(exc).__name__}: {exc}",
            )
            return False

        from .name_mapper import local_overlay_path, plan_local_overlay_migration

        writes: Dict[str, Mapping[str, Any]] = {}
        name_mapper_payloads: Dict[str, Mapping[str, Any]] = {}
        # Tracked apart so a pure relabelling refresh repaints the pickers
        # without staling resolved plans or rehashing every checkpoint.
        hash_changed = False
        name_changed = False
        for (_url, dest), data in zip(_MODEL_DATA_URLS, fetched, strict=True):
            if not isinstance(data, dict):
                debug("download", f"update_model_settings invalid payload path={dest}")
                return False
            payload: Mapping[str, Any] = data
            is_name_mapper = dest in _NAME_MAPPER_DESTS
            if is_name_mapper:
                name_mapper_payloads[dest] = payload
            writes[dest] = payload

        def prepare_locked() -> Mapping[str, Mapping[str, Any]]:
            nonlocal hash_changed, name_changed
            overlay_writes: Dict[str, Mapping[str, Any]] = {}
            for dest, payload in writes.items():
                if not _json_file_matches(dest, payload):
                    if dest in name_mapper_payloads:
                        name_changed = True
                    else:
                        hash_changed = True
            for dest, payload in name_mapper_payloads.items():
                local_only = plan_local_overlay_migration(dest, payload)
                if local_only is not None:
                    overlay_writes[local_overlay_path(dest)] = local_only
                    name_changed = name_changed or bool(local_only)
            return overlay_writes

        overlay_paths = tuple(local_overlay_path(dest) for dest in name_mapper_payloads)
        ok, _wrote_files = _transactional_json_refresh(
            writes,
            locked_paths=overlay_paths,
            prepare_locked=prepare_locked,
        )
        if not ok:
            return False
        changed = hash_changed or name_changed
        if repo is not None:
            if hash_changed:
                # Not invalidate_stem_check: the hash maps and name mappers were
                # just rewritten on disk, and only reload_mappers picks those up.
                # Full invalidation subsumes any name change in the same
                # transaction, so never emit both events.
                repo.invalidate_models()
            elif name_changed:
                repo.invalidate_model_presentation(reload_mappers=True)
            coordinator = getattr(repo, "catalogue", None)
            snapshot = getattr(coordinator, "_latest", None)
            _attempt_presentation_backfill(repo, snapshot, operation="online model-metadata update")
        debug(
            "download",
            f"update_model_settings ok changed={changed} "
            f"hash_changed={hash_changed} name_changed={name_changed} "
            f"invalidated={changed and repo is not None}",
        )
        return True

    # -- Update check -----------------------------------------------------------

    def check_release(self) -> Dict[str, object]:
        """Fetch fork release metadata and return GTK version/update status."""
        return release_update_status(force_refresh=True)

    def update_status(self) -> Dict[str, object]:
        """Return GTK fork version / update status for the Updates UI."""
        return release_update_status()

    # -- Manual downloads -------------------------------------------------------

    def manual_download_data(self) -> Dict[str, dict]:
        """Return ``{vr, mdx, demucs}`` link catalogues for the manual flow.

        Reads the same merge as the Download Center and the runtime pickers.
        This used to build its own catalogue from ``online_data`` plus Politrees
        only — a third merge path that listed 197 models where the Download
        Center listed 459, missing every extras and mvsepless entry and showing
        duplicate VR rows that dedupe removes.

        Legacy ``*_vip_list`` entries are folded into the same public base before
        supplements and deduplication.

        Keys stay raw catalogue labels — ``manual_links`` resolves against them.
        Ordering uses the same exact family-scoped projector as every other
        catalogue surface.
        """
        from .model_catalogue import (
            catalogue_entry_meta,
            project_catalogue_display,
        )

        if self.online_data:
            # Compatibility overlay: tests and callers may assign ``online_data``
            # as the upstream payload. Rebuild from that rather than a coordinator
            # snapshot that may predate the assignment.
            self._rebuild_catalogues()
            self._merge_politrees_supplement(allow_network=False)
        elif not self._has_any_catalogue():
            self.ensure_catalogues(allow_network=False)
        vr, mdx, demucs = (
            dict(self.vr_download_list),
            dict(self.mdx_download_list),
            dict(self.demucs_download_list),
        )

        def by_display(family: str, catalogue: Dict[str, Any]) -> Dict[str, Any]:
            def display(label: str) -> str:
                raw = catalogue[label]
                meta = catalogue_entry_meta(self, family, label, exact=True)
                return project_catalogue_display(family, label, raw, meta)

            return {
                label: catalogue[label]
                for label in sorted(catalogue, key=lambda name: display(name).casefold())
            }

        return {
            "vr": by_display("vr", vr),
            "mdx": by_display("mdx", mdx),
            "demucs": by_display("demucs", demucs),
        }

    def manual_download_rows(self) -> Dict[str, tuple[ManualDownloadRow, ...]]:
        """Return exact projected rows while retaining native link inputs."""
        from .model_catalogue import (
            catalogue_entry_meta,
            project_catalogue_display,
        )

        data = self.manual_download_data()
        arch_types = {
            "vr": VR_ARCH_TYPE,
            "mdx": MDX_ARCH_TYPE,
            "demucs": DEMUCS_ARCH_TYPE,
        }
        return {
            family: tuple(
                ManualDownloadRow(
                    arch_types[family],
                    selection,
                    project_catalogue_display(
                        family,
                        selection,
                        model,
                        catalogue_entry_meta(self, family, selection, exact=True),
                    ),
                    model,
                )
                for selection, model in catalogue.items()
            )
            for family, catalogue in data.items()
        }

    @staticmethod
    def _load_cache() -> Dict:
        try:
            with open(DOWNLOAD_MODEL_CACHE, "r") as cache_file:
                return json.load(cache_file)
        except (OSError, ValueError):
            return {}

    @staticmethod
    def manual_links(
        arch_type: str,
        model: typing.Any,
        *,
        selection: str = "",
    ) -> List[Tuple[str, str]]:
        """Return ``[(label, url), ...]`` direct links for a manual-download entry."""
        model_repo = (
            ADDITIONAL_MODEL_REPO if LEGACY_ADDITIONAL_REPO_SELECTION in selection else NORMAL_REPO
        )
        return manual_links_for_model(arch_type, model, model_repo)

    @staticmethod
    def model_directory(arch_type: str, selection: str = "") -> str:
        """Return the on-disk directory a manually-downloaded model belongs in."""
        if arch_type == VR_ARCH_TYPE:
            return paths.VR_MODELS_DIR
        if arch_type == MDX_ARCH_TYPE:
            return paths.MDX_MODELS_DIR
        if arch_type == DEMUCS_ARCH_TYPE:
            if any(x in selection for x in DEMUCS_NEWER_ARCH_TYPES):
                return paths.DEMUCS_NEWER_REPO_DIR
            return paths.DEMUCS_MODELS_DIR
        if arch_type == APOLLO_ARCH_TYPE:
            return paths.APOLLO_MODELS_DIR
        return paths.MODELS_DIR
