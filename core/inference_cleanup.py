"""Release GPU/CPU memory held by separation and audio-tool workers."""

from __future__ import annotations

import gc
import time
from typing import Any, Mapping, Optional

from .debug_log import debug, debug_elapsed, verbose


def release_torch_model(model: Any) -> None:
    """Move a torch module off the device and drop the reference when possible."""
    if model is None:
        return
    try:
        cpu = getattr(model, "cpu", None)
        if callable(cpu):
            cpu()
    except Exception:  # noqa: BLE001 - best-effort teardown
        pass


def _release_cached_value(value: Any) -> None:
    """Drop references to large cached audio / stem payloads."""
    if value is None:
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _release_cached_value(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _release_cached_value(item)


def clear_source_mapper(mapper: Optional[dict]) -> None:
    """Remove every cached stem entry from a per-architecture mapper."""
    if not mapper:
        return
    for key in list(mapper):
        _release_cached_value(mapper.pop(key, None))


def release_separator(separator: Any) -> None:
    """Drop a separator instance's loaded model and large cached arrays."""
    if separator is None:
        return
    model_name = getattr(separator, "model_basename", None)
    debug("cleanup", f"release_separator model={model_name!r}")

    cached = False
    try:
        from engines.model_weight_cache import get_weight_cache

        cached = get_weight_cache().stash_separator(separator)
    except Exception:  # noqa: BLE001 - never fail cleanup on cache errors
        cached = False

    if not cached:
        release_torch_model(getattr(separator, "demucs", None))
        if hasattr(separator, "demucs"):
            separator.demucs = None
        ort_session = getattr(separator, "_ort_session", None)
        if ort_session is not None:
            close = getattr(ort_session, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - best-effort teardown
                    pass
            if hasattr(separator, "_ort_session"):
                separator._ort_session = None
        release_torch_model(getattr(separator, "model_run", None))
        separator.model_run = None
        release_torch_model(getattr(separator, "_inference_model", None))
        separator._inference_model = None
    else:
        debug("cleanup", f"release_separator cached weights model={model_name!r}")
        if hasattr(separator, "demucs"):
            separator.demucs = None
        if hasattr(separator, "_ort_session"):
            separator._ort_session = None
        separator.model_run = None
        separator._inference_model = None

    for attr in (
        "primary_sources",
        "secondary_source",
        "primary_source",
        "secondary_source_primary",
        "secondary_source_secondary",
        "master_inst_source",
        "master_vocal_source",
        "mix",
        "stft",
    ):
        if hasattr(separator, attr):
            setattr(separator, attr, None)
    for attr in ("primary_source_map", "secondary_source_map"):
        if hasattr(separator, attr):
            mapping = getattr(separator, attr, None)
            if isinstance(mapping, dict):
                _release_cached_value(mapping)
                mapping.clear()
            setattr(separator, attr, {})


def release_inference_memory(
    runner: Optional[Any] = None,
    *,
    wait_for_stop: float = 0.0,
    force_if_alive: bool = False,
    clear_weight_cache: bool = False,
) -> None:
    """Clear per-run caches and return cached GPU/CPU allocator memory.

    Weight LRU is kept across normal runs so the next Start can reuse
    checkpoints. Pass ``clear_weight_cache=True`` on app quit / full teardown.
    """
    started = time.perf_counter()
    debug(
        "cleanup",
        "release_inference_memory enter "
        f"wait_for_stop={wait_for_stop} force={force_if_alive} "
        f"clear_weight_cache={clear_weight_cache}",
    )
    if runner is not None:
        is_running = getattr(runner, "is_running", None)
        stop = getattr(runner, "stop", None)
        if wait_for_stop > 0 and callable(is_running) and is_running():
            wait_started = time.perf_counter()
            deadline = time.monotonic() + wait_for_stop
            while is_running() and time.monotonic() < deadline:
                time.sleep(0.05)
            if verbose():
                debug_elapsed("cleanup", "wait_for_stop", wait_started)
        if force_if_alive and callable(is_running) and is_running() and callable(stop):
            debug("cleanup", "force stop worker thread")
            stop(force=True)
            time.sleep(0.15)
        if not callable(is_running) or not is_running() or force_if_alive:
            release_separator(getattr(runner, "_active_separator", None))
            if hasattr(runner, "_active_separator"):
                runner._active_separator = None
        cached_clear = getattr(runner, "_cached_sources_clear", None)
        if callable(cached_clear):
            cached_clear()
        if hasattr(runner, "all_models"):
            runner.all_models = []
    if clear_weight_cache:
        try:
            from engines.model_weight_cache import get_weight_cache

            get_weight_cache().clear()
        except Exception:  # noqa: BLE001
            pass
    from engines.separate import clear_gpu_cache

    gc.collect()
    clear_gpu_cache()
    gc.collect()
    debug_elapsed("cleanup", "release_inference_memory done", started)
