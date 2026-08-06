"""Checkpoint → display-name mappers, split into an upstream mirror + local overlay.

``model_name_mapper.json`` mirrors upstream verbatim. Fork-local and
locally-registered names live beside it in ``model_name_mapper_local.json`` and
are merged on read, overlay winning.

The previous scheme merged ``{**local, **remote}`` straight back into the
upstream file, which made that file the running union of every version upstream
ever published: a key upstream *removed* (a corrected mis-mapping, say) could
never disappear locally, and nothing distinguished a deliberate fork entry from
a stale upstream one. Keeping the two apart gives deletions a way to propagate
while fork entries still survive a refresh.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Mapping

_LOCAL_SUFFIX = "_local.json"


def local_overlay_path(mapper_path: str) -> str:
    """Sibling overlay file for ``mapper_path``."""
    base, _ext = os.path.splitext(mapper_path)
    return f"{base}{_LOCAL_SUFFIX}"


def _load_object(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return {str(k): str(v) for k, v in payload.items()}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _write_object(path: str, payload: Mapping[str, str]) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), indent=4))
        os.replace(tmp_path, path)
        return True
    except OSError:
        return False


def load_local_overlay(mapper_path: str) -> Dict[str, str]:
    return _load_object(local_overlay_path(mapper_path))


def load_name_mapper(mapper_path: str) -> Dict[str, str]:
    """Upstream mirror with the local overlay applied on top."""
    return {**_load_object(mapper_path), **load_local_overlay(mapper_path)}


def add_local_name(mapper_path: str, key: str, display_name: str) -> bool:
    """Record a fork-local display name. Never touches the upstream mirror."""
    overlay = load_local_overlay(mapper_path)
    if overlay.get(key) == display_name:
        return False
    overlay[key] = display_name
    return _write_object(local_overlay_path(mapper_path), overlay)


def migrate_local_only_keys(mapper_path: str, remote: Mapping[str, object]) -> bool:
    """One-shot rescue of fork keys that older builds wrote into the mirror.

    Returns ``True`` when keys were actually moved.

    This can only ever run **once per mapper**. "In the mirror but not in the
    incoming payload" describes a fork-local key and a key upstream just
    deleted equally well, so repeating it would re-capture every upstream
    deletion into the overlay and reinstate exactly the bug the overlay exists
    to fix. The overlay file is therefore its own migration marker: it is
    written unconditionally here — empty when there was nothing to rescue — and
    its existence means the mirror is authoritative from now on.
    """
    overlay_path = local_overlay_path(mapper_path)
    if os.path.exists(overlay_path):
        return False
    mirror = _load_object(mapper_path)
    local_only = {key: value for key, value in mirror.items() if key not in remote}
    _write_object(overlay_path, local_only)
    return bool(local_only)
