"""Opt-in assertion that direct GTK suites use the private test compositor."""

from __future__ import annotations

import os

_reported = False


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
    if not _reported:
        print(f"Private GTK display asserted: {display_type} {display_name}", flush=True)
        _reported = True
