"""Process-scoped LRU cache for loaded separation model weights.

Separators normally destroy weights in ``release_separator``. Caching lets
batch jobs and secondary chains reuse checkpoints without reloading from disk.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Hashable, Optional

from core.debug_log import debug


@dataclass
class CachedWeights:
    module: Any = None
    ort_session: Any = None
    meta: dict = field(default_factory=dict)


def _release_module(model: Any) -> None:
    if model is None:
        return
    try:
        cpu = getattr(model, "cpu", None)
        if callable(cpu):
            cpu()
    except Exception:  # noqa: BLE001
        pass


def weight_cache_key(
    kind: str,
    model_path: str,
    device: Any,
    *variant: Hashable,
) -> tuple:
    """Build a stable cache key from path identity, device, and architecture knobs."""
    try:
        real = os.path.realpath(model_path)
        st = os.stat(real)
        identity = (real, int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        identity = (str(model_path), 0, 0)
    return (kind, identity, str(device), variant)


class ModelWeightCache:
    """Small LRU of loaded modules / ORT sessions."""

    def __init__(self, max_entries: int = 2) -> None:
        self.max_entries = max(1, int(max_entries))
        self._items: OrderedDict[tuple, CachedWeights] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Optional[CachedWeights]:
        with self._lock:
            handle = self._items.get(key)
            if handle is None:
                return None
            self._items.move_to_end(key)
            debug("cache", f"weight cache hit kind={key[0]!r}")
            return handle

    def put(
        self,
        key: tuple,
        *,
        module: Any = None,
        ort_session: Any = None,
        meta: Optional[dict] = None,
    ) -> None:
        if module is None and ort_session is None:
            return
        handle = CachedWeights(module=module, ort_session=ort_session, meta=dict(meta or {}))
        with self._lock:
            if key in self._items:
                old = self._items.pop(key)
                same_module = old.module is handle.module
                same_ort = old.ort_session is handle.ort_session
                if not (same_module and same_ort):
                    self._destroy(old)
            self._items[key] = handle
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                _evicted_key, evicted = self._items.popitem(last=False)
                debug("cache", f"weight cache evict kind={_evicted_key[0]!r}")
                self._destroy(evicted)
            debug("cache", f"weight cache store kind={key[0]!r} size={len(self._items)}")

    def stash_separator(self, separator: Any) -> bool:
        """Move model handles from ``separator`` into the cache without destroying them."""
        key = getattr(separator, "_weight_cache_key", None)
        if key is None:
            return False

        ort_session = getattr(separator, "_ort_session", None)
        module = None
        meta: dict[str, Any] = {}

        if ort_session is not None:
            meta["backend"] = "ort"
        else:
            for attr in ("model_run", "_inference_model", "demucs"):
                candidate = getattr(separator, attr, None)
                if candidate is None:
                    continue
                if callable(candidate) and not hasattr(candidate, "state_dict"):
                    # Skip ONNX lambda wrappers without a live session.
                    continue
                module = candidate
                meta["attr"] = attr
                break

        if module is None and ort_session is None:
            return False

        self.put(key, module=module, ort_session=ort_session, meta={
            **meta,
            **dict(getattr(separator, "_weight_cache_meta", {}) or {}),
        })

        if hasattr(separator, "_ort_session"):
            separator._ort_session = None
        if hasattr(separator, "model_run"):
            separator.model_run = None
        if hasattr(separator, "_inference_model"):
            separator._inference_model = None
        if hasattr(separator, "demucs"):
            separator.demucs = None
        return True

    def clear(self) -> None:
        with self._lock:
            while self._items:
                _key, handle = self._items.popitem(last=False)
                self._destroy(handle)
            debug("cache", "weight cache cleared")

    @staticmethod
    def _destroy(handle: CachedWeights) -> None:
        _release_module(handle.module)
        handle.module = None
        ort = handle.ort_session
        if ort is not None:
            close = getattr(ort, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass
        handle.ort_session = None


_CACHE = ModelWeightCache(max_entries=2)


def get_weight_cache() -> ModelWeightCache:
    return _CACHE
