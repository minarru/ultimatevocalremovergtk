"""On-disk cache of training.instruments parsed from catalogue YAML URLs."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

import yaml

from .mdx_config_fetch import _urlopen

_SUCCESS_TTL_SECONDS = 7 * 24 * 3600
_FAILURE_TTL_SECONDS = 6 * 3600
_MAX_BODY_BYTES = 2 * 1024 * 1024

_memory_entries: Optional[Dict[str, Dict[str, Any]]] = None


@dataclass(frozen=True)
class StemCacheHit:
    stems: tuple[str, ...]
    target_instrument: Optional[str]
    ok: bool


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

    return paths.migrate_cache_file(
        "catalogue_stem_cache.json", paths.CATALOGUE_STEM_CACHE_FILE
    )


def _ensure_loaded() -> Dict[str, Dict[str, Any]]:
    global _memory_entries
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


def _entry_ttl_seconds(entry: Mapping[str, Any]) -> float:
    return _SUCCESS_TTL_SECONDS if entry.get("ok") else _FAILURE_TTL_SECONDS


def _entry_fresh(entry: Mapping[str, Any], *, now: Optional[float] = None) -> bool:
    fetched_at = entry.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return False
    if now is None:
        now = time.time()
    return (now - float(fetched_at)) <= _entry_ttl_seconds(entry)


def _entry_to_hit(entry: Mapping[str, Any]) -> StemCacheHit:
    raw_stems = entry.get("stems")
    stems: tuple[str, ...] = ()
    if isinstance(raw_stems, list):
        stems = tuple(str(s) for s in raw_stems if s is not None)
    target = entry.get("target_instrument")
    target_instrument = str(target) if target is not None and target != "" else None
    return StemCacheHit(
        stems=stems,
        target_instrument=target_instrument,
        ok=bool(entry.get("ok")),
    )


def lookup_stems(url: str) -> Optional[StemCacheHit]:
    if not catalogue_stems_enabled():
        return None
    key = normalize_config_url(url)
    entry = _ensure_loaded().get(key)
    if entry is None or not _entry_fresh(entry):
        return None
    return _entry_to_hit(entry)


def remember_stems(
    url: str,
    stems: Sequence[str],
    target_instrument: Optional[str],
    *,
    ok: bool,
) -> None:
    key = normalize_config_url(url)
    now = time.time()
    entry: Dict[str, Any] = {
        "stems": list(stems),
        "target_instrument": target_instrument,
        "fetched_at": now,
        "ok": ok,
    }
    entries = _ensure_loaded()
    entries[key] = entry
    try:
        cache_path = _cache_path()
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": now, "entries": entries}, handle)
    except OSError:
        pass


def clear_catalogue_stem_cache() -> None:
    global _memory_entries
    _memory_entries = None
    try:
        os.remove(_cache_path())
    except OSError:
        pass
    from .model_display import clear_display_cache

    clear_display_cache()


def parse_stems_from_yaml_bytes(data: bytes) -> tuple[list[str], Optional[str]]:
    doc = yaml.safe_load(data)
    if not isinstance(doc, dict):
        return [], None
    training = doc.get("training")
    if not isinstance(training, dict):
        return [], None
    instruments = training.get("instruments")
    stems: list[str] = []
    if isinstance(instruments, list):
        stems = [str(item) for item in instruments if item is not None]
    if not stems:
        return [], None
    target = training.get("target_instrument")
    target_instrument: Optional[str] = None
    if target is not None and target != "":
        target_instrument = str(target)
    return stems, target_instrument
