"""Stem-only save controls backed by ``Adw.ToggleGroup``.

Replaces mutually exclusive "Only" switches / combo rows with a horizontal
``Adw.ToggleGroup`` under the "Save stems" group header.
"""

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from gi.repository import Adw, Gtk

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    DRUM_STEM,
    INST_STEM,
    OTHER_STEM,
    PRIMARY_STEM,
    SECONDARY_STEM,
    VOCAL_STEM,
)

from ..spacing import set_inset
from ..help_text import (
    STEM_ONLY_ALL_HINT,
    primary_stem_only_tooltip,
    secondary_stem_only_tooltip,
    stem_only_tooltip,
)

_TOGGLE_ALL = "all"

# Stable display order for "<stem> Only" entries.
_STEM_ONLY_ORDER = (INST_STEM, VOCAL_STEM, BASS_STEM, DRUM_STEM, OTHER_STEM)

STEM_ONLY_ICONS: Dict[str, str] = {
    VOCAL_STEM: "person-talking-symbolic",
    INST_STEM: "bullhorn-symbolic",
}
ALL_STEMS_ICON = "ungroup-symbolic"


def stem_only_icon(stem: Optional[str]) -> Optional[str]:
    if not stem:
        return None
    return STEM_ONLY_ICONS.get(stem)


def _stem_only_rank(stem: str) -> int:
    if stem in _STEM_ONLY_ORDER:
        return _STEM_ONLY_ORDER.index(stem)
    return len(_STEM_ONLY_ORDER) + 1


@dataclass(frozen=True)
class StemOnlyOption:
    name: str
    tooltip: str
    display_label: str
    icon_name: Optional[str]
    settings_key: Optional[str]

def build_stem_only_options(
    *,
    primary_stem: Optional[str],
    secondary_stem: Optional[str],
    primary_key: str,
    secondary_key: str,
) -> List[StemOnlyOption]:
    """Build toggle entries for All Stems + each stem's Only option."""
    options = [
        StemOnlyOption(_TOGGLE_ALL, STEM_ONLY_ALL_HINT, ALL_STEMS, ALL_STEMS_ICON, None),
    ]
    if primary_stem and secondary_stem:
        entries = [
            (primary_stem, primary_key),
            (secondary_stem, secondary_key),
        ]
        entries.sort(key=lambda entry: _stem_only_rank(entry[0]))
        for stem, key in entries:
            options.append(
                StemOnlyOption(
                    key,
                    stem_only_tooltip(stem),
                    stem,
                    stem_only_icon(stem),
                    key,
                )
            )
    else:
        options.append(
            StemOnlyOption(
                primary_key,
                primary_stem_only_tooltip(),
                PRIMARY_STEM,
                None,
                primary_key,
            )
        )
        options.append(
            StemOnlyOption(
                secondary_key,
                secondary_stem_only_tooltip(),
                SECONDARY_STEM,
                None,
                secondary_key,
            )
        )
    return options


class StemOnlyControls:
    """Compact ``Adw.ToggleGroup`` for exclusive stem-only selection."""

    def __init__(self, *, on_changed: Optional[Callable[[], None]] = None):
        self.container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.container.add_css_class("uvr-stem-only-row")
        set_inset(self.container, bottom=6)
        self.container.set_halign(Gtk.Align.FILL)
        self.container.set_hexpand(True)

        self.group = Adw.ToggleGroup()
        self.group.set_homogeneous(True)
        self.group.set_can_shrink(False)
        self.group.set_hexpand(True)
        self.group.set_halign(Gtk.Align.FILL)
        self.container.append(self.group)

        self._on_changed = on_changed
        self._loading = False
        self._choice_keys: Dict[str, Optional[str]] = {}
        self.group.connect("notify::active-name", self._on_active_name)

    @property
    def widget(self) -> Gtk.Box:
        return self.container

    def set_visible(self, visible: bool) -> None:
        self.container.set_visible(visible)

    def rebuild(self, options: List[StemOnlyOption]) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self.group.remove_all()
            self._choice_keys = {}
            for option in options:
                toggle = Adw.Toggle()
                toggle.set_name(option.name)
                toggle.set_label(option.display_label)
                toggle.set_tooltip(option.tooltip)
                if option.icon_name:
                    toggle.set_icon_name(option.icon_name)
                self.group.add(toggle)
                self._choice_keys[option.name] = option.settings_key
        finally:
            self._loading = was_loading

    def sync_from_settings(self, settings, primary_key: str, secondary_key: str) -> None:
        primary_on = bool(settings.get(primary_key))
        secondary_on = bool(settings.get(secondary_key))
        if primary_on and not secondary_on:
            name = primary_key
        elif secondary_on and not primary_on:
            name = secondary_key
        else:
            name = _TOGGLE_ALL

        was_loading = self._loading
        self._loading = True
        try:
            if self.group.get_toggle_by_name(name) is not None:
                self.group.set_active_name(name)
            elif self.group.get_n_toggles() > 0:
                self.group.set_active_name(_TOGGLE_ALL)
        finally:
            self._loading = was_loading

    def persist_to_settings(self, settings, primary_key: str, secondary_key: str) -> None:
        name = self.group.get_active_name() or _TOGGLE_ALL
        only_key = self._choice_keys.get(name)
        settings.set(primary_key, only_key == primary_key)
        settings.set(secondary_key, only_key == secondary_key)

    def _on_active_name(self, *_args) -> None:
        if self._loading or self._on_changed is None:
            return
        self._on_changed()
