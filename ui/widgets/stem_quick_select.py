"""Shared compact quick selection for the page and Save Stems dialog."""

from collections.abc import Callable

from gi.repository import Adw, Gtk

from ..stem_controls import StemControlsSnapshot
from ..template import load_builder, object_from_builder


class StemQuickSelect:
    def __init__(self, on_selected: Callable[[str, int], None]):
        self._on_selected = on_selected
        self._rendering = False
        self.items: tuple[tuple[str, str], ...] = ()
        self.revision = -1
        self.badges: dict[str, Gtk.Image] = {}
        self.buttons: dict[str, Gtk.ToggleButton] = {}
        builder = load_builder("stem-quick-select")
        self.widget = object_from_builder(builder, "holder", Adw.BreakpointBin)
        if hasattr(Adw, "ToggleGroup"):
            self.group = Adw.ToggleGroup(can_shrink=True)
            self.group.connect("notify::active-name", self._quick_changed)
        else:
            self.group = Gtk.Box(css_classes=["linked"])
        self.group.add_css_class("stem-quick-group")
        self.group.set_overflow(Gtk.Overflow.VISIBLE)
        self.widget.set_child(self.group)
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 420sp"))
        breakpoint.add_setter(self.group, "orientation", Gtk.Orientation.VERTICAL)
        self.group.connect("notify::orientation", self._resize)
        self.widget.add_breakpoint(breakpoint)

    def render(self, snapshot: StemControlsSnapshot) -> None:
        self._rendering = True
        try:
            self._render(snapshot)
        finally:
            self._rendering = False

    def _render(self, snapshot: StemControlsSnapshot) -> None:
        items = snapshot.presets
        tooltips = dict(snapshot.tooltips)
        self.group.set_visible(bool(items))
        if items != self.items or snapshot.revision != self.revision:
            self.items = items
            self.revision = snapshot.revision
            if isinstance(self.group, Gtk.Box):
                while (child := self.group.get_first_child()) is not None:
                    self.group.remove(child)
            else:
                self.group.remove_all()
            self.badges.clear()
            self.buttons.clear()
            for ident, label in items:
                builder = load_builder("stem-quick-select")
                button = object_from_builder(builder, "selected", Gtk.ToggleButton)
                object_from_builder(builder, "label", Gtk.Label).set_label(label)
                self.badges[ident] = object_from_builder(builder, "badge", Gtk.Image)
                child = button.get_child()
                if child is not None:
                    child.set_tooltip_text(tooltips.get(ident))
                if isinstance(self.group, Gtk.Box):
                    button.connect("clicked", self._preset_clicked, ident, snapshot.revision)
                    self.buttons[ident] = button
                    self.group.append(button)
                else:
                    child = button.get_child()
                    button.set_child(None)
                    toggle = Adw.Toggle(name=ident, label=label)
                    toggle.set_child(child)
                    self.group.add(toggle)
                    # Adw owns the toggle button; allow its corner overlay to
                    # extend beyond the button without clipping the badge.
                    if child is not None and (button_parent := child.get_parent()) is not None:
                        button_parent.set_overflow(Gtk.Overflow.VISIBLE)
        defaults = frozenset(c.id for c in snapshot.choices if c.route.selected_by_default)
        active = None
        if not snapshot.review_required:
            for ident, _label in items:
                if ident == "all" and snapshot.mode == "derived":
                    continue
                selected = defaults if ident == "all" else frozenset((ident,))
                if snapshot.selected_ids == selected:
                    active = ident
                    break
        if not isinstance(self.group, Gtk.Box):
            self.group.set_active_name(active)
        for ident, badge in self.badges.items():
            badge.set_opacity(1 if ident == active else 0)
        for ident, button in self.buttons.items():
            button.set_active(ident == active)
        self._resize()

    def _resize(self, *_args: object) -> None:
        # Measure after the orientation setter: breakpoint apply/unapply signals
        # still expose the previous layout and can leave a stale minimum height.
        width = self.group.get_width() or -1
        height = self.group.measure(Gtk.Orientation.VERTICAL, width)[0]
        self.widget.set_size_request(180, max(28, height))

    def _quick_changed(self, *_args: object) -> None:
        if self._rendering or isinstance(self.group, Gtk.Box):
            return
        ident = self.group.get_active_name()
        if ident is not None:
            self._on_selected(ident, self.revision)

    def _preset_clicked(self, _button: Gtk.Button, ident: str, revision: int) -> None:
        if not self._rendering:
            self._on_selected(ident, revision)
