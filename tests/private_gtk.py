"""Opt-in assertion that direct GTK suites use the private test compositor."""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Callable

_reported = False
_skip_guard_installed = False

_DISPLAY_SKIP_TERMS = (
    "display",
    "gtk",
    "gdk",
    "wayland",
    "compositor",
    "x11",
    "xvfb",
    "broadway",
    "libadwaita",
)


def _is_display_skip(reason: object) -> bool:
    folded = str(reason).casefold()
    return any(term in folded for term in _DISPLAY_SKIP_TERMS)


def _guarded_add_skip(
    original: Callable[..., None],
) -> Callable[..., None]:
    def add_skip(result: Any, test: Any, reason: object) -> None:
        if os.getenv("UVR_REQUIRE_PRIVATE_GTK") != "1" or not _is_display_skip(reason):
            original(result, test, reason)
            return
        try:
            raise AssertionError(
                f"UVR_REQUIRE_PRIVATE_GTK=1 forbids display-related SkipTest: {reason}"
            )
        except AssertionError:
            result.addFailure(test, sys.exc_info())

    return add_skip


def _install_skip_guard() -> None:
    """Turn only display-related unittest skips into failures for this process."""
    global _skip_guard_installed
    if _skip_guard_installed:
        return
    unittest.TestResult.addSkip = _guarded_add_skip(unittest.TestResult.addSkip)  # type: ignore[method-assign]
    unittest.TextTestResult.addSkip = _guarded_add_skip(  # type: ignore[method-assign]
        unittest.TextTestResult.addSkip
    )
    _skip_guard_installed = True


def require_private_gtk() -> None:
    """Fail closed when a display-backed suite requests private GTK evidence."""
    if os.getenv("UVR_REQUIRE_PRIVATE_GTK") != "1":
        return

    global _reported

    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    Gtk.init()
    display = Gdk.Display.get_default()
    if display is None:
        raise AssertionError("UVR_REQUIRE_PRIVATE_GTK=1 but Gdk.Display is unavailable")
    display_type = type(display).__name__
    display_name = display.get_name()
    if display_type != "GdkWaylandDisplay" or display_name != "codex-gtk":
        raise AssertionError(
            "UVR_REQUIRE_PRIVATE_GTK=1 requires GdkWaylandDisplay codex-gtk; "
            f"got {display_type} {display_name!r}"
        )
    _install_skip_guard()
    if not _reported:
        print(f"Private GTK display asserted: {display_type} {display_name}", flush=True)
        _reported = True
