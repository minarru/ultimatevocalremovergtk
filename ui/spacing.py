"""Static widget insets via the Gtk margin API.

Use these helpers for dialogs, labels, and layout shells. Component padding,
colors, and radii stay in ``resources/style.css``.
"""

from gi.repository import Gtk

INSET_MD = 12
INSET_LG = 20


def set_inset(
    widget: Gtk.Widget,
    *,
    top: int = 0,
    bottom: int = 0,
    start: int = 0,
    end: int = 0,
) -> None:
    if top:
        widget.set_margin_top(top)
    if bottom:
        widget.set_margin_bottom(bottom)
    if start:
        widget.set_margin_start(start)
    if end:
        widget.set_margin_end(end)


def inset_all(widget: Gtk.Widget, px: int) -> None:
    set_inset(widget, top=px, bottom=px, start=px, end=px)


def inset_md(widget: Gtk.Widget) -> None:
    inset_all(widget, INSET_MD)


def inset_lg_sides_bottom(widget: Gtk.Widget) -> None:
    """Error dialog body: 20px sides and bottom, no top."""
    set_inset(widget, bottom=INSET_LG, start=INSET_LG, end=INSET_LG)
