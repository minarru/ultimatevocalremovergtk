"""Process-scoped LRU cache for loaded separation model weights.

Separators normally destroy weights in ``release_separator``. Caching lets
batch jobs and secondary chains reuse checkpoints without reloading from disk.

Accelerator-backed entries keep the most recently used key resident on device
so same-model batch files avoid CPU↔GPU weight migration. Older entries are
parked to CPU; eviction / clear / model switches park as needed.

Under VRAM pressure, :func:`ensure_weight_cache_vram_headroom` reclaims
unused (non-run) entries first, then escalates to in-run / full clear.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Hashable, Iterable, Optional, Set, Tuple

from core.debug_log import debug

# When free VRAM falls below either floor, reclaim cache-held device memory so
# the current job can proceed (park unused first; clear only if still tight).
_MIN_FREE_BYTES = 2 * 1024**3  # 2 GiB
_MIN_FREE_RATIO = 0.15

FileIdentity = Tuple[str, int, int]


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
    except Exception:
        pass


def _close_ort(session: Any) -> None:
    if session is None:
        return
    close = getattr(session, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _is_accelerator_device(device: Any) -> bool:
    text = str(device or "cpu").lower()
    if not text or text == "cpu" or text.startswith("cpu"):
        return False
    return True


def model_file_identity(model_path: str) -> Optional[FileIdentity]:
    """Return ``(realpath, mtime_ns, size)`` for ``model_path``, or ``None`` if empty.

    Matches the identity embedded in :func:`weight_cache_key` so protect-sets
    can match cache entries without reconstructing full keys.
    """
    if not model_path:
        return None
    try:
        real = os.path.realpath(model_path)
        st = os.stat(real)
        return (real, int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        return (str(model_path), 0, 0)


def _key_identity(key: tuple[Any, ...]) -> Optional[FileIdentity]:
    if len(key) > 1 and isinstance(key[1], tuple) and len(key[1]) == 3:
        return key[1]  # type: ignore[return-value]
    return None


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
    identity = model_file_identity(model_path) or (str(model_path), 0, 0)
    return (kind, identity, str(device), variant)


class ModelWeightCache:
    """Small LRU of loaded modules / ORT sessions.

    Assumes at most one separator performs GPU inference at a time: the app's
    ``RunController`` (ui/run_control.py) exposes a single shared
    Start/Stop and ``_running_target``, so separation/ensemble/audio-tools
    runs are mutually exclusive. If that ever changes to allow concurrent
    runs on the same device, ``_device_resident_key`` below (a single slot)
    could park a module that a different run is still actively using
    mid-forward — this needs a per-run reservation, not just a bigger LRU.
    """

    def __init__(self, max_entries: int = 4) -> None:
        self.max_entries = max(1, int(max_entries))
        self._items: OrderedDict[tuple[Any, ...], CachedWeights] = OrderedDict()
        self._lock = threading.Lock()
        # At most one accelerator-resident module; others stay parked on CPU.
        self._device_resident_key: Optional[tuple[Any, ...]] = None

    def get(self, key: tuple[Any, ...]) -> Optional[CachedWeights]:
        with self._lock:
            handle = self._items.get(key)
            if handle is None:
                return None
            self._items.move_to_end(key)
            debug("cache", f"weight cache hit kind={key[0]!r}")
            return handle

    def put(
        self,
        key: tuple[Any, ...],
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
                debug(
                    "cache",
                    f"weight cache evict kind={next(iter(_evicted_key), '')!r}",
                )
                self._destroy(evicted)
            debug(
                "cache",
                f"weight cache store kind={next(iter(key), '')!r} "
                f"size={len(self._items)}",
            )

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

    def park_all(self) -> None:
        """Park cached modules on CPU and drop ORT sessions to free device memory."""
        with self._lock:
            self._park_entries_locked(protect_identities=None)
            debug("cache", "weight cache parked all to cpu")

    def park_except(self, protect_identities: Optional[Iterable[FileIdentity]] = None) -> int:
        """Park modules / drop ORT for entries whose file identity is not protected.

        Returns the number of entries touched.
        """
        protect = set(protect_identities or ())
        with self._lock:
            touched = self._park_entries_locked(protect_identities=protect)
            debug("cache", f"weight cache park_except touched={touched} protect={len(protect)}")
            return touched

    def clear_except(self, protect_identities: Optional[Iterable[FileIdentity]] = None) -> int:
        """Destroy cache entries whose file identity is not protected.

        Returns the number of entries removed.
        """
        protect = set(protect_identities or ())
        with self._lock:
            remove_keys = [
                key
                for key in list(self._items.keys())
                if _key_identity(key) not in protect
            ]
            for key in remove_keys:
                handle = self._items.pop(key)
                if self._device_resident_key == key:
                    self._device_resident_key = None
                self._destroy(handle)
                debug("cache", f"weight cache clear_except kind={key[0]!r}")
            return len(remove_keys)

    def _park_entries_locked(self, *, protect_identities: Optional[Set[FileIdentity]]) -> int:
        """Park modules and drop ORT for non-protected entries. ``None`` protect = all."""
        touched = 0
        for key, handle in self._items.items():
            ident = _key_identity(key)
            if protect_identities is not None and ident in protect_identities:
                continue
            changed = False
            if handle.module is not None:
                _release_module(handle.module)
                changed = True
            if handle.ort_session is not None:
                _close_ort(handle.ort_session)
                handle.ort_session = None
                changed = True
                debug("cache", f"weight cache drop ort kind={key[0]!r}")
            if changed:
                touched += 1
            if self._device_resident_key == key:
                self._device_resident_key = None
        return touched

    def _park_device_resident_locked(
        self, *, except_key: Optional[tuple[Any, ...]] = None
    ) -> None:
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
        handle.ort_session = None
        _close_ort(ort)


_CACHE = ModelWeightCache(max_entries=4)


def get_weight_cache() -> ModelWeightCache:
    return _CACHE


def _cuda_device_index(device: Any = None) -> int:
    if device is None:
        return 0
    try:
        from bundled.constants import DEFAULT

        if device == DEFAULT or device == "":
            return 0
    except Exception:
        pass
    try:
        import torch

        device_obj = torch.device(device) if not isinstance(device, torch.device) else device
        if device_obj.type != "cuda":
            return 0
        return int(device_obj.index or 0)
    except Exception:
        text = str(device).split(":")[-1].strip()
        try:
            return int(text)
        except ValueError:
            return 0


def cuda_mem_info(device: Any = None) -> Optional[Tuple[int, int]]:
    """Return ``(free_bytes, total_bytes)`` for a CUDA device, or ``None``."""
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        index = _cuda_device_index(device)
        if index < 0 or index >= torch.cuda.device_count():
            return None
        free, total = torch.cuda.mem_get_info(index)
        return int(free), int(total)
    except Exception:
        return None


def vram_headroom_is_low(
    free_bytes: int,
    total_bytes: int,
    *,
    min_free_bytes: int = _MIN_FREE_BYTES,
    min_free_ratio: float = _MIN_FREE_RATIO,
) -> bool:
    """True when free VRAM is below the absolute or fractional floor."""
    if total_bytes <= 0 or free_bytes < 0:
        return False
    if free_bytes < int(min_free_bytes):
        return True
    return (free_bytes / float(total_bytes)) < float(min_free_ratio)


def _flush_cuda_allocator() -> None:
    try:
        from engines.gpu_cache import clear_gpu_cache

        clear_gpu_cache("cuda")
    except Exception:
        pass
    try:
        import gc

        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _headroom_ok(device: Any = None) -> bool:
    info = cuda_mem_info(device)
    if info is None:
        return True
    return not vram_headroom_is_low(info[0], info[1])


def ensure_weight_cache_vram_headroom(
    device: Any = None,
    *,
    protect_identities: Optional[Iterable[FileIdentity]] = None,
    prefer_gpu_identity: Optional[FileIdentity] = None,
) -> str:
    """Free just enough cache-held VRAM for the current job to proceed.

    Escalation when free VRAM is low:

    1. Park entries outside the protect set (or only keep ``prefer_gpu_identity``
       on GPU when set)
    2. Clear unprotected entries if still tight
    3. Park protect-set entries too
    4. Clear the entire LRU

    When ``protect_identities`` is empty/None, falls back to park-all then clear-all.

    Returns ``\"\"``, ``\"parked_other\"``, ``\"cleared_other\"``, ``\"parked_all\"``,
    or ``\"cleared_all\"``.
    """
    info = cuda_mem_info(device)
    if info is None:
        return ""
    free_bytes, total_bytes = info
    if not vram_headroom_is_low(free_bytes, total_bytes):
        return ""

    cache = get_weight_cache()
    protect = set(protect_identities or ())

    if not protect:
        cache.park_all()
        _flush_cuda_allocator()
        if _headroom_ok(device):
            debug(
                "cache",
                "weight cache parked_all (no protect set) "
                f"free_mib={free_bytes // (1024 * 1024)}",
            )
            return "parked_all"
        cache.clear()
        _flush_cuda_allocator()
        debug("cache", "weight cache cleared_all (no protect set)")
        return "cleared_all"

    # Prefer keeping only the active model on GPU when reclaiming mid-run.
    park_protect = {prefer_gpu_identity} if prefer_gpu_identity is not None else protect
    cache.park_except(park_protect)
    _flush_cuda_allocator()
    if _headroom_ok(device):
        debug(
            "cache",
            "weight cache parked_other "
            f"free_mib={free_bytes // (1024 * 1024)} protect={len(protect)}",
        )
        return "parked_other"

    cache.clear_except(protect)
    _flush_cuda_allocator()
    if _headroom_ok(device):
        debug("cache", f"weight cache cleared_other protect={len(protect)}")
        return "cleared_other"

    cache.park_all()
    _flush_cuda_allocator()
    if _headroom_ok(device):
        debug("cache", "weight cache parked_all after protect reclaim")
        return "parked_all"

    cache.clear()
    _flush_cuda_allocator()
    debug("cache", "weight cache cleared_all after protect reclaim")
    return "cleared_all"
