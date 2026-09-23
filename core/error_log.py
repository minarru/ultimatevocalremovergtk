"""Process-wide error reports, independent of a GUI or its lifetime."""

from __future__ import annotations

import threading
from collections.abc import Callable

from bundled.error_handling import error_text


class ErrorLogStore:
    """Atomic storage with invalidation callbacks delivered outside its lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = ""
        self._subscribers: dict[object, Callable[[], None]] = {}

    def get(self) -> str:
        with self._lock:
            return self._text

    def subscribe(self, on_changed: Callable[[], None]) -> Callable[[], None]:
        token = object()
        with self._lock:
            self._subscribers[token] = on_changed

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.pop(token, None)

        return unsubscribe

    def set(self, text: str) -> None:
        with self._lock:
            self._text = text or ""
            callbacks = tuple(self._subscribers.values())
        self._notify(callbacks, text)

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._text = f"{self._text.rstrip()}\n\n---\n\n{text.lstrip()}" if self._text else text
            complete = self._text
            callbacks = tuple(self._subscribers.values())
        self._notify(callbacks, complete)

    @staticmethod
    def _notify(callbacks: tuple[Callable[[], None], ...], text: str) -> None:
        from core.debug_log import debug, preview_text

        for callback in callbacks:
            callback()
        if text:
            debug("error", f"set_error_log {preview_text(text, max_len=120)!r}")


_STORE = ErrorLogStore()


def get_error_log() -> str:
    return _STORE.get()


def set_error_log(text: str) -> None:
    _STORE.set(text)


def append_error_log(text: str) -> None:
    _STORE.append(text)


def subscribe_error_log(on_changed: Callable[[], None]) -> Callable[[], None]:
    return _STORE.subscribe(on_changed)


def log_error(process_method: str, exception: BaseException, *, context: str = "") -> str:
    """Format ``exception`` like UVR and store it as the current error log.

    Thread-safe so worker threads can record errors directly; returns the
    formatted text. When a prior error is already stored, the new report is
    appended rather than replacing it.
    """
    import traceback

    from core.debug_log import log_event

    if not context:
        from core.error_context import format_error_context

        context = format_error_context()
    formatted = error_text(process_method, exception, context=context)
    append_error_log(formatted)
    log_event(
        "error",
        "ui_error",
        level="error",
        process_method=process_method,
        context=context,
        error_type=type(exception).__name__,
        error=str(exception),
        traceback="".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        ),
    )
    return formatted
