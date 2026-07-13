"""Reusable responsive two-column options layout.

The main separation surface and the embedded Ensemble / Audio Tools pages all
share the same shape: a set of :class:`Adw.PreferencesGroup` panels distributed
across two equal-width columns that collapse into a single stacked column when
the window gets narrow. Centralising the construction here keeps every page's
layout (margins, spacing, clamp width, scroller minimum width and the
wide/narrow flip) identical, and lets :class:`ui.window.MainWindow` drive
every page's ``columns_box`` from one breakpoint handler.
"""

from typing import Optional

from gi.repository import Adw, Gtk

from ..spacing import set_inset
from .log_panel import LogPanel

#: Clamp width shared by every two-column options surface.
DEFAULT_MAX_WIDTH = 1180
#: Breathing room between the last preference row and the floating log panel.
_OPTIONS_CLEARANCE_GAP = 8


def set_options_bottom_clearance(columns_box: Gtk.Box, clearance_px: int) -> None:
    """Reserve scroll space below option columns for the floating log panel."""
    columns_box.set_margin_bottom(clearance_px + _OPTIONS_CLEARANCE_GAP)


def make_column() -> Gtk.Box:
    """Build one vertical options column (top-aligned, expanding)."""
    return Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=18,
        hexpand=True,
        valign=Gtk.Align.START,
    )


def build_columns_box(left_groups=(), right_groups=()):
    """Build the horizontal ``columns_box`` and its two child columns.

    ``left_groups`` / ``right_groups`` are appended to the start/end columns in
    order. Returns ``(columns_box, col_start, col_end)``; callers keep the
    column references when they need to repopulate dynamically (separation), and
    register ``columns_box`` so the breakpoint can flip its orientation.
    """
    col_start = make_column()
    col_end = make_column()
    for group in left_groups:
        col_start.append(group)
    for group in right_groups:
        col_end.append(group)

    columns_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
    # Homogeneous keeps both columns the same width regardless of content, so
    # the split point doesn't jump when the active panel changes height.
    columns_box.set_homogeneous(True)
    # Expand horizontally so the enclosing Adw.Clamp stretches the box to its
    # clamp width instead of allocating the (content-driven) natural width and
    # centring it. Without this, each page's column width tracks the longest
    # row it contains (long file paths / model names), so the split point and
    # card widths differ from view to view. Expanding pins every page to the
    # same clamp-bounded width for a consistent layout.
    columns_box.set_hexpand(True)
    set_inset(columns_box, top=18, bottom=18, start=12, end=12)
    columns_box.append(col_start)
    columns_box.append(col_end)
    return columns_box, col_start, col_end


def wrap_options_scroller(
    columns_box: Gtk.Widget,
    maximum_size: int = DEFAULT_MAX_WIDTH,
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
    clamp = Adw.Clamp(child=columns_box, maximum_size=maximum_size)
    # Pin the tightening threshold to the maximum size. With the default (lower)
    # threshold, any window between the threshold and ``maximum_size`` lands in
    # Adw.Clamp's easing region, where the child is allocated less than the
    # available width by an amount that depends on the child's own content
    # (natural/min) width. That makes each page's columns render at a different
    # width based on its longest row. Raising the threshold to the maximum
    # removes the easing band: below ``maximum_size`` the child fills the full
    # available width (consistent across every page), and it is still clamped
    # and centred once the window grows past ``maximum_size``.
    clamp.set_tightening_threshold(maximum_size)
    clamp.set_vexpand(True)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_propagate_natural_height(False)
    scroller.set_vexpand(True)
    scroller.set_hexpand(True)
    scroller.set_min_content_width(360)
    scroller.set_child(clamp)

    page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    page.set_vexpand(True)
    page.set_hexpand(True)
    page.append(scroller)
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
