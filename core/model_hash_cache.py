"""Trusted path→hash entries for dry model checks across sessions."""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional

StatFn = Callable[[str], os.stat_result]


def _as_entry(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, Mapping) and "hash" in value:
        digest = value.get("hash")
        if isinstance(digest, str) and digest:
            return {
                "hash": digest,
                "mtime_ns": int(value.get("mtime_ns") or 0),
                "size": int(value.get("size") or -1),
            }
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
    st = stat(path)
    table[path] = {
        "hash": digest,
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
    }
