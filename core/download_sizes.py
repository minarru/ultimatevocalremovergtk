"""Remote download size lookup and human-readable formatting."""

from __future__ import annotations

import atexit
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import paths
from .access_policy import current_access_policy
from .catalog_dedupe import normalize_checkpoint_url
from .debug_log import debug
from .json_store import write_json_atomic

_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_TIMEOUT_SECONDS = 20
_IDENTITY_HEAD_CAP = 64
_DEFAULT_HEAD_WORKERS = 8

#: Stops the HEAD wave loops below from submitting any more work.
#:
#: ``ThreadPoolExecutor`` joins its (non-daemon) workers at interpreter exit
#: *after* everything already submitted has run, so submitting the whole stale
#: backlog up front made quitting block on hundreds of requests at
#: ``_TIMEOUT_SECONDS`` each. What bounds that wait is submitting in waves of
#: ``workers``: the exit join can only ever wait on the wave in flight.
#:
#: This flag is the *cooperative* half, for an explicit in-app shutdown. It
#: cannot help at interpreter exit — ``concurrent.futures.thread`` registers
#: its hook with ``threading._register_atexit``, which runs before plain
#: ``atexit`` handlers — so the wave loops also treat a ``RuntimeError`` from
#: ``submit`` ("cannot schedule new futures after interpreter shutdown") as a
#: stop signal rather than letting it escape a background thread.
_shutdown = threading.Event()
_memory_lock = threading.RLock()
_memory_payload: Optional[Dict[str, object]] = None
_memory_path: Optional[str] = None
_size_inflight: Dict[str, List[Callable[[str, Optional[int]], None]]] = {}
_size_inflight_lock = threading.Lock()


def request_shutdown() -> None:
    """Stop submitting further HEAD waves (idempotent)."""
    _shutdown.set()


atexit.register(request_shutdown)


def _submit_wave(
    pool: ThreadPoolExecutor, wave: List[str]
) -> Optional[Dict["Future[Tuple[Optional[int], Optional[str], Optional[str]]]", str]]:
    """Submit one wave, or ``None`` once no more work can be scheduled."""
    try:
        return {pool.submit(_fetch_size_meta, url): url for url in wave}
    except RuntimeError:
        return None


def _cache_path() -> str:
    return paths.migrate_cache_file("download_size_cache.json", paths.DOWNLOAD_SIZE_CACHE_FILE)


def _ssl_context() -> ssl.SSLContext:
    if os.environ.get("UVR_INSECURE_DOWNLOADS") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _head_workers() -> int:
    raw = os.environ.get("UVR_SIZE_HEAD_WORKERS", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return _DEFAULT_HEAD_WORKERS


def format_download_size(num_bytes: Optional[int]) -> str:
    """Format a byte count for UI labels (e.g. ``245 MB``, ``1.2 GB``)."""
    if num_bytes is None or num_bytes < 0:
        return "unknown"
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}".replace(".0 ", " ")
        value /= 1024.0
    return f"{value:.1f} TB"


def _read_cache_from_disk(path: str) -> Dict[str, object]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _read_cache() -> Dict[str, object]:
    global _memory_payload, _memory_path
    path = _cache_path()
    with _memory_lock:
        if _memory_payload is None or _memory_path != path:
            _memory_payload = _read_cache_from_disk(path)
            _memory_path = path
        return _memory_payload


def _write_cache(payload: Dict[str, object]) -> None:
    global _memory_payload, _memory_path
    path = _cache_path()
    with _memory_lock:
        _memory_payload = payload
        _memory_path = path
        if not current_access_policy().allow_metadata_writes:
            return
        try:
            write_json_atomic(path, payload)
        except OSError as exc:
            debug("download", f"size cache write failed err={exc}")


def _cache_entry_fresh(entry: object, *, now: Optional[float] = None) -> bool:
    if not isinstance(entry, dict):
        return False
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return False
    if now is None:
        now = time.time()
    return (now - float(fetched_at)) <= _CACHE_TTL_SECONDS


