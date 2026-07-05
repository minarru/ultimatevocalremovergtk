"""GTK fork release metadata and semver comparison."""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from typing import Dict, Tuple

from bundled.constants import FORK_RELEASE_JSON_URL, FORK_RELEASE_PAGE

from . import paths

try:
    from __version__ import UPSTREAM_BASE, VERSION
except Exception:  # pragma: no cover
    VERSION = ""
    UPSTREAM_BASE = ""

_RELEASE_CACHE: Dict | None = None
_RELEASE_ONLINE = False


def parse_version(version: str) -> Tuple[int, ...]:
    """Parse ``v1.0.0`` or ``1.0.0`` into a numeric tuple for comparison."""
    text = (version or "").strip().lstrip("vV")
    if not text:
        return (0,)
    parts: list[int] = []
    for segment in text.split("."):
        digits = ""
        for char in segment:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def is_newer(latest: str, current: str) -> bool:
    """Return True when ``latest`` is strictly newer than ``current``."""
    return parse_version(latest) > parse_version(current)


def _ssl_context() -> ssl.SSLContext:
    if os.environ.get("UVR_INSECURE_DOWNLOADS") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _urlopen(url: str):
    return urllib.request.urlopen(url, context=_ssl_context())


def _load_local_release_metadata() -> Dict:
    try:
        with open(paths.RELEASE_JSON_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def load_release_metadata(*, force_refresh: bool = False) -> Tuple[Dict, bool]:
    """Load fork release metadata. Returns ``(data, fetched_remote)``."""
    global _RELEASE_CACHE, _RELEASE_ONLINE

    if _RELEASE_CACHE is not None and not force_refresh:
        return _RELEASE_CACHE, _RELEASE_ONLINE

    remote: Dict = {}
    fetched_remote = False
    try:
        with _urlopen(FORK_RELEASE_JSON_URL) as response:
            remote = json.load(response)
            fetched_remote = isinstance(remote, dict)
    except Exception:
        remote = {}

    if not fetched_remote:
        remote = _load_local_release_metadata()
    elif not remote:
        remote = _load_local_release_metadata()

    _RELEASE_CACHE = remote if isinstance(remote, dict) else {}
    _RELEASE_ONLINE = fetched_remote
    return _RELEASE_CACHE, _RELEASE_ONLINE


def release_update_status(*, force_refresh: bool = False) -> Dict[str, object]:
    """Return GTK fork version/update status for the Updates UI."""
    metadata, is_online = load_release_metadata(force_refresh=force_refresh)
    latest = str(metadata.get("latest_version") or "")
    running = VERSION or ""
    is_current = bool(latest) and not is_newer(latest, running)
    if not latest:
        is_current = True

    update_link = (
        str(metadata.get("update_url") or "")
        or str(metadata.get("release_notes_url") or "")
        or FORK_RELEASE_PAGE
    )

    return {
        "version": running,
        "upstream_base": UPSTREAM_BASE,
        "latest": latest,
        "is_current": is_current,
        "is_online": is_online,
        "update_link": update_link,
        "distribution": str(metadata.get("distribution") or "source"),
        "upgrade_instructions": str(metadata.get("upgrade_instructions") or ""),
    }


def clear_release_cache() -> None:
    """Reset cached release metadata (for tests)."""
    global _RELEASE_CACHE, _RELEASE_ONLINE
    _RELEASE_CACHE = None
    _RELEASE_ONLINE = False
