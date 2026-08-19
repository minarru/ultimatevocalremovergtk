"""Lazy import of separation engines.

Importing the ``Seperate*`` engine modules pulls in torch, onnxruntime, demucs,
etc. and typically costs ~1–2s on the first load. :func:`warm_import_separate_engines`
starts that work in a background thread during app startup so the first
separation run can emit console output immediately.

Set ``UVR_SKIP_SEPARATE_WARMUP=1`` to skip that background import (engines load
on the first separation run instead).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

from .debug_log import debug

_lock = threading.Lock()
_imported: bool = False
_warm_thread: Optional[threading.Thread] = None

_SKIP_WARMUP_ENV = "UVR_SKIP_SEPARATE_WARMUP"


def skip_separate_warmup() -> bool:
    """Return whether startup should skip the background separate import."""
    return os.environ.get(_SKIP_WARMUP_ENV, "").strip() == "1"


def import_separate_engines() -> None:
    """Import and cache heavy engine modules; safe to call from any thread.

    Loads SeperateVR / SeperateMDX / SeperateMDXC / SeperateDemucs
    (torch, onnxruntime, demucs) via engines.separator_factory.preload_engine_modules.
    Returns nothing: JobRunner builds separators with build_seperator;
    run_loop imports clear_gpu_cache from engines.gpu_cache at use.
    """
    global _imported
    with _lock:
        if _imported:
            return
        started = time.perf_counter()
        debug("worker", "importing separate engines (sync)")
        from engines.separator_factory import preload_engine_modules

        preload_engine_modules()
        _imported = True
        debug(
            "worker",
            f"separate engines imported elapsed={time.perf_counter() - started:.3f}s",
        )
        global _warm_thread
        _warm_thread = None


def warm_import_separate_engines() -> None:
    """Start a background import if engines are not loaded yet."""
    if skip_separate_warmup():
        debug("worker", "skipping separate import warmup (UVR_SKIP_SEPARATE_WARMUP)")
        return
    global _warm_thread
    with _lock:
        if _imported or _warm_thread is not None:
            return

        def _run() -> None:
            import_separate_engines()

        _warm_thread = threading.Thread(
            target=_run,
            name="uvr-separate-warm",
            daemon=True,
        )
        debug("worker", "warming separate import in background")
        _warm_thread.start()


def engines_imported() -> bool:
    return _imported


def warm_status() -> str:
    if _imported:
        return "done"
    thread = _warm_thread
    if thread is not None and thread.is_alive():
        return "in_progress"
    if thread is not None:
        return "finished"
    return "not_started"
