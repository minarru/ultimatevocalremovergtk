"""Process-level shutdown helpers for the GTK shell.

GTK may quit while a non-daemon :class:`kthread.KThread` worker is still alive;
Python would otherwise keep running headlessly. :func:`finalize_process_exit`
ends the OS process after the main loop returns.
"""

from __future__ import annotations

import os
import threading


def finalize_process_exit(status: int) -> None:
    """Terminate the process, bypassing lingering non-daemon worker threads."""
    from core.debug_log import debug, enabled

    code = status if status >= 0 else 0
    if enabled("ui"):
        debug(
            "ui",
            f"os._exit status={code} threads={threading.active_count()}",
        )
    os._exit(code)
