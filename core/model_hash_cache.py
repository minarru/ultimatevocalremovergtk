"""Trusted path→hash entries for dry model checks across sessions."""

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional, TypedDict

StatFn = Callable[[str], os.stat_result]

#: Guards mutation of ``settings.process.model_hash_table`` so a worker-thread
#: :func:`remember` call can't race with :func:`snapshot_table` copying the
#: same dict for JSON serialization on the main thread (dataclasses.asdict
#: iterates the live dict; a size change mid-iteration raises RuntimeError).
_TABLE_LOCK = threading.Lock()


class HashEntry(TypedDict):
    hash: str
    mtime_ns: int
    size: int


def _coerce_stat_field(value: Any, *, default: int) -> Optional[int]:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _as_entry(value: Any) -> Optional[HashEntry]:
    if isinstance(value, Mapping) and "hash" in value:
        digest = value.get("hash")
        if isinstance(digest, str) and digest:
            mtime_ns = _coerce_stat_field(value.get("mtime_ns"), default=0)
            if mtime_ns is None:
                return None
            size = _coerce_stat_field(value.get("size"), default=-1)
            if size is None:
                return None
            return HashEntry(hash=digest, mtime_ns=mtime_ns, size=size)
    return None


def lookup_trusted(
    table: Mapping[str, Any],
    path: str,
    *,
    stat: StatFn = os.stat,
) -> Optional[str]:
    raw = table.get(path)
    entry = _as_entry(raw)
    if entry is None:
        return None
    try:
        st = stat(path)
    except OSError:
        return None
    if st.st_mtime_ns != entry["mtime_ns"] or st.st_size != entry["size"]:
        return None
    return entry["hash"]


def flatten_trusted(
    table: Mapping[str, Any],
    *,
    stat: StatFn = os.stat,
) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for path in table:
        digest = lookup_trusted(table, path, stat=stat)
        if digest is not None:
            out[path] = digest
    return out


def remember(
    table: MutableMapping[str, Any],
    path: str,
    digest: str,
    *,
    stat: StatFn = os.stat,
) -> None:
    try:
        st = stat(path)
    except OSError:
        return
    entry = HashEntry(
        hash=digest,
        mtime_ns=st.st_mtime_ns,
        size=st.st_size,
    )
    with _TABLE_LOCK:
        table[path] = entry


def snapshot_table(table: Mapping[str, Any]) -> Dict[str, Any]:
    """Copy ``table`` under the same lock :func:`remember` writes through.

    Use this instead of ``dict(table)`` before handing the table to code that
    iterates it off-thread (e.g. ``dataclasses.asdict`` during settings
    serialization), since a worker thread may be inserting new entries via
    :func:`remember` concurrently.
    """
    with _TABLE_LOCK:
        return dict(table)
