"""On-disk cache of training.instruments parsed from catalogue YAML URLs."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from .access_policy import AccessPolicy, access_policy, current_access_policy
from .debug_log import log_event
from .mdx_config_fetch import _urlopen
from .model_data import load_mdx_c_config_data

_SUCCESS_TTL_SECONDS = 7 * 24 * 3600
_FAILURE_TTL_SECONDS = 6 * 3600
_MAX_BODY_BYTES = 2 * 1024 * 1024
_FETCH_WORKERS = 2

_memory_entries: Optional[Dict[str, Dict[str, Any]]] = None
#: Guards ``_memory_entries`` and the cache file. Reentrant because
#: ``remember_stems`` holds it across ``_ensure_loaded``. Needed since
#: ``_FETCH_WORKERS`` > 1 writes from several pool threads at once.
_entries_lock = threading.RLock()

#: PriorityQueue items are ``(priority, sequence, url, request)`` — lower priority first.
_url_queue: queue.PriorityQueue[tuple[int, int, str, "_QueuedRequest"]] = queue.PriorityQueue()
_queue_seq = itertools.count()
_request_seq = itertools.count()
#: url -> best priority currently queued, so a later priority enqueue can
#: promote a URL already sitting in the bulk backlog.
_queued_requests: Dict[str, "_QueuedRequest"] = {}
_queue_lock = threading.Lock()
#: Serializes reserve -> publish -> release so accepted work is never executable
#: before its caller has installed observable state.
_admission_lock = threading.Lock()
_subscribers: List[Callable[[], None]] = []
_subscribers_lock = threading.Lock()
_worker_thread: Optional[threading.Thread] = None
_worker_lock = threading.Lock()
_worker_idle = threading.Event()
_worker_idle.set()
_shutdown = threading.Event()


@dataclass(frozen=True)
class StemCacheError:
    """One compact, serializable validation failure for a config URL."""

    kind: str
    message: str
    at: float


@dataclass(frozen=True)
class _QueuedRequest:
    """One scheduled fetch with a least-privilege policy snapshot."""

    priority: int
    force: bool
    policy: AccessPolicy
    token: int


@dataclass(frozen=True)
class StemCacheHit:
    """Immutable cache view; old callers can keep using ``ok``."""

    stems: tuple[str, ...]
    target_instrument: Optional[str]
    ok: bool
    content_sha256: str = ""
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    fetched_at: float = 0.0
    checked_at: float = 0.0
    last_error: Optional[StemCacheError] = None
    stale: bool = False
    revalidation_due: bool = False
    warning: str = ""

    @property
    def usable(self) -> bool:
        """Whether this hit retains successfully parsed evidence."""
        return self.ok and bool(self.stems)


def catalogue_stems_enabled() -> bool:
    return os.environ.get("UVR_DISABLE_CATALOGUE_STEMS", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def normalize_config_url(url: str) -> str:
    return url.split("?", 1)[0]


def _cache_path() -> str:
    from core import paths

    if not current_access_policy().allow_cache_writes:
        from core.remote_catalog_cache import inspect_cache_path

        return inspect_cache_path("catalogue_stem_cache.json", paths.CATALOGUE_STEM_CACHE_FILE)

    return paths.migrate_cache_file("catalogue_stem_cache.json", paths.CATALOGUE_STEM_CACHE_FILE)


def _ensure_loaded() -> Dict[str, Dict[str, Any]]:
    global _memory_entries
    with _entries_lock:
        if _memory_entries is not None:
            return _memory_entries
        entries: Dict[str, Dict[str, Any]] = {}
        try:
            with open(_cache_path(), "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                raw = payload.get("entries")
                if isinstance(raw, dict):
                    for key, entry in raw.items():
                        if isinstance(key, str) and isinstance(entry, dict):
                            entries[key] = entry
        except (OSError, ValueError, TypeError):
            pass
        _memory_entries = entries
        return entries


def _number(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else default


def _valid_digest(value: object) -> str:
    if not isinstance(value, str):
        return ""
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        return ""
    return value


def _optional_text(value: object) -> Optional[str]:
    return str(value) if value is not None and value != "" else None


def _entry_stems(entry: Mapping[str, Any]) -> list[str]:
    raw_stems = entry.get("stems")
    return (
        [str(stem) for stem in raw_stems if stem is not None] if isinstance(raw_stems, list) else []
    )


def _entry_error(entry: Mapping[str, Any]) -> Optional[StemCacheError]:
    raw = entry.get("last_error")
    if not isinstance(raw, Mapping):
        return None
    kind = raw.get("kind")
    message = raw.get("message")
    at = raw.get("at")
    if (
        not isinstance(kind, str)
        or not isinstance(message, str)
        or not isinstance(at, (int, float))
    ):
        return None
    return StemCacheError(kind=kind, message=message, at=float(at))


def _normalized_entry(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Accept legacy ``ok`` records in memory, but expose schema-2 fields."""
    stems = _entry_stems(entry)
    target = _optional_text(entry.get("target_instrument"))
    fetched_at = _number(entry.get("fetched_at"))
    checked_at = _number(entry.get("checked_at"), fetched_at)
    if checked_at <= 0:
        checked_at = fetched_at
    error = _entry_error(entry)
    legacy_ok = entry.get("ok")
    usable = bool(stems) and (legacy_ok is not False)
    if legacy_ok is False and error is None:
        error = StemCacheError("legacy_failure", "legacy cache validation failed", checked_at)
    normalized: Dict[str, Any] = {
        "stems": stems if usable else [],
        "target_instrument": target if usable else None,
        "content_sha256": _valid_digest(entry.get("content_sha256")) if usable else "",
        "etag": _optional_text(entry.get("etag")),
        "last_modified": _optional_text(entry.get("last_modified")),
        "fetched_at": fetched_at if usable else 0.0,
        "checked_at": checked_at,
        "last_error": (
            {"kind": error.kind, "message": error.message, "at": error.at}
            if error is not None
            else None
        ),
    }
    return normalized


