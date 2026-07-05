"""Lazy import of separation engines (:mod:`separate`).

Importing ``separate`` pulls in torch, onnxruntime, demucs, etc. and typically
costs ~1–2s on the first load. :func:`warm_import_separate_engines` starts that
work in a background thread during app startup so the first separation run can
emit console output immediately.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional, Tuple

from .debug_log import debug

_lock = threading.Lock()
_engines: Optional[Tuple[Any, ...]] = None
_warm_thread: Optional[threading.Thread] = None


def import_separate_engines() -> Tuple[Any, ...]:
    """Import and cache engine classes; safe to call from any thread."""
    global _engines
    with _lock:
        if _engines is not None:
            return _engines
        started = time.perf_counter()
        debug("worker", "importing separate engines (sync)")
        from separate import (  # noqa: WPS433 - intentional lazy import
            SeperateDemucs,
            SeperateMDX,
            SeperateMDXC,
            SeperateVR,
            clear_gpu_cache,
        )

        _engines = (
            SeperateDemucs,
            SeperateMDX,
            SeperateMDXC,
            SeperateVR,
            clear_gpu_cache,
        )
        debug(
            "worker",
            f"separate engines imported elapsed={time.perf_counter() - started:.3f}s",
        )
        global _warm_thread
        _warm_thread = None
        return _engines


def warm_import_separate_engines() -> None:
    """Start a background import if engines are not loaded yet."""
    global _warm_thread
    with _lock:
        if _engines is not None or _warm_thread is not None:
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
    return _engines is not None


def warm_status() -> str:
    if _engines is not None:
        return "done"
    thread = _warm_thread
    if thread is not None and thread.is_alive():
        return "in_progress"
    if thread is not None:
        return "finished"
    return "not_started"
