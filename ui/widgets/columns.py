"""Reusable responsive two-column options layout.

The main separation surface and the embedded Ensemble / Audio Tools pages all
share the same shape: a set of :class:`Adw.PreferencesGroup` panels distributed
across two equal-width columns that collapse into a single stacked column when
the window gets narrow. Centralising the construction here keeps every page's
layout (margins, spacing, clamp width, scroller minimum width and the
wide/narrow flip) identical, and lets :class:`ui.window.MainWindow` drive
every page's ``columns_box`` from one breakpoint handler.
"""

import typing
from typing import Optional

from gi.repository import Adw, Gtk

from ..template import load_builder, object_from_builder
from .log_panel import LogPanel

# Preferences pages use a 640sp clamp inside a 700sp dialog, so the groups sit
# 30sp in from each edge, and ease in across a 40sp band (tightening 600).
# The main window's default width is 1040; the same edge gap and band keep
# Separation, Ensemble, and Audio Tools off the window edges.
_PREFERENCES_EDGE_GAP = 30
_PREFERENCES_TIGHTENING_BAND = 40
_DEFAULT_WINDOW_WIDTH = 1040
#: Maximum width in sp, shared by every two-column options surface.
DEFAULT_MAX_WIDTH = _DEFAULT_WINDOW_WIDTH - 2 * _PREFERENCES_EDGE_GAP
#: Width in sp where the clamp starts easing toward ``DEFAULT_MAX_WIDTH``.
DEFAULT_TIGHTENING = DEFAULT_MAX_WIDTH - _PREFERENCES_TIGHTENING_BAND
#: Breathing room between the last preference row and the floating log panel.
_OPTIONS_CLEARANCE_GAP = 8


def set_options_bottom_clearance(columns_box: Gtk.Widget, clearance_px: int) -> None:
    """Reserve scroll space below option columns for the floating log panel."""
    columns_box.set_margin_bottom(clearance_px + _OPTIONS_CLEARANCE_GAP)


def build_columns_box(left_groups: typing.Any = (), right_groups: typing.Any = ()):
    """Build the horizontal ``columns_box`` and its two child columns.

    ``left_groups`` / ``right_groups`` are appended to the start/end columns in
    order. Returns ``(columns_box, col_start, col_end)``; callers keep the
    column references when they need to repopulate dynamically (separation), and
    register ``columns_box`` so the breakpoint can flip its orientation.
    """
    builder = load_builder("columns")
    columns_box = object_from_builder(builder, "columns_box", Gtk.Box)
    col_start = object_from_builder(builder, "col_start", Gtk.Box)
    col_end = object_from_builder(builder, "col_end", Gtk.Box)
    for group in left_groups:
        col_start.append(group)
    for group in right_groups:
        col_end.append(group)

    return columns_box, col_start, col_end


def wrap_options_scroller(
    columns_box: Gtk.Widget,
    maximum_size: int = DEFAULT_MAX_WIDTH,
    tightening_threshold: int = DEFAULT_TIGHTENING,
    bottom_inset: Optional[int] = None,
) -> Gtk.Box:
    """Wrap a ``columns_box`` in the shared clamp + vertical scroller.

    Returns a vertical ``Gtk.Box`` that fills the :class:`Adw.ViewStack` page
    slot; the scroller is its only child and also expands vertically.

    With a horizontal policy of ``NEVER`` the scroller would otherwise report a
    near-zero minimum width, letting the window shrink below the content and
    clip it, so a sane minimum is pinned (single-column content reflows to fit).

    ``bottom_inset`` adds scrollable padding below the option groups so the
    last rows are not hidden behind the floating log panel overlay. When omitted,
    the inset is derived from :meth:`LogPanel.default_bottom_inset`.

    ``propagate_natural_height`` stays off so dynamically reparented option
    groups (the separation page rebuilds its columns on method change) still
    receive a usable viewport height inside :class:`Adw.ViewStack`.
    """
    if bottom_inset is None:
        bottom_inset = LogPanel.default_bottom_inset()
    if bottom_inset:
        set_options_bottom_clearance(columns_box, bottom_inset)
    builder = load_builder("options_scroller")
    page = object_from_builder(builder, "options_page", Gtk.Box)
    clamp = object_from_builder(builder, "options_clamp", Adw.Clamp)
    clamp.set_child(columns_box)
    clamp.set_maximum_size(maximum_size)
    # Same 40sp easing band as the preferences page clamp. A custom cap shorter
    # than the band stays valid by tightening at the cap itself.
    clamp.set_tightening_threshold(min(maximum_size, tightening_threshold))
    return page


def options_scroller(page: Gtk.Widget) -> Gtk.ScrolledWindow:
    """Return the ``Gtk.ScrolledWindow`` inside a :func:`wrap_options_scroller` page."""
    if isinstance(page, Gtk.ScrolledWindow):
        return page
    child = page.get_first_child()
    if isinstance(child, Gtk.ScrolledWindow):
        return child
    raise TypeError(f"expected options page from wrap_options_scroller, got {type(page)!r}")


def set_columns_narrow(columns_box: Gtk.Box, narrow: bool) -> None:
    """Flip a ``columns_box`` between stacked (narrow) and side-by-side (wide).

    Narrow drops homogeneity so groups size by their own natural height instead
    of being forced to equal heights in a single stacked column.
    """
    if narrow:
        columns_box.set_homogeneous(False)
        columns_box.set_orientation(Gtk.Orientation.VERTICAL)
    else:
        columns_box.set_orientation(Gtk.Orientation.HORIZONTAL)
        columns_box.set_homogeneous(True)