def _entry_has_evidence(entry: Mapping[str, Any]) -> bool:
    return bool(_entry_stems(entry)) and entry.get("ok") is not False


def _entry_ttl_seconds(entry: Mapping[str, Any]) -> float:
    return (
        _FAILURE_TTL_SECONDS
        if _entry_error(entry) is not None or not _entry_has_evidence(entry)
        else _SUCCESS_TTL_SECONDS
    )


def _entry_fresh(entry: Mapping[str, Any], *, now: Optional[float] = None) -> bool:
    checked_at = entry.get("checked_at", entry.get("fetched_at"))
    if not isinstance(checked_at, (int, float)):
        return False
    if now is None:
        now = time.time()
    return (now - float(checked_at)) <= _entry_ttl_seconds(entry)


def _entry_to_hit(entry: Mapping[str, Any], *, now: Optional[float] = None) -> StemCacheHit:
    normalized = _normalized_entry(entry)
    stems = tuple(normalized["stems"])
    error = _entry_error(normalized)
    usable = bool(stems)
    fresh = _entry_fresh(normalized, now=now)
    if error is not None:
        warning = error.message
    else:
        warning = ""
    return StemCacheHit(
        stems=stems,
        target_instrument=normalized["target_instrument"],
        ok=usable,
        content_sha256=normalized["content_sha256"],
        etag=normalized["etag"],
        last_modified=normalized["last_modified"],
        fetched_at=normalized["fetched_at"],
        checked_at=normalized["checked_at"],
        last_error=error,
        stale=bool(error) or not fresh,
        revalidation_due=not fresh,
        warning=warning,
    )


def lookup_stems(url: str) -> Optional[StemCacheHit]:
    if not catalogue_stems_enabled():
        return None
    key = normalize_config_url(url)
    entry = _ensure_loaded().get(key)
    if entry is None:
        return None
    hit = _entry_to_hit(entry)
    if hit.usable:
        return hit
    if not _entry_fresh(entry):
        return None
    return hit


