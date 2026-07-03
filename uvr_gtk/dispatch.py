"""Marshal background-thread callbacks onto the GTK main loop.

:class:`uvr_core.JobRunner` runs separation on a worker thread and calls plain
callbacks from that thread. GTK widgets may only be touched from the main loop,
so the helpers here wrap those callbacks with ``GLib.idle_add``. Later phases use
:func:`gtk_job_callbacks` to bind progress/console/completion to widgets safely.
"""

from typing import Callable, Optional

from gi.repository import GLib

from uvr_core import JobCallbacks
from uvr_core.debug_log import debug


def idle_on_main(func: Callable, *args, **kwargs) -> None:
    """Schedule ``func(*args, **kwargs)`` once on the GTK main loop."""

    def invoke():
        func(*args, **kwargs)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(invoke)


def main_thread(func: Callable) -> Callable:
    """Return a wrapper that schedules ``func`` to run once on the main loop."""
    label = getattr(func, "__name__", repr(func))

    def wrapper(*args, **kwargs):
        debug("dispatch", f"schedule {label}({ _preview_args(args) })")

        def invoke():
            debug("dispatch", f"invoke {label}({ _preview_args(args) })")
            func(*args, **kwargs)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(invoke)

    return wrapper


def _preview_args(args: tuple) -> str:
    if not args:
        return ""
    first = args[0]
    if isinstance(first, str):
        text = first.replace("\n", "\\n")
        if len(text) > 72:
            text = text[:69] + "..."
        return repr(text)
    if isinstance(first, float):
        return f"{first:.4f}"
    return repr(first)


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
