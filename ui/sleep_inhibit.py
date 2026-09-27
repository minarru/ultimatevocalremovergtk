"""Keep the session from suspending while a run is processing.

Long batch or ensemble runs can outlast the desktop's idle-suspend timer, which
freezes the worker mid-inference. :class:`SleepInhibitor` wraps
``Gtk.Application.inhibit`` (session manager or the desktop portal) and only
blocks suspend: the screen may still blank or lock.
"""

from __future__ import annotations

from typing import Callable

from gi.repository import Gtk

from core.debug_log import log_event


class SleepInhibitor:
    """One suspend inhibition, acquired and released idempotently."""

    def __init__(
        self,
        application: Callable[[], Gtk.Application | None],
        window: Callable[[], Gtk.Window | None],
    ) -> None:
        self._application = application
        self._window = window
        self._app: Gtk.Application | None = None
        self._cookie = 0

    @property
    def active(self) -> bool:
        return self._cookie != 0

    def acquire(self, reason: str) -> None:
        if self._cookie:
            return
        try:
            app = self._application()
            if app is None:
                return
            cookie = app.inhibit(self._window(), Gtk.ApplicationInhibitFlags.SUSPEND, reason)
        except Exception as exc:  # inhibiting is best effort; never block a run
            log_event("ui", "sleep_inhibit_failed", level="warning", error=str(exc))
            return
        # 0 means the session manager or portal declined the request.
        log_event("ui", "sleep_inhibit", granted=bool(cookie))
        if cookie:
            self._app = app
            self._cookie = cookie

    def release(self) -> None:
        app, cookie = self._app, self._cookie
        self._app, self._cookie = None, 0
        if app is None or not cookie:
            return
        try:
            app.uninhibit(cookie)
        except Exception as exc:
            log_event("ui", "sleep_uninhibit_failed", level="warning", error=str(exc))