def remember_stems(
    url: str,
    stems: Sequence[str],
    target_instrument: Optional[str],
    *,
    content_sha256: str = "",
    ok: bool,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
    error_kind: str = "validation",
    error_message: str = "YAML validation failed",
) -> None:
    """Record validated config evidence or a structured validation failure.

    A failure never discards existing evidence. This is deliberately one API so
    the background worker cannot accidentally turn a transient failure into a
    six-hour empty-cache poison pill.
    """
    key = normalize_config_url(url)
    now = time.time()
    with _entries_lock:
        entries = _ensure_loaded()
        previous = entries.get(key)
        prior = _normalized_entry(previous) if isinstance(previous, Mapping) else None
        clean_stems = [str(stem) for stem in stems]
        drift_kind = ""
        if ok and clean_stems:
            prior_stems = tuple(prior["stems"]) if prior else ()
            prior_target = prior["target_instrument"] if prior else None
            prior_digest = prior["content_sha256"] if prior else ""
            digest = _valid_digest(content_sha256)
            if prior_digest and digest and prior_digest != digest:
                if prior_stems == tuple(clean_stems) and prior_target == target_instrument:
                    drift_kind = "digest"
                else:
                    drift_kind = "semantic"
            entry: Dict[str, Any] = {
                "stems": clean_stems,
                "target_instrument": _optional_text(target_instrument),
                "content_sha256": digest,
                "etag": _optional_text(etag),
                "last_modified": _optional_text(last_modified),
                "fetched_at": now,
                "checked_at": now,
                "last_error": None,
            }
        elif prior is not None and bool(prior["stems"]):
            entry = dict(prior)
            entry["checked_at"] = now
            entry["last_error"] = {
                "kind": error_kind,
                "message": error_message,
                "at": now,
            }
        else:
            entry = {
                "stems": [],
                "target_instrument": None,
                "content_sha256": "",
                "etag": _optional_text(etag),
                "last_modified": _optional_text(last_modified),
                "fetched_at": 0.0,
                "checked_at": now,
                "last_error": {
                    "kind": error_kind,
                    "message": error_message,
                    "at": now,
                },
            }
        entries[key] = entry
        from .access_policy import current_access_policy

        if not current_access_policy().allow_cache_writes:
            pass
        else:
            _write_entries_locked(entries)
    if drift_kind:
        log_event(
            "cache", "catalogue_stem_evidence_drift", level="warning", url=key, kind=drift_kind
        )


def _write_entries_locked(entries: Mapping[str, Mapping[str, Any]]) -> None:
    """Write only schema 2; callers hold ``_entries_lock`` across replace."""
    try:
        cache_path = _cache_path()
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        normalized = {key: _normalized_entry(entry) for key, entry in entries.items()}
        tmp_path = f"{cache_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 2, "entries": normalized}, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, cache_path)
    except OSError:
        # The old file remains authoritative when replacing the temporary file
        # fails. Memory retains the update and a later successful mutation
        # writes the complete snapshot.
        try:
            os.unlink(f"{_cache_path()}.tmp")
        except OSError:
            pass


def clear_catalogue_stem_cache() -> None:
    global _memory_entries
    with _entries_lock:
        _memory_entries = None
        from .access_policy import current_access_policy

        if current_access_policy().allow_cache_writes:
            try:
                os.remove(_cache_path())
            except OSError:
                pass
    from .model_display import clear_display_cache

    clear_display_cache()


def parse_stems_from_yaml_bytes(data: bytes) -> tuple[list[str], Optional[str]]:
    """Extract the minimal training evidence from one restricted MDX-C YAML."""
    doc = load_mdx_c_config_data(data)
    if not isinstance(doc, Mapping):
        raise ValueError("config document must be a mapping")
    training = doc.get("training")
    if not isinstance(training, Mapping):
        raise ValueError("config document has no training mapping")
    instruments = training.get("instruments")
    stems: list[str] = []
    if isinstance(instruments, (list, tuple)):
        stems = [str(item) for item in instruments if item is not None]
    if not stems:
        raise ValueError("config training.instruments is empty")
    target = training.get("target_instrument")
    target_instrument: Optional[str] = None
    if target is not None and target != "":
        target_instrument = str(target)
    return stems, target_instrument


def subscribe(callback: Callable[[], None]) -> None:
    with _subscribers_lock:
        if callback not in _subscribers:
            _subscribers.append(callback)


def unsubscribe(callback: Callable[[], None]) -> None:
    with _subscribers_lock:
        try:
            _subscribers.remove(callback)
        except ValueError:
            pass