def _cache_get(url: str) -> Optional[int]:
    entry = _read_cache().get(url)
    if not _cache_entry_fresh(entry):
        # Also try the normalized key — catalogue URLs often carry ?download=true.
        norm = normalize_checkpoint_url(url)
        if norm != url:
            entry = _read_cache().get(norm)
            if not _cache_entry_fresh(entry):
                return None
        else:
            return None
    if not isinstance(entry, dict):
        return None
    size = entry.get("size")
    if size is None:
        return None
    try:
        return int(size)
    except (TypeError, ValueError):
        return None


def _store_entry(
    payload: Dict[str, object],
    url: str,
    *,
    size: Optional[int],
    etag: Optional[str],
    now: float,
    content_id: Optional[str] = None,
) -> None:
    key = normalize_checkpoint_url(url) or url
    stored: Dict[str, object] = {"size": size, "fetched_at": now}
    if etag:
        stored["etag"] = etag
    if content_id:
        stored["content_id"] = content_id
    payload[key] = stored
    if key != url:
        payload[url] = dict(stored)


def _cache_put(
    url: str,
    size: Optional[int],
    etag: Optional[str] = None,
    content_id: Optional[str] = None,
) -> None:
    payload = _read_cache()
    _store_entry(
        payload, url, size=size, etag=etag, now=time.time(), content_id=content_id
    )
    _write_cache(payload)


