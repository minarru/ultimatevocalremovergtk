"""Wait for exact content allocations across native GTK display backends."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gi.repository import Gtk


def resize_window(window: Gtk.Window, width: int, height: int) -> None:
    """Present a window and wait for its requested content width.

    X11 default sizes include the client-side decoration extents, whereas
    Gtk.Widget.get_width() excludes them. Measure those extents after mapping
    so layout tests exercise the same content width on X11 and Wayland.
    """
    from gi.repository import GLib, GObject

    context = GLib.MainContext.default()
    deadline = time.monotonic() + 5
    # Measure a mapped window before requesting another size: during an X11
    # configure event the surface can already have its new dimensions while
    # the widget still retains its previous allocation.
    if not window.get_mapped() or window.get_width() <= 0:
        window.set_default_size(width, height)
        window.present()
        while not window.get_mapped() or window.get_width() <= 0:
            if time.monotonic() >= deadline:
                raise AssertionError("Window did not receive its first allocation")
            context.iteration(False)
            time.sleep(0.005)
    surface = window.get_surface()
    extra_width = extra_height = 0
    if surface is not None and GObject.type_name(type(surface)) == "GdkX11Toplevel":
        extra_width = surface.get_width() - window.get_width()
        extra_height = surface.get_height() - window.get_height()
    window.set_default_size(width + extra_width, height + extra_height)
    window.present()
    while time.monotonic() < deadline:
        context.iteration(False)
        if window.get_width() == width:
            return
        time.sleep(0.005)
    raise AssertionError(
        f"Window content did not reach {width}px: got {window.get_width()}x{window.get_height()}"
    )
