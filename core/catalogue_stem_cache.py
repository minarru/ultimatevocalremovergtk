"""On-disk cache of training.instruments parsed from catalogue YAML URLs."""

from __future__ import annotations

import itertools
import json
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set

import yaml

from .mdx_config_fetch import _urlopen

_SUCCESS_TTL_SECONDS = 7 * 24 * 3600
_FAILURE_TTL_SECONDS = 6 * 3600
_MAX_BODY_BYTES = 2 * 1024 * 1024
_FETCH_WORKERS = 2

_memory_entries: Optional[Dict[str, Dict[str, Any]]] = None

#: PriorityQueue items are ``(priority, sequence, url)`` — lower priority first.
_url_queue: queue.PriorityQueue[tuple[int, int, str]] = queue.PriorityQueue()
_queue_seq = itertools.count()
_queued_urls: Set[str] = set()
_queue_lock = threading.Lock()
_subscribers: List[Callable[[], None]] = []
_subscribers_lock = threading.Lock()
_worker_thread: Optional[threading.Thread] = None
_worker_lock = threading.Lock()
_worker_idle = threading.Event()
_worker_idle.set()
_active_fetches = 0
_active_fetches_lock = threading.Lock()


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


def subscribe(callback: Callable[[], None]) -> None:
    with _subscribers_lock:
        if callback not in _subscribers:
            _subscribers.append(callback)


def unsubscribe(callback: Callable[[], None]) -> None:
    with _subscribers_lock:
        try:
            _subscribers.remove(callback)
        except ValueError:
            pass


def _notify_subscribers() -> None:
    # Do not clear_display_cache here: stem apply patches catalogue_meta in
    # place via DownloadManager.apply_catalogue_stem_cache. A full remesh on
    # every YAML batch was rebuilding politrees/extras/mvsepless repeatedly.
    with _subscribers_lock:
        callbacks = list(_subscribers)
    for callback in callbacks:
        try:
            callback()
        except Exception:
            pass


def enqueue_missing(urls: Iterable[str], *, priority: bool = False) -> None:
    """Queue YAML URLs for background stem fetch.

    ``priority=True`` jumps ahead of bulk/background URLs (Download Center
    visible rows). Already-queued URLs are not duplicated; a later priority
    enqueue of an in-flight URL is a no-op.
    """
    if not catalogue_stems_enabled():
        return
    prio = 0 if priority else 1
    with _queue_lock:
        to_put: list[str] = []
        for url in urls:
            key = normalize_config_url(str(url))
            if not key or key in _queued_urls:
                continue
            _queued_urls.add(key)
            to_put.append(key)
        for key in to_put:
            _url_queue.put((prio, next(_queue_seq), key))


def ensure_worker_started() -> None:
    global _worker_thread
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        thread = threading.Thread(
            target=_worker_loop,
            name="uvr-catalogue-stems",
            daemon=True,
        )
        _worker_thread = thread
        thread.start()


def _fetch_and_remember(url: str) -> None:
    global _active_fetches
    with _active_fetches_lock:
        _active_fetches += 1
    try:
        try:
            with _urlopen(url) as response:
                data = response.read(_MAX_BODY_BYTES + 1)
            if not isinstance(data, (bytes, bytearray)):
                remember_stems(url, [], None, ok=False)
                return
            body = bytes(data)
            if len(body) > _MAX_BODY_BYTES:
                remember_stems(url, [], None, ok=False)
                return
            stems, target = parse_stems_from_yaml_bytes(body)
            if not stems:
                remember_stems(url, [], None, ok=False)
                return
            remember_stems(url, stems, target, ok=True)
        except Exception:
            remember_stems(url, [], None, ok=False)
    finally:
        with _active_fetches_lock:
            _active_fetches -= 1


def active_fetch_count() -> int:
    """How many stem YAML fetches are in flight (for tests)."""
    with _active_fetches_lock:
        return _active_fetches


def _drain_queued_items(
    first: tuple[int, int, str],
) -> list[tuple[int, int, str]]:
    """Collect ``first`` plus any items currently queued (holds ``_queue_lock``)."""
    pending = [first]
    with _queue_lock:
        while True:
            try:
                pending.append(_url_queue.get_nowait())
            except queue.Empty:
                break
    pending.sort()
    return pending


def _worker_loop() -> None:
    while True:
        first = _url_queue.get()
        _worker_idle.clear()
        pending = _drain_queued_items(first)
        try:
            while pending:
                chunk = pending[:_FETCH_WORKERS]
                pending = pending[_FETCH_WORKERS:]
                with ThreadPoolExecutor(max_workers=len(chunk)) as pool:
                    futures = [
                        pool.submit(_fetch_and_remember, item[2]) for item in chunk
                    ]
                    for future in as_completed(futures):
                        future.result()
                with _queue_lock:
                    for item in chunk:
                        _queued_urls.discard(item[2])
                    newly: list[tuple[int, int, str]] = []
                    while True:
                        try:
                            newly.append(_url_queue.get_nowait())
                        except queue.Empty:
                            break
                if newly:
                    pending = sorted(pending + newly)
            _notify_subscribers()
        finally:
            with _queue_lock:
                idle = _url_queue.empty() and not _queued_urls
            if idle:
                _worker_idle.set()


def _reset_worker_state_for_tests() -> None:
    """Drain queue / subscribers between unit tests (daemon thread stays)."""
    global _subscribers
    if _worker_thread is not None and _worker_thread.is_alive():
        _worker_idle.wait(timeout=2.0)
    with _subscribers_lock:
        _subscribers = []
    with _queue_lock:
        while True:
            try:
                _url_queue.get_nowait()
            except queue.Empty:
                break
        _queued_urls.clear()
    _worker_idle.set()
