"""Header input picker shared by the listening tools.

One input shows the tool's title with the file name under it; several swap in a
drop-down of the inputs.
"""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Adw, GObject, Gtk, Pango

from ..template import load_builder, object_from_builder


def _input_factory(*, ellipsize: bool) -> Gtk.SignalListItemFactory:
    """Input names for the header picker; the button ellipsizes, the list does not."""
    factory = Gtk.SignalListItemFactory()

    def setup(_factory: Gtk.SignalListItemFactory, item: GObject.Object) -> None:
        if not isinstance(item, Gtk.ListItem):
            return
        label = Gtk.Label(xalign=0)
        if ellipsize:
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_max_width_chars(28)
        item.set_child(label)

    def bind(_factory: Gtk.SignalListItemFactory, item: GObject.Object) -> None:
        if not isinstance(item, Gtk.ListItem):
            return
        label, name = item.get_child(), item.get_item()
        if isinstance(label, Gtk.Label) and isinstance(name, Gtk.StringObject):
            label.set_label(name.get_string())

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    return factory


class InputPicker:
    def __init__(self, title: str, names: Sequence[str], on_changed: Callable[[int], None]) -> None:
        builder = load_builder("input-picker")
        self.widget = object_from_builder(builder, "title_box", Gtk.Box)
        self.window_title = object_from_builder(builder, "window_title", Adw.WindowTitle)
        self.dropdown = object_from_builder(builder, "input_dropdown", Gtk.DropDown)
        self.window_title.set_title(title)
        if len(names) > 1:
            total = len(names)
            labels = [f"{name}  {i} of {total}" for i, name in enumerate(names, start=1)]
            self.dropdown.set_factory(_input_factory(ellipsize=True))
            self.dropdown.set_list_factory(_input_factory(ellipsize=False))
            self.dropdown.set_model(Gtk.StringList.new(labels))
            self.window_title.set_visible(False)
            self.dropdown.set_visible(True)
            self.dropdown.connect(
                "notify::selected", lambda dropdown, _pspec: on_changed(dropdown.get_selected())
            )
        elif names:
            self.window_title.set_subtitle(names[0])

    @property
    def selected(self) -> int:
        return self.dropdown.get_selected() if self.dropdown.get_visible() else 0


__all__ = ["InputPicker"]
