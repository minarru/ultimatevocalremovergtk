"""Remote download size lookup and human-readable formatting."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Dict, Iterable, List, Optional, Tuple

from . import paths
from .debug_log import debug

_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_TIMEOUT_SECONDS = 20


def _cache_path() -> str:
    return paths.migrate_cache_file("download_size_cache.json", paths.DOWNLOAD_SIZE_CACHE_FILE)


def _ssl_context() -> ssl.SSLContext:
    if os.environ.get("UVR_INSECURE_DOWNLOADS") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


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


def _cache_put(url: str, size: Optional[int]) -> None:
    payload = _read_cache()
    payload[url] = {"size": size, "fetched_at": time.time()}
    _write_cache(payload)


def fetch_remote_size(url: str) -> Optional[int]:
    """Return the remote ``Content-Length`` in bytes, or ``None`` if unknown."""
    cached = _cache_get(url)
    if cached is not None:
        return cached

    size = _head_content_length(url)
    if size is None:
        size = _get_content_length(url)
    _cache_put(url, size)
    return size


def prefetch_remote_sizes(urls: Iterable[str]) -> Dict[str, int]:
    """Refresh stale or missing cache entries for ``urls``.

    Entries younger than :data:`_CACHE_TTL_SECONDS` are left untouched.
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
    fetched = 0
    failed = 0
    dirty = False

    for url in unique:
        entry = payload.get(url)
        if _cache_entry_fresh(entry, now=now):
            fresh += 1
            continue
        size = _head_content_length(url)
        if size is None:
            size = _get_content_length(url)
        payload[url] = {"size": size, "fetched_at": now}
        dirty = True
        if size is not None:
            fetched += 1
        else:
            failed += 1

    if dirty:
        _write_cache(payload)

    return {
        "total": len(unique),
        "fresh": fresh,
        "fetched": fetched,
        "failed": failed,
    }


def _head_content_length(url: str) -> Optional[int]:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(
            request, context=_ssl_context(), timeout=_TIMEOUT_SECONDS
        ) as response:
            return _parse_content_length(response.getheader("Content-Length"))
    except Exception:
        return None


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