def _notify_subscribers() -> None:
    # Do not clear_display_cache here: stem apply patches catalogue_meta in
    # place via DownloadManager.apply_catalogue_stem_cache. A full remesh on
    # every YAML batch was rebuilding politrees/extras/mvsepless repeatedly.
    with _subscribers_lock:
        callbacks = list(_subscribers)
    for callback in callbacks:
        try:
            callback()
        except Exception as exc:
            log_event(
                "cache",
                "catalogue_stem_subscriber_failed",
                level="warning",
                subscriber_type=type(callback).__name__,
                error_type=type(exc).__name__,
                message=str(exc),
            )


def _merge_policy(left: AccessPolicy, right: AccessPolicy) -> AccessPolicy:
    """A coalesced request never gains a capability from another caller."""
    return AccessPolicy(
        allow_network=left.allow_network and right.allow_network,
        allow_metadata_writes=left.allow_metadata_writes and right.allow_metadata_writes,
        allow_cache_writes=bool(left.allow_cache_writes) and bool(right.allow_cache_writes),
    )


def _merge_queued_request(left: _QueuedRequest, right: _QueuedRequest) -> _QueuedRequest:
    return _QueuedRequest(
        priority=min(left.priority, right.priority),
        force=left.force or right.force,
        policy=_merge_policy(left.policy, right.policy),
        token=max(left.token, right.token),
    )


def enqueue_missing(
    urls: Iterable[str],
    *,
    priority: bool = False,
    force: bool = False,
    on_reserved: Callable[[tuple[str, ...]], None] | None = None,
) -> tuple[str, ...]:
    """Queue YAML URLs for background stem fetch.

    ``priority=True`` jumps ahead of bulk/background URLs (Download Center
    visible rows). A URL already queued at the same or better priority is
    skipped; one queued at a worse priority is re-queued at the better one and
    the worker drops the superseded copy. The return value is the exact set of
    normalized URLs accepted as queued/in-flight work; disabled, offline, and
    shutdown callers receive an empty tuple. ``on_reserved`` runs after the
    URLs are admitted but before any corresponding queue item becomes
    executable, allowing callers to publish pending/subscriber state atomically.
    """
    policy = current_access_policy()
    if not catalogue_stems_enabled() or not policy.allow_network or _shutdown.is_set():
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for url in urls:
        key = normalize_config_url(str(url))
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    if not normalized:
        return ()

    prio = 0 if priority else 1
    with _admission_lock:
        if not catalogue_stems_enabled() or not policy.allow_network or _shutdown.is_set():
            return ()
        reserved: list[tuple[str, _QueuedRequest, _QueuedRequest | None]] = []
        with _queue_lock:
            for key in normalized:
                request = _QueuedRequest(
                    priority=prio,
                    force=force,
                    policy=policy,
                    token=next(_request_seq),
                )
                current = _queued_requests.get(key)
                merged = _merge_queued_request(current, request) if current else request
                _queued_requests[key] = merged
                reserved.append((key, merged, current))
        accepted = tuple(key for key, _request, _previous in reserved)
        try:
            if on_reserved is not None:
                on_reserved(accepted)
        except Exception:
            with _queue_lock:
                for key, request, previous in reserved:
                    if _queued_requests.get(key) != request:
                        continue
                    if previous is None:
                        _queued_requests.pop(key, None)
                    else:
                        _queued_requests[key] = previous
                        _url_queue.put((previous.priority, next(_queue_seq), key, previous))
            raise
        with _queue_lock:
            for key, request, _previous in reserved:
                if _queued_requests.get(key) == request:
                    _url_queue.put((request.priority, next(_queue_seq), key, request))
        return accepted


def pending_urls() -> frozenset[str]:
    """Return normalized config URLs that are queued or currently in flight."""
    with _queue_lock:
        return frozenset(_queued_requests)


def is_pending(url: str) -> bool:
    """Whether one exact config URL is queued or currently in flight."""
    return normalize_config_url(url) in pending_urls()


def request_shutdown() -> None:
    """Stop accepting new stem fetches (idempotent)."""
    _shutdown.set()


def ensure_worker_started() -> None:
    policy = current_access_policy()
    if not policy.allow_network or _shutdown.is_set():
        return
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        thread = threading.Thread(
            target=_worker_loop,
            name="uvr-catalogue-stems",
            daemon=True,
        )
        _worker_thread = thread
        thread.start()


