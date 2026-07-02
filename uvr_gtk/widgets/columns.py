"""Reusable responsive two-column options layout.

The main separation surface and the embedded Ensemble / Audio Tools pages all
share the same shape: a set of :class:`Adw.PreferencesGroup` panels distributed
across two equal-width columns that collapse into a single stacked column when
the window gets narrow. Centralising the construction here keeps every page's
layout (margins, spacing, clamp width, scroller minimum width and the
wide/narrow flip) identical, and lets :class:`uvr_gtk.window.MainWindow` drive
every page's ``columns_box`` from one breakpoint handler.
"""

from typing import Optional

from gi.repository import Adw, Gtk

from .log_panel import LogPanel

#: Clamp width shared by every two-column options surface.
DEFAULT_MAX_WIDTH = 1180


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
    columns_box.set_margin_top(18)
    columns_box.set_margin_bottom(18)
    columns_box.set_margin_start(12)
    columns_box.set_margin_end(12)
    columns_box.append(col_start)
    columns_box.append(col_end)
    return columns_box, col_start, col_end


def wrap_options_scroller(
    columns_box: Gtk.Widget,
    maximum_size: int = DEFAULT_MAX_WIDTH,
    bottom_inset: Optional[int] = None,
) -> Gtk.ScrolledWindow:
    """Wrap a ``columns_box`` in the shared clamp + vertical scroller.

    With a horizontal policy of ``NEVER`` the scroller would otherwise report a
    near-zero minimum width, letting the window shrink below the content and
    clip it, so a sane minimum is pinned (single-column content reflows to fit).

    ``bottom_inset`` adds scrollable padding below the option groups so the
  last rows are not hidden behind the floating log panel overlay. When omitted,
  the inset is derived from :meth:`LogPanel.default_bottom_inset`.
    """
    if bottom_inset is None:
        bottom_inset = LogPanel.default_bottom_inset()
    if bottom_inset:
        columns_box.set_margin_bottom(columns_box.get_margin_bottom() + bottom_inset)
    clamp = Adw.Clamp(child=columns_box, maximum_size=maximum_size)
    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroller.set_propagate_natural_height(True)
    scroller.set_vexpand(True)
    scroller.set_min_content_width(360)
    scroller.set_child(clamp)
    return scroller


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
