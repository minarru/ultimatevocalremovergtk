"""Dependency-injected revisioned remote/local JSON catalogue source store."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Optional

from .access_policy import AccessPolicy
from .catalogue_types import (
    ADAPTER_SCHEMA,
    ENVELOPE_SCHEMA,
    RefreshMode,
    SourceContent,
    SourceId,
    SourceState,
    SourceStatus,
    readonly_mapping,
    semantic_digest,
)
from .debug_log import debug
from .json_store import write_json_atomic

Opener = Callable[[str | urllib.request.Request], Any]
EnabledFn = Callable[[], bool]
FallbackFn = Callable[[], Mapping[str, Any] | None]
ClockFn = Callable[[], float]
NormalizeFn = Callable[[Any], Mapping[str, Any]]

_DEFAULT_TTL_SECONDS = 24 * 60 * 60
_MAX_BACKOFF_SECONDS = 15 * 60
_INITIAL_BACKOFF_SECONDS = 15.0


def inspect_cache_path(filename: str, dest_path: str) -> str:
    """Return dest or a legacy location without creating, moving, or copying."""
    from . import paths

    if os.path.isfile(dest_path):
        return dest_path
    candidates = []
    legacy_data = os.path.join(paths.DATA_DIR, filename)
    if legacy_data != dest_path:
        candidates.append(legacy_data)
    legacy_base = os.path.join(paths.BASE_PATH, filename)
    if legacy_base != dest_path and legacy_base != legacy_data:
        candidates.append(legacy_base)
    for src in candidates:
        if os.path.isfile(src):
            return src
    return dest_path


def _is_mapping(value: object) -> bool:
    return isinstance(value, dict)


def _identity_normalize(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return payload


class RemoteJsonSource:
    """One remote or local JSON catalogue with memory, disk, and SWR state."""

    def __init__(
        self,
        *,
        source_id: SourceId,
        url: str | None = None,
        cache_filename: str | None = None,
        cache_path: str | Callable[[], str] | None = None,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        adapter_schema: int = ADAPTER_SCHEMA,
        opener: Opener | None = None,
        enabled: EnabledFn | None = None,
        bundled_fallback: FallbackFn | None = None,
        normalize: NormalizeFn | None = None,
        clock: ClockFn | None = None,
        local_loader: Callable[[], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self.source_id = source_id
        self.url = url
        self.cache_filename = cache_filename
        self._cache_path = cache_path
        self.ttl_seconds = float(ttl_seconds)
        self.adapter_schema = int(adapter_schema)
        self._opener = opener
        self._enabled = enabled
        self._bundled_fallback = bundled_fallback
        self._normalize = normalize or _identity_normalize
        self._clock = clock or time.time
        self._local_loader = local_loader
        self._lock = threading.RLock()
        self._state = SourceState()
        self._flight: threading.Event | None = None
        self._flight_force = False
        self._closed = False
        self._on_update: Callable[[], None] | None = None

    def close(self) -> None:
        self._closed = True
        with self._lock:
            inflight = self._flight
        if inflight is not None:
            inflight.wait(timeout=2)

    def reset(self) -> None:
        with self._lock:
            self._state = SourceState()
            self._flight = None
            self._flight_force = False

    @property
    def state(self) -> SourceState:
        with self._lock:
            return SourceState(
                content=self._state.content,
                status=SourceStatus(
                    checked_at=self._state.status.checked_at,
                    last_success_at=self._state.status.last_success_at,
                    error=self._state.status.error,
                    backoff_until=self._state.status.backoff_until,
                    failures=self._state.status.failures,
                    etag=self._state.status.etag,
                    last_modified=self._state.status.last_modified,
                ),
            )

    def enabled(self) -> bool:
        if self._enabled is None:
            return True
        return bool(self._enabled())

    def _now(self) -> float:
        return float(self._clock())

    def _resolved_cache_path(self) -> str | None:
        path = self._cache_path
        if callable(path):
            return str(path())
        return path

    def _cache_file(self, policy: AccessPolicy) -> str | None:
        dest = self._resolved_cache_path()
        if not dest:
            return None
        filename = self.cache_filename or os.path.basename(dest)
        if policy.allow_metadata_writes:
            from . import paths

            return paths.migrate_cache_file(filename, dest)
        return inspect_cache_path(filename, dest)

    def _stale(self, fetched_at: float, now: float) -> bool:
        if fetched_at <= 0:
            return True
        return (now - fetched_at) >= self.ttl_seconds

    def _in_backoff(self, now: float) -> bool:
        return self._state.status.backoff_until > now

    def load(
        self,
        *,
        mode: RefreshMode = RefreshMode.STALE_WHILE_REVALIDATE,
        policy: AccessPolicy,
    ) -> SourceState:
        if self._closed:
            return self.state
        if not self.enabled():
            return SourceState()
        now = self._now()
        with self._lock:
            memory = self._state.content
            if mode != RefreshMode.FORCE and memory is not None:
                stale = self._stale(memory.fetched_at, now)
                snapshot = self.state
                if stale and mode is RefreshMode.STALE_WHILE_REVALIDATE:
                    self._schedule_refresh(policy)
                return snapshot

        if self._local_loader is not None and mode != RefreshMode.FORCE:
            local = self._read_local(now)
            if local is not None:
                return local

        if mode != RefreshMode.FORCE:
            disk = self._read_disk(policy, now)
            if disk is not None:
                stale = self._stale(disk.fetched_at, now)
                snapshot = self.state
                if stale and mode is RefreshMode.STALE_WHILE_REVALIDATE:
                    self._schedule_refresh(policy)
                return snapshot

        if mode is RefreshMode.OFFLINE or not policy.allow_network:
            fallback = self._load_bundled(now)
            return fallback if fallback is not None else self.state

        if mode is RefreshMode.FORCE:
            return self._force_fetch(policy)
        self._schedule_refresh(policy)
        if self._state.content is None:
            fallback = self._load_bundled(now)
            if fallback is not None:
                return fallback
        return self.state

    def _read_local(self, now: float) -> SourceState | None:
        if self._local_loader is None:
            return None
        try:
            payload = self._local_loader()
        except Exception as exc:
            debug("download", f"{self.source_id.value} local load failed err={exc}")
            return None
        if not isinstance(payload, dict) or not payload:
            return None
        content = self._content_from_payload(payload, fetched_at=now, etag=None, last_modified=None)
        with self._lock:
            self._publish_content(content, now, from_network=False)
        return self.state

    def _read_disk(self, policy: AccessPolicy, now: float) -> SourceContent | None:
        path = self._cache_file(policy)
        if not path or not os.path.isfile(path):
            return None
        envelope = _read_envelope(path)
        if envelope is None:
            return None
        content = self._content_from_envelope(envelope)
        if content is None:
            return None
        with self._lock:
            previous = self._state.content
            self._publish_content(content, now, from_network=False)
            if previous is None or previous.semantic_digest != content.semantic_digest:
                debug(
                    "download",
                    f"{self.source_id.value} disk load digest={content.semantic_digest[:12]}",
                )
        return content

    def _load_bundled(self, now: float) -> SourceState | None:
        if self._bundled_fallback is None:
            return None
        try:
            payload = self._bundled_fallback()
        except Exception:
            return None
        if not isinstance(payload, dict) or not payload:
            return None
        content = self._content_from_payload(
            payload, fetched_at=0.0, etag=None, last_modified=None
        )
        with self._lock:
            if self._state.content is None:
                self._publish_content(content, now, from_network=False)
        return self.state

    def _schedule_refresh(self, policy: AccessPolicy) -> None:
        if self._closed or not policy.allow_network or self.url is None:
            return
        now = self._now()
        if self._in_backoff(now):
            return
        with self._lock:
            if self._flight is not None:
                return
            event = threading.Event()
            self._flight = event
            self._flight_force = False

        captured = AccessPolicy(
            allow_network=policy.allow_network,
            allow_metadata_writes=policy.allow_metadata_writes,
        )

        def run() -> None:
            try:
                self._fetch(captured, force=False)
                self._notify_update()
            except Exception as exc:
                debug(
                    "download",
                    f"{self.source_id.value} background refresh failed err={exc}",
                )
            finally:
                event.set()
                with self._lock:
                    if self._flight is event:
                        self._flight = None
                        self._flight_force = False

        threading.Thread(
            target=run, name=f"uvr-catalogue-{self.source_id.value}", daemon=True
        ).start()

    def _force_fetch(self, policy: AccessPolicy) -> SourceState:
        if self.url is None:
            if self._local_loader is not None:
                loaded = self._read_local(self._now())
                return loaded if loaded is not None else self.state
            fallback = self._load_bundled(self._now())
            return fallback if fallback is not None else self.state
        owner = False
        with self._lock:
            inflight = self._flight
            wait_for_force = self._flight_force
            if inflight is None:
                inflight = threading.Event()
                self._flight = inflight
                self._flight_force = True
                owner = True
        if not owner:
            inflight.wait(timeout=120)
            if not wait_for_force and not self._closed:
                # A narrower SWR finished; FORCE still needs an unconditional fetch.
                return self._force_fetch(policy)
            return self.state
        try:
            self._fetch(policy, force=True)
        finally:
            inflight.set()
            with self._lock:
                if self._flight is inflight:
                    self._flight = None
                    self._flight_force = False
        return self.state

    def _fetch(self, policy: AccessPolicy, *, force: bool) -> SourceState:
        if self._closed or not policy.allow_network or self.url is None:
            return self.state
        if self._opener is None:
            return self.state
        now = self._now()
        if not force and self._in_backoff(now):
            return self.state
        previous = self._state.content
        validators = (
            (None, None)
            if previous is None
            else (previous.etag, previous.last_modified)
        )
        payload, etag, last_modified, not_modified = self._http_get(
            validators[0], validators[1]
        )
        if not_modified:
            if previous is None:
                payload, etag, last_modified, not_modified = self._http_get(None, None)
            else:
                refreshed = SourceContent(
                    source_id=previous.source_id,
                    payload=previous.payload,
                    semantic_digest=previous.semantic_digest,
                    adapter_schema=previous.adapter_schema,
                    fetched_at=now,
                    etag=previous.etag,
                    last_modified=previous.last_modified,
                )
                with self._lock:
                    self._publish_content(refreshed, now, from_network=True)
                return self.state
        if payload is None:
            self._mark_failure(now, "fetch failed")
            if self._state.content is None:
                # FORCE with an empty memory cache must still surface last-good
                # disk content; do not stamp fetched_at.
                disk_policy = AccessPolicy(
                    allow_network=False,
                    allow_metadata_writes=False,
                )
                self._read_disk(disk_policy, now)
            return self.state
        try:
            content = self._content_from_payload(
                payload, fetched_at=now, etag=etag, last_modified=last_modified
            )
        except Exception as exc:
            debug("download", f"{self.source_id.value} convert failed err={exc}")
            self._mark_failure(now, f"convert failed: {exc}")
            return self.state
        with self._lock:
            self._publish_content(content, now, from_network=True)
        if policy.allow_metadata_writes:
            self._write_disk(content, policy)
        return self.state

    def _http_get(
        self, etag: str | None, last_modified: str | None
    ) -> tuple[Mapping[str, Any] | None, str | None, str | None, bool]:
        if self._opener is None or self.url is None:
            return None, None, None, False
        request: str | urllib.request.Request = self.url
        if etag or last_modified:
            request = urllib.request.Request(self.url)
            if etag:
                request.add_header("If-None-Match", etag)
            if last_modified:
                request.add_header("If-Modified-Since", last_modified)
        try:
            with self._opener(request) as response:
                status = int(getattr(response, "status", 200) or 200)
                if status == 304:
                    return None, etag, last_modified, True
                data = json.load(response)
                headers = getattr(response, "headers", None)
                new_etag = _header(headers, "ETag") or etag
                new_modified = _header(headers, "Last-Modified") or last_modified
        except urllib.error.HTTPError as exc:
            try:
                if exc.code == 304:
                    return None, etag, last_modified, True
                debug(
                    "download",
                    f"{self.source_id.value} http {exc.code}",
                )
                return None, None, None, False
            finally:
                exc.close()
        except Exception as exc:
            debug(
                "download",
                f"{self.source_id.value} fetch failed err={type(exc).__name__}: {exc}",
            )
            return None, None, None, False
        if not _is_mapping(data):
            return None, None, None, False
        return data, new_etag, new_modified, False

    def _content_from_envelope(self, envelope: Mapping[str, Any]) -> SourceContent | None:
        raw = envelope.get("data")
        if not isinstance(raw, dict):
            return None
        fetched_at = envelope.get("fetched_at")
        if not isinstance(fetched_at, (int, float)):
            return None
        etag = envelope.get("etag")
        last_modified = envelope.get("last_modified")
        return self._content_from_payload(
            raw,
            fetched_at=float(fetched_at),
            etag=str(etag) if isinstance(etag, str) else None,
            last_modified=str(last_modified) if isinstance(last_modified, str) else None,
        )

    def _content_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        fetched_at: float,
        etag: str | None,
        last_modified: str | None,
    ) -> SourceContent:
        normalized = dict(self._normalize(payload))
        digest = semantic_digest(normalized, adapter_schema=self.adapter_schema)
        return SourceContent(
            source_id=self.source_id,
            payload=readonly_mapping(normalized),
            semantic_digest=digest,
            adapter_schema=self.adapter_schema,
            fetched_at=fetched_at,
            etag=etag,
            last_modified=last_modified,
        )

    def _publish_content(
        self, content: SourceContent, now: float, *, from_network: bool
    ) -> None:
        previous = self._state.content
        if (
            previous is not None
            and previous.semantic_digest == content.semantic_digest
            and not from_network
        ):
            # Disk/memory reload of identical bytes: keep the authoritative
            # fetched_at from content, never stamp "now".
            self._state.content = content
        elif previous is not None and previous.semantic_digest == content.semantic_digest:
            self._state.content = SourceContent(
                source_id=content.source_id,
                payload=content.payload,
                semantic_digest=previous.semantic_digest,
                adapter_schema=previous.adapter_schema,
                fetched_at=content.fetched_at if from_network else previous.fetched_at,
                etag=content.etag or previous.etag,
                last_modified=content.last_modified or previous.last_modified,
            )
        else:
            self._state.content = content
        self._state.status.checked_at = now
        self._state.status.last_success_at = now if from_network else (
            self._state.status.last_success_at
        )
        self._state.status.error = None
        self._state.status.failures = 0
        self._state.status.backoff_until = 0.0
        self._state.status.etag = content.etag
        self._state.status.last_modified = content.last_modified

    def _notify_update(self) -> None:
        callback = self._on_update
        if callback is None or self._closed:
            return
        try:
            callback()
        except Exception as exc:
            debug(
                "download",
                f"{self.source_id.value} update callback failed err={exc}",
            )

    def _mark_failure(self, now: float, message: str) -> None:
        with self._lock:
            status = self._state.status
            status.checked_at = now
            status.error = message
            status.failures += 1
            delay = min(
                _MAX_BACKOFF_SECONDS,
                _INITIAL_BACKOFF_SECONDS * (2 ** max(0, status.failures - 1)),
            )
            status.backoff_until = now + delay

    def _write_disk(self, content: SourceContent, policy: AccessPolicy) -> None:
        if not policy.allow_metadata_writes or not self._cache_path:
            return
        path = self._cache_file(policy)
        if not path:
            return
        envelope = {
            "schema": ENVELOPE_SCHEMA,
            "source": self.source_id.value,
            "adapter_schema": self.adapter_schema,
            "fetched_at": content.fetched_at,
            "semantic_digest": content.semantic_digest,
            "data": dict(content.payload),
        }
        if content.etag:
            envelope["etag"] = content.etag
        if content.last_modified:
            envelope["last_modified"] = content.last_modified
        try:
            write_json_atomic(path, envelope)
        except OSError as exc:
            debug("download", f"{self.source_id.value} cache write failed err={exc}")


def _header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    get = getattr(headers, "get", None)
    if not callable(get):
        return None
    value = get(name)
    return str(value) if value else None


def _read_envelope(path: str) -> Optional[dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("data"), dict):
        return payload
    # Bare catalogue JSON (bundled-style) is treated as data with unknown age.
    return {"fetched_at": 0.0, "data": payload}


def copy_without_write(src: str, dest: str) -> None:
    """Unused helper kept for tests that patch shutil copy/move."""
    shutil.copy2(src, dest)


__all__ = ["RemoteJsonSource", "inspect_cache_path"]
