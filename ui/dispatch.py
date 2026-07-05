"""Marshal background-thread callbacks onto the GTK main loop.

:class:`uvr_core.JobRunner` runs separation on a worker thread and calls plain
callbacks from that thread. GTK widgets may only be touched from the main loop,
so the helpers here wrap those callbacks with ``GLib.idle_add``. Later phases use
:func:`gtk_job_callbacks` to bind progress/console/completion to widgets safely.
"""

from typing import Callable, Optional
import time

from gi.repository import GLib

from uvr_core import JobCallbacks
from uvr_core.debug_log import correlation_seq, debug, preview_text, verbose

_PROGRESS_LOG_STEP = 0.05
_last_progress_log = -1.0


def reset_progress_log() -> None:
    global _last_progress_log
    _last_progress_log = -1.0


def idle_on_main(func: Callable, *args, **kwargs) -> None:
    """Schedule ``func(*args, **kwargs)`` once on the GTK main loop."""

    def invoke():
        func(*args, **kwargs)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(invoke)


def _should_log_progress(fraction: float) -> bool:
    global _last_progress_log
    if verbose():
        return True
    if fraction >= 1.0 or _last_progress_log < 0:
        _last_progress_log = fraction
        return True
    if fraction - _last_progress_log >= _PROGRESS_LOG_STEP:
        _last_progress_log = fraction
        return True
    return False


def _preview_args(label: str, args: tuple) -> str:
    if not args:
        return ""
    first = args[0]
    if label.startswith("_on_progress") and isinstance(first, float):
        return f"{first:.4f}"
    if isinstance(first, str):
        return repr(preview_text(first))
    if isinstance(first, float):
        return f"{first:.4f}"
    if isinstance(first, Exception):
        return type(first).__name__
    return repr(first)


def main_thread(func: Callable) -> Callable:
    """Return a wrapper that schedules ``func`` to run once on the main loop."""
    label = getattr(func, "__name__", repr(func))
    is_progress = label.endswith("_on_progress") or label == "_on_progress"

    def wrapper(*args, **kwargs):
        if is_progress and args and isinstance(args[0], float):
            if not _should_log_progress(args[0]):
                def invoke_quiet():
                    func(*args, **kwargs)
                    return GLib.SOURCE_REMOVE
                GLib.idle_add(invoke_quiet)
                return

        seq = correlation_seq()
        preview = _preview_args(label, args)
        scheduled_at = time.monotonic()
        debug("dispatch", f"schedule {label}({preview})", seq=seq)

        def invoke():
            latency_ms = (time.monotonic() - scheduled_at) * 1000.0
            if is_progress:
                debug("dispatch", f"invoke {label}({preview})", seq=seq)
            else:
                debug(
                    "dispatch",
                    f"invoke {label}({preview}) after {latency_ms:.1f}ms",
                    seq=seq,
                )
            func(*args, **kwargs)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(invoke)

    return wrapper


def gtk_job_callbacks(
    on_progress: Optional[Callable[[float], None]] = None,
    on_console: Optional[Callable[[str], None]] = None,
    on_complete: Optional[Callable[[], None]] = None,
    on_stopped: Optional[Callable[[], None]] = None,
    on_error: Optional[Callable[[BaseException], None]] = None,
) -> JobCallbacks:
    """Build :class:`JobCallbacks` whose handlers run on the GTK main loop."""
    return JobCallbacks(
        on_progress=main_thread(on_progress) if on_progress else None,
        on_console=main_thread(on_console) if on_console else None,
        on_complete=main_thread(on_complete) if on_complete else None,
        on_stopped=main_thread(on_stopped) if on_stopped else None,
        on_error=main_thread(on_error) if on_error else None,
    )
