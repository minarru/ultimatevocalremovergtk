"""Allocation helpers for the floating log's fixed widths and stable wrapping."""

from collections.abc import Callable
from typing import cast

from gi.repository import Adw, Gtk


class PanelClamp(Gtk.Box):
    """Clamp layout whose transparent side areas are not pointer targets."""

    __gtype_name__ = "UvrPanelClamp"

    def get_child(self) -> Gtk.Widget | None:
        return self.get_first_child()

    def _clamp_layout(self) -> Adw.ClampLayout:
        return cast(Adw.ClampLayout, self.get_layout_manager())

    def get_maximum_size(self) -> int:
        return self._clamp_layout().get_maximum_size()

    def set_maximum_size(self, size: int) -> None:
        self._clamp_layout().set_maximum_size(size)

    def set_tightening_threshold(self, size: int) -> None:
        self._clamp_layout().set_tightening_threshold(size)

    def do_contains(self, x: float, y: float) -> bool:
        child = self.get_child()
        if child is None:
            return False
        valid, bounds = child.compute_bounds(self)
        return bool(
            valid
            and bounds.get_x() <= x < bounds.get_x() + bounds.get_width()
            and bounds.get_y() <= y < bounds.get_y() + bounds.get_height()
        )


class PanelLayout(Gtk.BinLayout):
    """Observe available overlay space when GTK allocates, without a frame poll."""

    def __init__(self, on_size: Callable[[int, int], None]):
        super().__init__()
        self._on_size = on_size

    def do_allocate(self, widget: Gtk.Widget, width: int, height: int, baseline: int) -> None:
        self._on_size(width, height)
        Gtk.BinLayout.do_allocate(self, widget, width, height, baseline)


class StableLogLayout(Gtk.LayoutManager):
    """Wrap at the expanded width; clip while the surrounding panel animates."""

    def __init__(self):
        super().__init__()
        self._text_width = 530

    def set_text_width(self, width: int) -> None:
        if width != self._text_width:
            self._text_width = width
            self.layout_changed()

    def do_measure(
        self, widget: Gtk.Widget, orientation: Gtk.Orientation, for_size: int
    ) -> tuple[int, int, int, int]:
        child = widget.get_first_child()
        if child is None or orientation == Gtk.Orientation.HORIZONTAL:
            return 0, 0, -1, -1
        minimum, natural, min_baseline, nat_baseline = child.measure(orientation, self._text_width)
        return minimum, natural, min_baseline, nat_baseline

    def do_allocate(self, widget: Gtk.Widget, width: int, height: int, baseline: int) -> None:
        child = widget.get_first_child()
        if child is not None:
            child.allocate(self._text_width, height, baseline, None)