def _fetch_size_meta(url: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    size, validator, content_id = _unpack_head_meta(_head_remote_meta(url))
    if size is None:
        size = _get_content_length(url)
    return size, validator, content_id


def _unpack_head_meta(
    meta: Tuple[Optional[int], Optional[str]] | Tuple[Optional[int], Optional[str], Optional[str]],
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    if len(meta) >= 3:
        return meta[0], meta[1], meta[2]
    return meta[0], meta[1], None


def fetch_remote_size(url: str) -> Optional[int]:
    """Return the remote ``Content-Length`` in bytes, or ``None`` if unknown."""
    cached = _cache_get(url)
    if cached is not None:
        return cached
    if not current_access_policy().allow_network:
        return None

    size, etag, content_id = _fetch_size_meta(url)
    _cache_put(url, size, etag, content_id)
    return size


def request_url_size(
    url: str, callback: Callable[[str, Optional[int]], None]
) -> None:
    """Coalesce HEAD lookups for ``url``; invoke ``callback`` when known.

    Duplicate callers share one in-flight fetch. Cached hits invoke the
    callback synchronously.
    """
    cached = _cache_get(url)
    if cached is not None:
        callback(url, cached)
        return
    with _size_inflight_lock:
        waiters = _size_inflight.get(url)
        if waiters is not None:
            waiters.append(callback)
            return
        _size_inflight[url] = [callback]

    def run() -> None:
        size = fetch_remote_size(url) if not _shutdown.is_set() else None
        with _size_inflight_lock:
            cbs = _size_inflight.pop(url, [])
        for waiter in cbs:
            try:
                waiter(url, size)
            except Exception:
                debug("download", "size lookup waiter raised")

    threading.Thread(target=run, name="uvr-size-lookup", daemon=True).start()


def prefetch_remote_sizes(urls: Iterable[str]) -> Dict[str, int]:
    """Refresh stale or missing cache entries for ``urls``.

    Entries younger than :data:`_CACHE_TTL_SECONDS` are left untouched, even
    when they lack an etag (avoids a wholesale HEAD storm after upgrades).
    Returns counts ``{total, fresh, fetched, failed}``.
    """
    unique: List[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(url)

    if not unique:
        return {"total": 0, "fresh": 0, "fetched": 0, "failed": 0}

    payload = _read_cache()
    now = time.time()
    fresh = 0
    to_fetch: List[str] = []

    for url in unique:
        key = normalize_checkpoint_url(url) or url
        entry = payload.get(key)
        if entry is None and key != url:
            entry = payload.get(url)
        if _cache_entry_fresh(entry, now=now):
            fresh += 1
            continue
        to_fetch.append(url)

    fetched = 0
    failed = 0
    if to_fetch:
        workers = min(_head_workers(), len(to_fetch))
        remaining = list(to_fetch)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while remaining and not _shutdown.is_set():
                wave, remaining = remaining[:workers], remaining[workers:]
                futures = _submit_wave(pool, wave)
                if futures is None:
                    break
                for future in as_completed(futures):
                    url = futures[future]
                    try:
                        size, etag, content_id = _unpack_head_meta(future.result())
                    except Exception:
                        size, etag, content_id = None, None, None
                    _store_entry(
                        payload,
                        url,
                        size=size,
                        etag=etag,
                        now=now,
                        content_id=content_id,
                    )
                    if size is not None:
                        fetched += 1
                    else:
                        failed += 1
        _write_cache(payload)

    return {
        "total": len(unique),
        "fresh": fresh,
        "fetched": fetched,
        "failed": failed,
    }


def content_ids_from_cache(urls: Iterable[str]) -> Dict[str, str]:
    """Map normalized checkpoint URLs to trusted content identities.

    Ordinary/weak HTTP ETags and Last-Modified are validators only and never
    cross-URL-dedupe. Hugging Face ``X-Linked-Etag`` values are stored as
    ``content_id`` and are the only ids returned here.
    """
    return trusted_content_ids_from_cache(urls)


def trusted_content_ids_from_cache(urls: Iterable[str]) -> Dict[str, str]:
    payload = _read_cache()
    out: Dict[str, str] = {}
    for url in urls:
        if not url:
            continue
        key = normalize_checkpoint_url(url) or url
        entry = payload.get(key)
        if not isinstance(entry, dict):
            entry = payload.get(url)
        if not isinstance(entry, dict):
            continue
        content_id = entry.get("content_id")
        if isinstance(content_id, str) and content_id:
            out[key] = content_id
    return out


def prefetch_same_size_identity(urls: Iterable[str]) -> Dict[str, int]:
    """HEAD only checkpoint URLs that share a cached size and lack an etag.

    Catches rehosts (same bytes, different URL/basename) without refetching the
    whole catalogue. At most :data:`_IDENTITY_HEAD_CAP` URLs are HEADed per call.
    Returns ``{total, fetched, failed, skipped}``.
    """
    unique: List[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(url)

    payload = _read_cache()
    now = time.time()
    by_size: Dict[int, List[str]] = defaultdict(list)
    fetched_at_by_url: Dict[str, float] = {}
    for url in unique:
        key = normalize_checkpoint_url(url) or url
        entry = payload.get(key)
        if not isinstance(entry, dict):
            entry = payload.get(url)
        if not _cache_entry_fresh(entry, now=now) or not isinstance(entry, dict):
            continue
        size = entry.get("size")
        if not isinstance(size, int) or size <= 0:
            continue
        content_id = entry.get("content_id")
        if isinstance(content_id, str) and content_id:
            continue
        stamp = entry.get("fetched_at")
        fetched_at_by_url[url] = float(stamp) if isinstance(stamp, (int, float)) else 0.0
        by_size[size].append(url)

    # Oldest first, not alphabetical: a URL whose host never returns an ETag
    # stays in the cohort forever, and ordering by URL would let the same
    # early-sorting few block the tail on every pass. A HEAD refreshes
    # fetched_at even when no etag comes back, so tried URLs rotate to the
    # back and the window advances by itself.
    candidates = [url for cohort in by_size.values() if len(cohort) > 1 for url in cohort]
    candidates.sort(key=lambda url: (fetched_at_by_url.get(url, 0.0), url))
    capped = len(candidates) > _IDENTITY_HEAD_CAP
    targets = candidates[:_IDENTITY_HEAD_CAP] if capped else candidates
    if not targets:
        return {
            "total": 0,
            "fetched": 0,
            "failed": 0,
            "skipped": len(unique),
            "capped": 0,
        }

    fetched = 0
    failed = 0
    workers = min(_head_workers(), len(targets))
    remaining = list(targets)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while remaining and not _shutdown.is_set():
            wave, remaining = remaining[:workers], remaining[workers:]
            futures = _submit_wave(pool, wave)
            if futures is None:
                break
            for future in as_completed(futures):
                url = futures[future]
                try:
                    size, etag, content_id = _unpack_head_meta(future.result())
                except Exception:
                    size, etag, content_id = None, None, None
                _store_entry(
                    payload,
                    url,
                    size=size,
                    etag=etag,
                    now=now,
                    content_id=content_id,
                )
                if content_id or etag:
                    fetched += 1
                else:
                    failed += 1
    _write_cache(payload)

    debug(
        "download",
        f"size_cache identity pass targets={len(targets)} "
        f"fetched={fetched} failed={failed}",
    )
    return {
        "total": len(targets),
        "fetched": fetched,
        "failed": failed,
        "skipped": len(unique) - len(targets),
        # Non-zero when candidates outran the cap, so the caller knows another
        # pass still has work to do rather than marking the warmup complete.
        "capped": len(candidates) - len(targets),
    }


def _head_remote_meta(
    url: str,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Return ``(content_length, validator, content_id)`` from a HEAD request.

    ``content_id`` is set only for Hugging Face ``X-Linked-Etag``. Ordinary
    and weak ETags remain URL-scoped validators.
    """
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(
            request, context=_ssl_context(), timeout=_TIMEOUT_SECONDS
        ) as response:
            size = _parse_content_length(
                response.getheader("X-Linked-Size")
                or response.getheader("Content-Length")
            )
            linked = response.getheader("X-Linked-Etag")
            raw_etag = response.getheader("ETag")
            validator = _parse_etag(raw_etag) or (str(raw_etag).strip() if raw_etag else None)
            content_id = _parse_etag(linked) if linked else None
            if content_id and str(linked).strip().startswith("W/"):
                content_id = None
            return size, validator, content_id
    except Exception:
        return None, None, None


def _head_content_length(url: str) -> Optional[int]:
    size, _validator, _content_id = _unpack_head_meta(_head_remote_meta(url))
    return size


def _get_content_length(url: str) -> Optional[int]:
    try:
        with urllib.request.urlopen(
            url, context=_ssl_context(), timeout=_TIMEOUT_SECONDS
        ) as response:
            return _parse_content_length(response.getheader("Content-Length"))
    except Exception:
        return None


def _parse_content_length(header: Optional[str]) -> Optional[int]:
    if not header or not str(header).isdigit():
        return None
    return int(header)


def _parse_etag(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    text = str(header).strip()
    if text.startswith("W/"):
        text = text[2:].strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    return text or None


def estimate_jobs_size(
    jobs: List[Tuple[str, str]],
) -> Tuple[Optional[int], int, int]:
    """Return ``(total_bytes, files_count, known_count)`` for pending ``jobs``."""
    pending = [(url, path) for url, path in jobs if not os.path.isfile(path)]
    if not pending:
        return 0, 0, 0

    total = 0
    known = 0
    for url, _path in pending:
        size = fetch_remote_size(url)
        if size is not None:
            total += size
            known += 1
    if known == 0:
        return None, len(pending), 0
    if known < len(pending):
        return total, len(pending), known
    return total, len(pending), known


def describe_download_size(
    jobs: List[Tuple[str, str]],
) -> str:
    """Build a short UI label for the pending download size."""
    pending = [(url, path) for url, path in jobs if not os.path.isfile(path)]
    if not pending:
        return "Already downloaded"

    total, _file_count, known = estimate_jobs_size(pending)

    if total is None:
        return "Size unknown"
    if known < len(pending):
        return f"At least {format_download_size(total)}"
    return format_download_size(total)


def describe_cached_download_size(jobs: List[Tuple[str, str]]) -> str:
    """Size label from the in-memory cache only — no HEAD or writes."""
    pending = [(url, path) for url, path in jobs if not os.path.isfile(path)]
    if not pending:
        return "Already downloaded"
    total = 0
    known = 0
    for url, _path in pending:
        size = _cache_get(url)
        if size is not None:
            total += size
            known += 1
    if known == 0:
        return "Size unknown"
    if known < len(pending):
        return f"At least {format_download_size(total)}"
    return format_download_size(total)
