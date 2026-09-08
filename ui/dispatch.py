"""Marshal background-thread callbacks onto the GTK main loop.

:class:`core.JobRunner` runs separation on a worker thread and calls plain
callbacks from that thread. GTK widgets may only be touched from the main loop,
so the helpers here wrap those callbacks with ``GLib.idle_add``. Later phases use
:func:`gtk_job_callbacks` to bind progress/console/completion to widgets safely.
"""

import threading
import time
import typing
from typing import Callable, Optional

from gi.repository import GLib

from bundled.constants import DONE
from core import JobCallbacks
from core.debug_log import correlation_seq, log_event, preview_text, verbose
from core.oom_choice import OomChoiceRequest

_PROGRESS_LOG_STEP = 0.05
_last_progress_log = -1.0


def reset_progress_log() -> None:
    global _last_progress_log
    _last_progress_log = -1.0


def idle_on_main(func: Callable, *args: typing.Any, **kwargs: typing.Any) -> None:
    """Schedule ``func(*args, **kwargs)`` once on the GTK main loop."""

    def invoke():
        func(*args, **kwargs)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(invoke)


def _should_log_progress(fraction: float) -> bool:
    del fraction
    return verbose()


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

    def wrapper(*args: typing.Any, **kwargs: typing.Any):
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
        log_event(
            "dispatch",
            "dispatch_scheduled",
            level="trace",
            sequence=seq,
            callback=label,
            arguments=preview,
        )

        def invoke():
            latency_ms = (time.monotonic() - scheduled_at) * 1000.0
            log_event(
                "dispatch",
                "dispatch_invoked",
                level="trace",
                sequence=seq,
                callback=label,
                arguments=preview,
                latency_ms=round(latency_ms, 3),
            )
            func(*args, **kwargs)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(invoke)

    return wrapper


def latest_main_thread(func: Callable) -> Callable:
    """Marshal only the newest pending call to ``func`` onto the main loop.

    Progress producers can run much faster than GTK can paint. Keeping one
    pending source bounds main-loop work while retaining the newest value; a
    call arriving while the handler runs schedules the next source normally.
    """
    lock = threading.Lock()
    pending = False
    latest_args: tuple[typing.Any, ...] = ()
    latest_kwargs: dict[str, typing.Any] = {}

    def wrapper(*args: typing.Any, **kwargs: typing.Any) -> None:
        nonlocal pending, latest_args, latest_kwargs
        with lock:
            latest_args = args
            latest_kwargs = kwargs
            if pending:
                return
            pending = True

        def invoke() -> bool:
            nonlocal pending
            with lock:
                call_args = latest_args
                call_kwargs = latest_kwargs
                pending = False
            func(*call_args, **call_kwargs)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(invoke)

    return wrapper


class _ConsoleBatch:
    """Join adjacent text while keeping DONE and terminal events ordered."""

    def __init__(self, func: Callable[[str], None]) -> None:
        self._func = func
        self._lock = threading.RLock()
        self._pending: list[str] | None = None

    def append(self, text: str) -> None:
        with self._lock:
            if self._pending is not None:
                self._pending.append(text)
                return
            batch = [text]
            self._pending = batch

            def invoke() -> None:
                with self._lock:
                    if self._pending is batch:
                        self._pending = None
                    messages = tuple(batch)
                parts: list[str] = []
                for message in messages:
                    # ConsoleView interprets standalone DONE using its open-line
                    # state. Joining it with ordinary text would bypass that gate.
                    if message == DONE:
                        if parts:
                            self._deliver_parts(parts)
                            parts.clear()
                        self._func(message)
                    else:
                        parts.append(message)
                if parts:
                    self._deliver_parts(parts)

            main_thread(invoke)()

    def _deliver_parts(self, parts: list[str]) -> None:
        text = "".join(parts)
        if text == DONE:
            # Ordinary fragments can happen to spell the sentinel; retain their
            # original calls so ConsoleView does not reinterpret them as DONE.
            for part in parts:
                self._func(part)
        else:
            self._func(text)

    def boundary(self, func: Callable) -> Callable:
        scheduled = main_thread(func)

        def wrapper(*args: typing.Any, **kwargs: typing.Any) -> None:
            with self._lock:
                # The already scheduled idle retains the old batch. Later text
                # must get its own idle after this completion/error/choice event.
                self._pending = None
                scheduled(*args, **kwargs)

        return wrapper


def gtk_job_callbacks(
    on_progress: Optional[Callable[[float], None]] = None,
    on_console: Optional[Callable[[str], None]] = None,
    on_complete: Optional[Callable[[], None]] = None,
    on_stopped: Optional[Callable[[], None]] = None,
    on_error: Optional[Callable[[BaseException], None]] = None,
    on_oom_choice: Optional[Callable[[OomChoiceRequest], None]] = None,
) -> JobCallbacks:
    """Build :class:`JobCallbacks` whose handlers run on the GTK main loop."""
    console = _ConsoleBatch(on_console) if on_console else None
    boundary = console.boundary if console else main_thread
    return JobCallbacks(
        on_progress=latest_main_thread(on_progress) if on_progress else None,
        on_console=console.append if console else None,
        on_complete=boundary(on_complete) if on_complete else None,
        on_stopped=boundary(on_stopped) if on_stopped else None,
        on_error=boundary(on_error) if on_error else None,
        on_oom_choice=boundary(on_oom_choice) if on_oom_choice else None,
    )
