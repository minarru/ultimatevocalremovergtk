"""Cache for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
from dataclasses import dataclass
from typing import (
    Optional,
    Tuple,
)

from catalogue import locations


@dataclass(frozen=True)
class FetchPolicy:
    """How this run is allowed to reach the network and reuse caches.

    One object rather than a pair of booleans threaded through every layer:
    the generator has several fetch points and they must all agree, which is
    exactly what went wrong when only the snapshot honoured ``--offline``.
    """

    allow_network: bool = True
    refresh: bool = False
    max_age: float = locations.CACHE_MAX_AGE_SECONDS
    #: Whether coordinator/runtime metadata may be persisted. Generator YAML
    #: evidence never uses runtime config storage; it is governed exclusively
    #: by allow_cache_writes below.
    allow_metadata_writes: bool = True
    #: Whether network responses may be persisted in catalogue supplement or
    #: coordinator source caches. Check/summary may still fetch into memory.
    allow_cache_writes: bool = True


# Online, cache-respecting, TTL-bound default for standalone callers.
DEFAULT_FETCH_POLICY = FetchPolicy()


# Cache-only: never fetch; serve whatever is on disk however old.
OFFLINE_FETCH_POLICY = FetchPolicy(allow_network=False)


def _cache_path(cache_dir: str, url: str, filename: str) -> str:
    """Cache identity keyed by URL, not by basename alone.

    Two different models can both ship a ``config.yaml``; keying on the
    basename made the second one silently read the first one's bytes. The
    readable stem is kept so the directory stays browsable.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    stem, ext = os.path.splitext(filename)
    return os.path.join(cache_dir, f"{stem}-{digest}{ext}")


def fetch_cached_bytes(
    url: str,
    cache_dir: str,
    filename: str,
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
    refresh: bool = False,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Return response bytes and the readable cache path, if one exists.

    Offline is strictly cache-only: a miss stays a miss and a stale entry is
    still served, because the alternative is a silent download. Online, an
    entry older than ``policy.max_age`` is refreshed. A read-only online run
    receives fresh bytes in memory without creating or replacing cache files.
    """
    if allow_network is not None or refresh:
        policy = FetchPolicy(
            allow_network=policy.allow_network if allow_network is None else allow_network,
            refresh=refresh or policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
            allow_cache_writes=policy.allow_cache_writes,
        )

    cache_path = _cache_path(cache_dir, url, filename)
    cached = os.path.isfile(cache_path)
    cached_data: Optional[bytes] = None
    if cached:
        try:
            with open(cache_path, "rb") as handle:
                cached_data = handle.read()
        except OSError:
            pass

    if not policy.allow_network:
        # However old: offline must never turn a cache hit into a fetch.
        return cached_data, cache_path if cached_data is not None else None
    if cached_data is not None and not policy.refresh:
        try:
            if time.time() - os.path.getmtime(cache_path) < policy.max_age:
                return cached_data, cache_path
        except OSError:
            pass

    try:
        from core.mdx_config_fetch import _urlopen

        with _urlopen(url) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, TimeoutError):
        return cached_data, cache_path if cached_data is not None else None

    persisted_path: Optional[str] = cache_path if cached_data is not None else None
    if policy.allow_cache_writes:
        # Staged, so a failed write cannot truncate a good entry into a
        # corrupt one that is then served for the rest of the TTL.
        tmp_path = f"{cache_path}.part"
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(tmp_path, "wb") as handle:
                handle.write(data)
            os.replace(tmp_path, cache_path)
            persisted_path = cache_path
        except OSError:
            pass
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return data, persisted_path


def fetch_cached(
    url: str,
    cache_dir: str,
    filename: str,
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
    refresh: bool = False,
) -> Optional[str]:
    """Return a readable cache path for compatibility with path consumers."""
    data, path = fetch_cached_bytes(
        url,
        cache_dir,
        filename,
        policy=policy,
        allow_network=allow_network,
        refresh=refresh,
    )
    return path if data is not None else None


def fetch_yaml_bytes(
    url: str, yaml_name: str, *, policy: FetchPolicy = DEFAULT_FETCH_POLICY
) -> Tuple[Optional[bytes], Optional[str]]:
    if not url or not yaml_name.casefold().endswith((".yaml", ".yml")):
        return None, None
    return fetch_cached_bytes(url, locations.YAML_CACHE_DIR, yaml_name, policy=policy)