def _response_validator(response: Any, name: str) -> Optional[str]:
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get", None)
    value = getter(name) if callable(getter) else None
    return _optional_text(value)


def _mark_not_modified(url: str, response: Any = None) -> bool:
    """Advance a conditional validation without changing parsed body evidence."""
    key = normalize_config_url(url)
    now = time.time()
    with _entries_lock:
        entries = _ensure_loaded()
        current = entries.get(key)
        if not isinstance(current, Mapping):
            remember_stems(
                url,
                [],
                None,
                ok=False,
                error_kind="protocol",
                error_message="HTTP 304 without cached evidence",
            )
            return False
        entry = _normalized_entry(current)
        if not entry["stems"]:
            remember_stems(
                url,
                [],
                None,
                ok=False,
                error_kind="protocol",
                error_message="HTTP 304 without cached evidence",
            )
            return False
        etag = _response_validator(response, "ETag") if response is not None else None
        last_modified = (
            _response_validator(response, "Last-Modified") if response is not None else None
        )
        if etag is not None:
            entry["etag"] = etag
        if last_modified is not None:
            entry["last_modified"] = last_modified
        entry["checked_at"] = now
        entry["last_error"] = None
        entries[key] = entry
        from .access_policy import current_access_policy

        if current_access_policy().allow_cache_writes:
            _write_entries_locked(entries)
    return True


def _remember_fetch_failure(url: str, kind: str, message: str) -> bool:
    remember_stems(url, [], None, ok=False, error_kind=kind, error_message=message)
    log_event("cache", "catalogue_stem_validation_failed", level="warning", url=url, kind=kind)
    return False


def _fetch_and_remember(
    url: str,
    *,
    force: bool = False,
    policy: Optional[AccessPolicy] = None,
) -> bool:
    """Fetch one YAML, preserving prior evidence unless a complete 200 validates."""
    if policy is not None:
        with access_policy(
            allow_network=policy.allow_network,
            allow_metadata_writes=policy.allow_metadata_writes,
            allow_cache_writes=policy.allow_cache_writes,
        ):
            return _fetch_and_remember(url, force=force)
    key = normalize_config_url(url)
    with _entries_lock:
        current = _ensure_loaded().get(key)
        if not force and isinstance(current, Mapping) and _entry_fresh(current):
            return _entry_has_evidence(current)
        prior_hit = _entry_to_hit(current) if isinstance(current, Mapping) else None
    headers: Dict[str, str] = {}
    if prior_hit is not None:
        if prior_hit.etag:
            headers["If-None-Match"] = prior_hit.etag
        if prior_hit.last_modified:
            headers["If-Modified-Since"] = prior_hit.last_modified
    request = urllib.request.Request(key, headers=headers)
    try:
        with _urlopen(request) as response:
            status = getattr(response, "status", None)
            if status is None:
                getcode = getattr(response, "getcode", None)
                status = getcode() if callable(getcode) else 200
            if status == 304:
                return _mark_not_modified(key, response)
            if status != 200:
                return _remember_fetch_failure(key, "http", f"HTTP {status}")
            data = response.read(_MAX_BODY_BYTES + 1)
            etag = _response_validator(response, "ETag")
            last_modified = _response_validator(response, "Last-Modified")
        if not isinstance(data, (bytes, bytearray)):
            return _remember_fetch_failure(key, "response", "response body is not bytes")
        body = bytes(data)
        if len(body) > _MAX_BODY_BYTES:
            return _remember_fetch_failure(key, "size", "response body exceeds 2 MiB")
        try:
            stems, target = parse_stems_from_yaml_bytes(body)
        except Exception as exc:
            return _remember_fetch_failure(key, "parse", f"YAML parse failed: {type(exc).__name__}")
        remember_stems(
            key,
            stems,
            target,
            content_sha256=hashlib.sha256(body).hexdigest(),
            ok=True,
            etag=etag,
            last_modified=last_modified,
        )
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            try:
                return _mark_not_modified(key, exc)
            finally:
                exc.close()
        try:
            return _remember_fetch_failure(key, "http", f"HTTP {exc.code}")
        finally:
            exc.close()
    except Exception as exc:
        return _remember_fetch_failure(key, "network", f"request failed: {type(exc).__name__}")


