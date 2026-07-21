"""Process-scoped LRU cache for loaded separation model weights.

Separators normally destroy weights in ``release_separator``. Caching lets
batch jobs and secondary chains reuse checkpoints without reloading from disk.

Accelerator-backed entries keep the most recently used key resident on device
so same-model batch files avoid CPU↔GPU weight migration. Older entries are
parked to CPU; eviction / clear / model switches park as needed.
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


def _is_accelerator_device(device: Any) -> bool:
    text = str(device or "cpu").lower()
    if not text or text == "cpu" or text.startswith("cpu"):
        return False
    return True


def materialize_module(module: Any, device: Any) -> Any:
    """Move a cached module onto ``device`` and set eval mode for inference."""
    if module is None:
        return None
    to = getattr(module, "to", None)
    if callable(to):
        module = to(device)
    eval_fn = getattr(module, "eval", None)
    if callable(eval_fn):
        eval_fn()
    return module


def park_module(module: Any) -> None:
    """Return a materialized module to CPU residency for the weight cache."""
    _release_module(module)


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

    def __init__(self, max_entries: int = 4) -> None:
        self.max_entries = max(1, int(max_entries))
        self._items: OrderedDict[tuple, CachedWeights] = OrderedDict()
        self._lock = threading.Lock()
        # At most one accelerator-resident module; others stay parked on CPU.
        self._device_resident_key: Optional[tuple] = None

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
        park_to_cpu: bool = False,
    ) -> None:
        if module is None and ort_session is None:
            return
        want_device = (
            not park_to_cpu
            and module is not None
            and len(key) > 2
            and _is_accelerator_device(key[2])
        )
        with self._lock:
            if want_device:
                self._park_device_resident_locked(except_key=key)
            elif module is not None:
                # CPU targets (or explicit park) always store on host.
                _release_module(module)
                if self._device_resident_key == key:
                    self._device_resident_key = None

            handle = CachedWeights(module=module, ort_session=ort_session, meta=dict(meta or {}))
            if key in self._items:
                old = self._items.pop(key)
                same_module = old.module is handle.module
                same_ort = old.ort_session is handle.ort_session
                if not (same_module and same_ort):
                    self._destroy(old)
            self._items[key] = handle
            self._items.move_to_end(key)
            if want_device:
                self._device_resident_key = key
            while len(self._items) > self.max_entries:
                _evicted_key, evicted = self._items.popitem(last=False)
                if self._device_resident_key == _evicted_key:
                    self._device_resident_key = None
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
            self._device_resident_key = None
            debug("cache", "weight cache cleared")

    def _park_device_resident_locked(self, *, except_key: Optional[tuple] = None) -> None:
        key = self._device_resident_key
        if key is None or key == except_key:
            return
        handle = self._items.get(key)
        if handle is not None and handle.module is not None:
            _release_module(handle.module)
            debug("cache", f"weight cache park kind={key[0]!r}")
        self._device_resident_key = None

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


_CACHE = ModelWeightCache(max_entries=4)


def get_weight_cache() -> ModelWeightCache:
    return _CACHE
