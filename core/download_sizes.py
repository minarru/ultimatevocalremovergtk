"""Remote download size lookup and human-readable formatting."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Iterable, List, Optional, Tuple

from . import paths
from .catalog_dedupe import normalize_checkpoint_url
from .debug_log import debug

_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_TIMEOUT_SECONDS = 20
_IDENTITY_HEAD_CAP = 64
_DEFAULT_HEAD_WORKERS = 8


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


def _read_cache() -> Dict[str, object]:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _write_cache(payload: Dict[str, object]) -> None:
    try:
        cache_path = _cache_path()
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
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
) -> None:
    key = normalize_checkpoint_url(url) or url
    stored: Dict[str, object] = {"size": size, "fetched_at": now}
    if etag:
        stored["etag"] = etag
    payload[key] = stored
    if key != url:
        payload[url] = dict(stored)


def _cache_put(url: str, size: Optional[int], etag: Optional[str] = None) -> None:
    payload = _read_cache()
    _store_entry(payload, url, size=size, etag=etag, now=time.time())
    _write_cache(payload)


def _fetch_size_meta(url: str) -> Tuple[Optional[int], Optional[str]]:
    size, etag = _head_remote_meta(url)
    if size is None:
        size = _get_content_length(url)
    return size, etag


def fetch_remote_size(url: str) -> Optional[int]:
    """Return the remote ``Content-Length`` in bytes, or ``None`` if unknown."""
    cached = _cache_get(url)
    if cached is not None:
        return cached

    size, etag = _fetch_size_meta(url)
    _cache_put(url, size, etag)
    return size


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
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch_size_meta, url): url for url in to_fetch}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    size, etag = future.result()
                except Exception:
                    size, etag = None, None
                _store_entry(payload, url, size=size, etag=etag, now=now)
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
    """Map normalized checkpoint URLs to cached content ids (etags)."""
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
        etag = entry.get("etag")
        if isinstance(etag, str) and etag:
            out[key] = etag
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
    for url in unique:
        key = normalize_checkpoint_url(url) or url
        entry = payload.get(key)
        if not isinstance(entry, dict):
            entry = payload.get(url)
        if not _cache_entry_fresh(entry, now=now) or not isinstance(entry, dict):
            continue
        size = entry.get("size")
        etag = entry.get("etag")
        if not isinstance(size, int) or size <= 0:
            continue
        if isinstance(etag, str) and etag:
            continue
        by_size[size].append(url)

    targets = sorted(
        url for cohort in by_size.values() if len(cohort) > 1 for url in cohort
    )
    if len(targets) > _IDENTITY_HEAD_CAP:
        targets = targets[:_IDENTITY_HEAD_CAP]
    if not targets:
        return {"total": 0, "fetched": 0, "failed": 0, "skipped": len(unique)}

    fetched = 0
    failed = 0
    workers = min(_head_workers(), len(targets))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_size_meta, url): url for url in targets}
        for future in as_completed(futures):
            url = futures[future]
            try:
                size, etag = future.result()
            except Exception:
                size, etag = None, None
            _store_entry(payload, url, size=size, etag=etag, now=now)
            if etag:
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
    }


def _head_remote_meta(url: str) -> Tuple[Optional[int], Optional[str]]:
    """Return ``(content_length, etag)`` from a HEAD request."""
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(
            request, context=_ssl_context(), timeout=_TIMEOUT_SECONDS
        ) as response:
            size = _parse_content_length(
                response.getheader("X-Linked-Size")
                or response.getheader("Content-Length")
            )
            etag = _parse_etag(
                response.getheader("X-Linked-Etag") or response.getheader("ETag")
            )
            return size, etag
    except Exception:
        return None, None


def _head_content_length(url: str) -> Optional[int]:
    size, _etag = _head_remote_meta(url)
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