def _dedupe_sorted(
    items: list[tuple[int, int, str, _QueuedRequest]],
) -> list[tuple[int, int, str, _QueuedRequest]]:
    """Drop superseded copies of a URL, keeping the best-priority one.

    ``items`` must already be sorted, so the first copy of each URL is the one
    with the lowest ``(priority, sequence)``. Promotion re-queues a URL rather
    than mutating the existing entry, so duplicates are expected here.
    """
    selected: Dict[str, tuple[int, int, str, _QueuedRequest]] = {}
    for item in items:
        previous = selected.get(item[2])
        if previous is None:
            selected[item[2]] = item
            continue
        merged = _merge_queued_request(previous[3], item[3])
        selected[item[2]] = (merged.priority, min(previous[1], item[1]), item[2], merged)
    return sorted(selected.values())


def _drain_queued_items(
    first: tuple[int, int, str, _QueuedRequest],
) -> list[tuple[int, int, str, _QueuedRequest]]:
    """Collect ``first`` plus any items currently queued (holds ``_queue_lock``)."""
    pending = [first]
    with _queue_lock:
        while True:
            try:
                pending.append(_url_queue.get_nowait())
            except queue.Empty:
                break
    pending.sort()
    return _dedupe_sorted(pending)


def _worker_loop() -> None:
    while True:
        first = _url_queue.get()
        _worker_idle.clear()
        pending = _drain_queued_items(first)
        workers = max(1, _FETCH_WORKERS)
        try:
            # One pool for the whole batch: a fresh executor per chunk spawned
            # ~N threads to fetch N URLs.
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="uvr-stem-yaml"
            ) as pool:
                while pending:
                    chunk = pending[:workers]
                    pending = pending[workers:]
                    with _queue_lock:
                        active_chunk = [
                            item for item in chunk if _queued_requests.get(item[2]) == item[3]
                        ]
                    futures = {
                        pool.submit(
                            _fetch_and_remember,
                            item[2],
                            force=item[3].force,
                            policy=item[3].policy,
                        ): (item[2], item[3])
                        for item in active_chunk
                    }
                    successes = 0
                    failures = 0
                    for future in as_completed(futures):
                        url, request = futures[future]
                        try:
                            if future.result():
                                successes += 1
                                log_event(
                                    "cache", "catalogue_stem_validated", level="trace", url=url
                                )
                            else:
                                failures += 1
                        except Exception as exc:
                            failures += 1
                            with access_policy(
                                allow_network=request.policy.allow_network,
                                allow_metadata_writes=request.policy.allow_metadata_writes,
                                allow_cache_writes=request.policy.allow_cache_writes,
                            ):
                                _remember_fetch_failure(
                                    url,
                                    "worker",
                                    f"worker failed: {type(exc).__name__}",
                                )
                    log_event(
                        "cache",
                        "catalogue_stem_batch",
                        urls=len(active_chunk),
                        successes=successes,
                        failures=failures,
                    )
                    with _queue_lock:
                        for _prio, _seq, key, request in active_chunk:
                            # Leave the record in place if the URL was promoted
                            # while this chunk was in flight — the re-queued
                            # copy still has to run.
                            if _queued_requests.get(key) == request:
                                _queued_requests.pop(key, None)
                        newly: list[tuple[int, int, str, _QueuedRequest]] = []
                        while True:
                            try:
                                newly.append(_url_queue.get_nowait())
                            except queue.Empty:
                                break
                    if newly:
                        pending = _dedupe_sorted(sorted(pending + newly))
                    # Per chunk, not per drain: subtitles for prioritized
                    # visible rows must appear without waiting on the whole
                    # catalogue.
                    _notify_subscribers()
        finally:
            with _queue_lock:
                idle = _url_queue.empty() and not _queued_requests
            if idle:
                _worker_idle.set()


def _reset_worker_state_for_tests() -> None:
    """Drain queue / subscribers between unit tests (daemon thread stays)."""
    global _subscribers
    if _worker_thread is not None and _worker_thread.is_alive():
        _worker_idle.wait(timeout=2.0)
    with _subscribers_lock:
        _subscribers = []
    with _queue_lock:
        while True:
            try:
                _url_queue.get_nowait()
            except queue.Empty:
                break
        _queued_requests.clear()
    _worker_idle.set()
