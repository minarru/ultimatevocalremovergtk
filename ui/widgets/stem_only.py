"""Save-stems controls: exclusive export filter, MDX subset, and Demucs focus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple

from gi.repository import Adw, Gtk

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    DRUM_STEM,
    GUITAR_STEM,
    INST_STEM,
    NO_BASS_STEM,
    NO_DRUM_STEM,
    NO_GUITAR_STEM,
    NO_OTHER_STEM,
    NO_PIANO_STEM,
    NO_STEM,
    OTHER_STEM,
    PIANO_STEM,
    PRIMARY_STEM,
    SECONDARY_STEM,
    VOCAL_STEM,
    secondary_stem,
)

from core.model_stem_semantics import (
    VOCALS_OTHER_DISPLAY_OVERRIDES,
    stem_display_overrides,
)

from ..spacing import set_inset
from ..help_text import (
    DEMUCS_STEMS_SAVE_HELP,
    MDX_STEMS_HINT,
    QUICK_EXPORT_INSTRUMENTAL_HINT,
    QUICK_EXPORT_VOCALS_HINT,
    SAVE_STEM_ONLY_HELP,
    SAVE_STEMS_NO_MODEL_HELP,
    STEM_ONLY_ALL_HINT,
    primary_stem_only_tooltip,
    secondary_stem_only_tooltip,
)

_TOGGLE_ALL = "all"
_QUICK_ALL = "quick_all"
_QUICK_INSTRUMENTAL = "quick_instrumental"
_QUICK_VOCALS = "quick_vocals"
_FOCUS_INSTRUMENTAL = "focus_instrumental"
_FOCUS_VOCALS = "focus_vocals"

# Stable display order for "<stem> Only" entries.
_STEM_ONLY_ORDER = (INST_STEM, VOCAL_STEM, BASS_STEM, DRUM_STEM, OTHER_STEM)

STEM_ONLY_ICON_FALLBACK = "edit-none-symbolic"

STEM_ONLY_ICONS: Dict[str, str] = {
    VOCAL_STEM: "person-talking-symbolic",
    INST_STEM: "bullhorn-symbolic",
    BASS_STEM: "audio-input-microphone-symbolic",
    DRUM_STEM: "audio-speakers-symbolic",
    OTHER_STEM: "folder-music-symbolic",
    GUITAR_STEM: "audio-speakers-symbolic",
    PIANO_STEM: "folder-music-symbolic",
    "Speech": "person-talking-symbolic",
    "Music": "folder-music-symbolic",
    "Sfx": "speaker-3-symbolic",
    "Effects": "speaker-3-symbolic",
}
ALL_STEMS_ICON = "ungroup-symbolic"

# Lowercase / yaml aliases -> canonical UVR stem labels.
_STEM_ALIASES: Dict[str, str] = {
    "vocals": VOCAL_STEM,
    "vocal": VOCAL_STEM,
    "instrumental": INST_STEM,
    "inst": INST_STEM,
    "other": OTHER_STEM,
    "bass": BASS_STEM,
    "drums": DRUM_STEM,
    "guitar": GUITAR_STEM,
    "piano": PIANO_STEM,
    "speech": "Speech",
    "music": "Music",
    "sfx": "Sfx",
    "effects": "Effects",
}

# Friendlier export-filter labels for complement stems.
_COMPLEMENT_DISPLAY: Dict[str, str] = {
    f"{NO_STEM}{VOCAL_STEM}": INST_STEM,
    f"{NO_STEM}{VOCAL_STEM.lower()}": INST_STEM,
    "No vocals": INST_STEM,
    NO_OTHER_STEM: "Mix minus Other",
    f"{NO_STEM}{OTHER_STEM.lower()}": "Mix minus Other",
    f"{NO_STEM}{OTHER_STEM}": "Mix minus Other",
    NO_BASS_STEM: NO_BASS_STEM,
    f"{NO_STEM}{BASS_STEM.lower()}": NO_BASS_STEM,
    NO_DRUM_STEM: NO_DRUM_STEM,
    f"{NO_STEM}{DRUM_STEM.lower()}": NO_DRUM_STEM,
    NO_GUITAR_STEM: NO_GUITAR_STEM,
    NO_PIANO_STEM: NO_PIANO_STEM,
}

# Back-compat alias for tests and callers that referenced the old private dict.
_LEAD_VOCAL_PAIR_LABELS = VOCALS_OTHER_DISPLAY_OVERRIDES


def roformer_lead_vocal_label_overrides(model) -> Optional[Dict[str, str]]:
    """Return stem display overrides for the selected model."""
    return stem_display_overrides(model)


def canonical_stem_name(stem: Optional[str]) -> Optional[str]:
    """Normalize model/yaml stem strings to canonical UVR labels."""
    if not stem:
        return stem
    if stem in _STEM_ALIASES:
        return _STEM_ALIASES[stem]
    lowered = stem.lower()
    if lowered in _STEM_ALIASES:
        return _STEM_ALIASES[lowered]
    if stem.startswith(NO_STEM) and len(stem) > len(NO_STEM):
        suffix = stem[len(NO_STEM) :]
        canonical_suffix = _STEM_ALIASES.get(suffix.lower(), suffix)
        if canonical_suffix == suffix and suffix[:1].islower():
            canonical_suffix = suffix.title()
        return f"{NO_STEM}{canonical_suffix}"
    return stem


def stem_display_label(stem: Optional[str], *, overrides: Optional[Dict[str, str]] = None) -> str:
    """Human-readable label for toggles, chips, and export summaries."""
    if not stem:
        return ""
    if overrides:
        if stem in overrides:
            return overrides[stem]
        canonical = canonical_stem_name(stem) or stem
        if canonical in overrides:
            return overrides[canonical]
    canonical = canonical_stem_name(stem) or stem
    if canonical in _COMPLEMENT_DISPLAY:
        return _COMPLEMENT_DISPLAY[canonical]
    if stem in _COMPLEMENT_DISPLAY:
        return _COMPLEMENT_DISPLAY[stem]
    return canonical


def stem_only_tooltip(stem: str, *, overrides: Optional[Dict[str, str]] = None) -> str:
    return f"Export only {stem_display_label(stem, overrides=overrides)}; skip the other output file"


_QUICK_EXPORT_LABELS = {
    _QUICK_ALL: ALL_STEMS,
    _QUICK_INSTRUMENTAL: f"{INST_STEM} only",
    _QUICK_VOCALS: f"{VOCAL_STEM} only",
}


def stem_only_icon(stem: Optional[str]) -> Optional[str]:
    if not stem:
        return None
    canonical = canonical_stem_name(stem) or stem
    return STEM_ONLY_ICONS.get(canonical, STEM_ONLY_ICON_FALLBACK)


def _stem_only_rank(stem: str) -> int:
    if stem in _STEM_ONLY_ORDER:
        return _STEM_ONLY_ORDER.index(stem)
    return len(_STEM_ONLY_ORDER) + 1


def _section_label(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text, xalign=0)
    label.add_css_class("dim-label")
    label.add_css_class("uvr-stem-section-label")
    return label


def _labeled_row(caption: str, content: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.append(_section_label(caption))
    box.append(content)
    return box


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
    stem_label_overrides: Optional[Dict[str, str]] = None,
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
        if stem_label_overrides:
            entries.sort(
                key=lambda entry: (
                    0
                    if stem_display_label(entry[0], overrides=stem_label_overrides)
                    == VOCAL_STEM
                    else 1,
                    _stem_only_rank(entry[0]),
                )
            )
        else:
            entries.sort(key=lambda entry: _stem_only_rank(entry[0]))
        for stem, key in entries:
            display = stem_display_label(stem, overrides=stem_label_overrides)
            options.append(
                StemOnlyOption(
                    key,
                    stem_only_tooltip(stem, overrides=stem_label_overrides),
                    display,
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
        self.group.set_can_shrink(True)
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

    def active_export_label(self, primary_stem: Optional[str], secondary_stem: Optional[str]) -> str:
        name = self.group.get_active_name() or _TOGGLE_ALL
        if name == _TOGGLE_ALL:
            return "Exporting all outputs"
        toggle = self.group.get_toggle_by_name(name)
        if toggle is not None:
            return f"Exporting {toggle.get_label()} only"
        return "Exporting selected outputs"

    def expected_output_count(self) -> int:
        name = self.group.get_active_name() or _TOGGLE_ALL
        return 2 if name == _TOGGLE_ALL else 1

    def _on_active_name(self, *_args) -> None:
        if self._loading or self._on_changed is None:
            return
        self._on_changed()


def _make_chip(
    stem: str,
    *,
    tooltip: str,
    on_toggled: Callable,
    stem_label_overrides: Optional[Dict[str, str]] = None,
) -> Gtk.ToggleButton:
    label = stem_display_label(stem, overrides=stem_label_overrides)
    button = Gtk.ToggleButton(valign=Gtk.Align.CENTER)
    button.add_css_class("uvr-stem-chip")
    icon = stem_only_icon(stem)
    if icon:
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, valign=Gtk.Align.CENTER)
        content.append(Gtk.Image.new_from_icon_name(icon))
        content.append(Gtk.Label(label=label))
        button.set_child(content)
    else:
        button.set_label(label)
    button.set_tooltip_text(
        stem_only_tooltip(stem, overrides=stem_label_overrides) if stem_label_overrides else tooltip
    )
    button.connect("toggled", on_toggled)
    return button


class StemSubsetControls:
    """Multi-select stem chips with an All stems chip."""

    def __init__(self, *, on_changed: Optional[Callable[[], None]] = None):
        self._on_changed = on_changed
        self._loading = False
        self._stems: List[str] = []
        self._chips: Dict[str, Gtk.ToggleButton] = {}
        self._stem_label_overrides: Optional[Dict[str, str]] = None

        self.wrap = Adw.WrapBox()
        self.wrap.add_css_class("uvr-stem-subset")
        self.wrap.set_child_spacing(6)
        self.wrap.set_line_spacing(6)
        set_inset(self.wrap, top=2, bottom=6, start=0, end=0)

        self.container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.container.append(self.wrap)

    @property
    def widget(self) -> Gtk.Box:
        return self.container

    def rebuild(self, stems: List[str], *, stem_label_overrides: Optional[Dict[str, str]] = None) -> None:
        self._stems = list(stems)
        self._stem_label_overrides = stem_label_overrides
        child = self.wrap.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.wrap.remove(child)
            child = nxt
        self._chips = {}

        all_button = _make_chip(ALL_STEMS, tooltip=STEM_ONLY_ALL_HINT, on_toggled=self._on_all_toggled)
        all_button.add_css_class("uvr-stem-chip-all")
        self.wrap.append(all_button)
        self._chips[ALL_STEMS] = all_button

        for stem in stems:
            if stem == ALL_STEMS:
                continue
            chip = _make_chip(
                stem,
                tooltip=stem_only_tooltip(stem, overrides=self._stem_label_overrides),
                on_toggled=self._on_chip_toggled,
                stem_label_overrides=self._stem_label_overrides,
            )
            self.wrap.append(chip)
            self._chips[stem] = chip

    def set_selection(
        self,
        selected: Set[str],
        *,
        full_stems: List[str],
        highlight_all_when_empty: bool = True,
    ) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            stem_set = set(full_stems)
            if not selected:
                for stem, chip in self._chips.items():
                    if highlight_all_when_empty:
                        chip.set_active(stem == ALL_STEMS)
                    else:
                        chip.set_active(False)
            elif selected >= stem_set:
                for stem, chip in self._chips.items():
                    chip.set_active(stem == ALL_STEMS)
            else:
                if ALL_STEMS in self._chips:
                    self._chips[ALL_STEMS].set_active(False)
                for stem, chip in self._chips.items():
                    if stem == ALL_STEMS:
                        continue
                    chip.set_active(stem in selected)
        finally:
            self._loading = was_loading

    def selected_stems(self) -> List[str]:
        if self._chips.get(ALL_STEMS) and self._chips[ALL_STEMS].get_active():
            return []
        return [stem for stem in self._stems if self._chips.get(stem) and self._chips[stem].get_active()]

    def is_all_active(self) -> bool:
        return bool(self._chips.get(ALL_STEMS) and self._chips[ALL_STEMS].get_active())

    def _on_all_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._loading or not button.get_active():
            return
        was_loading = self._loading
        self._loading = True
        try:
            for stem, chip in self._chips.items():
                if stem != ALL_STEMS:
                    chip.set_active(False)
        finally:
            self._loading = was_loading
        self._notify()

    def _on_chip_toggled(self, _button: Gtk.ToggleButton) -> None:
        if self._loading:
            return
        if self._chips.get(ALL_STEMS):
            was_loading = self._loading
            self._loading = True
            try:
                self._chips[ALL_STEMS].set_active(False)
            finally:
                self._loading = was_loading
        self._notify()

    def _notify(self) -> None:
        if self._loading or self._on_changed is None:
            return
        self._on_changed()


class StemQuickExportControls:
    """Exclusive All / Instrumental only / Vocals only row."""

    def __init__(self, *, on_changed: Optional[Callable[[], None]] = None):
        self._on_changed = on_changed
        self._loading = False

        self.group = Adw.ToggleGroup()
        self.group.set_homogeneous(True)
        self.group.set_can_shrink(True)
        self.group.set_hexpand(True)
        self.group.connect("notify::active-name", self._on_active_name)

        self.container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.container.add_css_class("uvr-stem-only-row")
        self.container.append(self.group)

    @property
    def widget(self) -> Gtk.Box:
        return self.container

    def rebuild(self) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self.group.remove_all()
            entries = (
                (_QUICK_ALL, ALL_STEMS, ALL_STEMS_ICON, STEM_ONLY_ALL_HINT),
                (_QUICK_INSTRUMENTAL, _QUICK_EXPORT_LABELS[_QUICK_INSTRUMENTAL], stem_only_icon(INST_STEM), QUICK_EXPORT_INSTRUMENTAL_HINT),
                (_QUICK_VOCALS, _QUICK_EXPORT_LABELS[_QUICK_VOCALS], stem_only_icon(VOCAL_STEM), QUICK_EXPORT_VOCALS_HINT),
            )
            for name, label, icon, hint in entries:
                toggle = Adw.Toggle()
                toggle.set_name(name)
                toggle.set_label(label)
                toggle.set_tooltip(hint)
                if icon:
                    toggle.set_icon_name(icon)
                self.group.add(toggle)
        finally:
            self._loading = was_loading

    def set_active(self, name: str) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            if self.group.get_toggle_by_name(name) is not None:
                self.group.set_active_name(name)
            elif self.group.get_n_toggles() > 0:
                self.group.set_active_name(_QUICK_ALL)
        finally:
            self._loading = was_loading

    def active_name(self) -> str:
        return self.group.get_active_name() or _QUICK_ALL

    def _on_active_name(self, *_args) -> None:
        if self._loading or self._on_changed is None:
            return
        self._on_changed()


class StemFocusControls:
    """Exclusive Demucs focus row (All, quick exports, and per-stem focus)."""

    def __init__(self, *, on_changed: Optional[Callable[[], None]] = None):
        self._on_changed = on_changed
        self._loading = False
        self._focus_map: Dict[str, str] = {}

        self.group = Adw.ToggleGroup()
        self.group.set_homogeneous(False)
        self.group.set_can_shrink(True)
        self.group.set_hexpand(True)
        self.group.connect("notify::active-name", self._on_active_name)

        self.container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.container.add_css_class("uvr-stem-only-row")
        self.container.append(self.group)

    @property
    def widget(self) -> Gtk.Box:
        return self.container

    def rebuild(self, focus_stems: List[str]) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            self.group.remove_all()
            self._focus_map = {}
            for entry in focus_stems:
                if entry == ALL_STEMS:
                    name, label, icon, hint = _QUICK_ALL, ALL_STEMS, ALL_STEMS_ICON, STEM_ONLY_ALL_HINT
                    self._focus_map[name] = ALL_STEMS
                elif entry == _FOCUS_INSTRUMENTAL:
                    name = _FOCUS_INSTRUMENTAL
                    label = _QUICK_EXPORT_LABELS[_QUICK_INSTRUMENTAL]
                    icon = stem_only_icon(INST_STEM)
                    hint = QUICK_EXPORT_INSTRUMENTAL_HINT
                    self._focus_map[name] = _FOCUS_INSTRUMENTAL
                elif entry == _FOCUS_VOCALS:
                    name = _FOCUS_VOCALS
                    label = _QUICK_EXPORT_LABELS[_QUICK_VOCALS]
                    icon = stem_only_icon(VOCAL_STEM)
                    hint = QUICK_EXPORT_VOCALS_HINT
                    self._focus_map[name] = _FOCUS_VOCALS
                else:
                    name = entry
                    label = stem_display_label(entry)
                    icon = stem_only_icon(entry)
                    hint = stem_only_tooltip(entry)
                    self._focus_map[name] = entry
                toggle = Adw.Toggle()
                toggle.set_name(name)
                toggle.set_label(label)
                toggle.set_tooltip(hint)
                if icon:
                    toggle.set_icon_name(icon)
                self.group.add(toggle)
        finally:
            self._loading = was_loading

    def set_active_name(self, name: str) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            if self.group.get_toggle_by_name(name) is not None:
                self.group.set_active_name(name)
            elif self.group.get_n_toggles() > 0:
                self.group.set_active_name(_QUICK_ALL)
        finally:
            self._loading = was_loading

    def active_name(self) -> str:
        return self.group.get_active_name() or _QUICK_ALL

    def focus_value(self) -> str:
        return self._focus_map.get(self.active_name(), ALL_STEMS)

    def is_quick_vocals(self) -> bool:
        return self.active_name() == _FOCUS_VOCALS

    def is_quick_instrumental(self) -> bool:
        return self.active_name() == _FOCUS_INSTRUMENTAL

    def is_all_stems(self) -> bool:
        return self.active_name() == _QUICK_ALL

    def needs_export_filter(self) -> bool:
        name = self.active_name()
        return name not in (_QUICK_ALL, _FOCUS_INSTRUMENTAL, _FOCUS_VOCALS)

    def _on_active_name(self, *_args) -> None:
        if self._loading or self._on_changed is None:
            return
        self._on_changed()


class SaveStemsSection:
    """Unified Save stems widget for method views and ensemble."""

    def __init__(self, *, settings, on_changed: Optional[Callable[[], None]] = None):
        self.settings = settings
        self._on_changed = on_changed
        self._loading = False

        self.mode = "hidden"
        self._has_model = False
        self._primary_key = "is_primary_stem_only"
        self._secondary_key = "is_secondary_stem_only"
        self._subset_stems: List[str] = []
        self._exclusive_primary: Optional[str] = None
        self._exclusive_secondary: Optional[str] = None
        self._demucs_export_primary: Optional[str] = None
        self._demucs_export_secondary: Optional[str] = None
        self._subset_mode = _QUICK_ALL
        self._stem_label_overrides: Optional[Dict[str, str]] = None
        self._export_semantics_note = ""
        self._demucs_stem_count = 4

        self._exclusive = StemOnlyControls(on_changed=self._notify)
        self._quick_export = StemQuickExportControls(on_changed=self._on_quick_export_changed)
        self._subset = StemSubsetControls(on_changed=self._on_subset_changed)
        self._demucs_focus = StemFocusControls(on_changed=self._on_demucs_focus_changed)
        self._demucs_export = StemOnlyControls(on_changed=self._notify)

        self._exclusive_block = _labeled_row("Export filter", self._exclusive.widget)
        self._quick_block = _labeled_row("Common exports", self._quick_export.widget)
        self._subset_block = _labeled_row("Custom stems", self._subset.widget)
        self._demucs_focus_block = _labeled_row("Stem focus", self._demucs_focus.widget)
        self._demucs_export_block = _labeled_row("Export filter", self._demucs_export.widget)

        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.widget.set_halign(Gtk.Align.FILL)
        self.widget.set_hexpand(True)
        for block in (
            self._exclusive_block,
            self._quick_block,
            self._subset_block,
            self._demucs_focus_block,
            self._demucs_export_block,
        ):
            self.widget.append(block)

        self._hide_all_rows()

    def configure_hidden(self, *, has_model: bool = False) -> None:
        self.mode = "hidden"
        self._has_model = has_model
        self._stem_label_overrides = None
        self._export_semantics_note = ""
        self._hide_all_rows()
        self.widget.set_visible(False)

    def configure_exclusive(
        self,
        *,
        primary_stem: Optional[str],
        secondary_stem: Optional[str],
        primary_key: str,
        secondary_key: str,
        has_model: bool = True,
        stem_label_overrides: Optional[Dict[str, str]] = None,
        export_semantics_note: str = "",
    ) -> None:
        self.mode = "exclusive"
        self._has_model = has_model
        self._primary_key = primary_key
        self._secondary_key = secondary_key
        self._exclusive_primary = primary_stem
        self._exclusive_secondary = secondary_stem
        self._stem_label_overrides = stem_label_overrides
        self._export_semantics_note = export_semantics_note or ""
        self._hide_all_rows()
        if not has_model:
            self.widget.set_visible(False)
            return
        self.widget.set_visible(True)
        options = build_stem_only_options(
            primary_stem=primary_stem,
            secondary_stem=secondary_stem,
            primary_key=primary_key,
            secondary_key=secondary_key,
            stem_label_overrides=stem_label_overrides,
        )
        self._exclusive.rebuild(options)
        self._exclusive_block.set_visible(True)

    def configure_subset(
        self,
        *,
        stems: List[str],
        show_quick_export: bool,
        primary_key: str,
        secondary_key: str,
        has_model: bool = True,
        stem_label_overrides: Optional[Dict[str, str]] = None,
        export_semantics_note: str = "",
    ) -> None:
        self.mode = "subset"
        self._has_model = has_model
        self._stem_label_overrides = stem_label_overrides
        self._export_semantics_note = export_semantics_note or ""
        self._primary_key = primary_key
        self._secondary_key = secondary_key
        self._subset_stems = [s for s in stems if s != ALL_STEMS]
        self._hide_all_rows()
        if not has_model:
            self.widget.set_visible(False)
            return
        self.widget.set_visible(True)
        if show_quick_export:
            self._quick_export.rebuild()
            self._quick_block.set_visible(True)
        self._subset.rebuild(self._subset_stems, stem_label_overrides=stem_label_overrides)
        self._subset_block.set_visible(True)
        self._apply_subset_dimming()

    def configure_demucs(
        self,
        *,
        focus_stems: List[str],
        primary_key: str,
        secondary_key: str,
        has_model: bool = True,
        demucs_stem_count: int = 4,
        export_semantics_note: str = "",
    ) -> None:
        self.mode = "demucs"
        self._has_model = has_model
        self._stem_label_overrides = None
        self._export_semantics_note = export_semantics_note or ""
        self._demucs_stem_count = max(1, demucs_stem_count)
        self._primary_key = primary_key
        self._secondary_key = secondary_key
        self._hide_all_rows()
        if not has_model:
            self.widget.set_visible(False)
            return
        self.widget.set_visible(True)
        self._demucs_focus.rebuild(focus_stems)
        self._demucs_focus_block.set_visible(True)

    def sync_from_settings(self) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            if self.mode == "exclusive":
                self._exclusive.sync_from_settings(
                    self.settings, self._primary_key, self._secondary_key
                )
            elif self.mode == "subset":
                self._sync_subset_from_settings()
            elif self.mode == "demucs":
                self._sync_demucs_from_settings()
        finally:
            self._loading = was_loading

    def persist_to_settings(self) -> None:
        if self.mode == "exclusive":
            self._exclusive.persist_to_settings(
                self.settings, self._primary_key, self._secondary_key
            )
        elif self.mode == "subset":
            self._persist_subset()
        elif self.mode == "demucs":
            self._persist_demucs()

    def export_summary(self) -> str:
        if not self._has_model:
            return SAVE_STEMS_NO_MODEL_HELP
        if self.mode == "exclusive":
            return self._exclusive.active_export_label(
                self._exclusive_primary, self._exclusive_secondary
            )
        if self.mode == "subset":
            return self._subset_export_summary()
        if self.mode == "demucs":
            return self._demucs_export_summary()
        return SAVE_STEMS_NO_MODEL_HELP

    def export_description_lines(self) -> List[str]:
        lines = [self.export_summary()]
        if self._export_semantics_note:
            lines.append(self._export_semantics_note)
        return lines

    def expected_output_count(self) -> int:
        if not self._has_model or self.mode == "hidden":
            return 0
        if self.mode == "exclusive":
            return self._exclusive.expected_output_count()
        if self.mode == "subset":
            if self._subset_mode in (_QUICK_INSTRUMENTAL, _QUICK_VOCALS):
                return 1
            if self._subset_mode == _QUICK_ALL or self._subset.is_all_active():
                return max(1, len(self._subset_stems))
            selected = self._subset.selected_stems()
            if not selected:
                return max(1, len(self._subset_stems))
            return len(selected)
        if self.mode == "demucs":
            if self._demucs_focus.is_quick_instrumental() or self._demucs_focus.is_quick_vocals():
                return 1
            if self._demucs_focus.is_all_stems():
                return max(1, self._demucs_stem_count)
            if self._demucs_export_block.get_visible():
                return self._demucs_export.expected_output_count()
            return 1
        return 0

    def active_hint(self) -> str:
        if self.mode == "subset":
            return MDX_STEMS_HINT
        if self.mode == "demucs":
            return DEMUCS_STEMS_SAVE_HELP
        return SAVE_STEM_ONLY_HELP

    def _hide_all_rows(self) -> None:
        for block in (
            self._exclusive_block,
            self._quick_block,
            self._subset_block,
            self._demucs_focus_block,
            self._demucs_export_block,
        ):
            block.set_visible(False)
        self._quick_block.remove_css_class("uvr-stem-row-inactive")
        self._subset_block.remove_css_class("uvr-stem-row-inactive")

    def _apply_subset_dimming(self) -> None:
        if self._subset_mode == "custom":
            self._quick_block.add_css_class("uvr-stem-row-inactive")
            self._subset_block.remove_css_class("uvr-stem-row-inactive")
        else:
            self._subset_block.add_css_class("uvr-stem-row-inactive")
            self._quick_block.remove_css_class("uvr-stem-row-inactive")

    def _vocal_stem_in_subset(self) -> Optional[str]:
        for stem in self._subset_stems:
            if canonical_stem_name(stem) == VOCAL_STEM:
                return stem
        return None

    def _selection_matches_vocal_stem(self, selected: Set[str]) -> bool:
        if not selected or len(selected) != 1:
            return False
        chosen = next(iter(selected))
        return canonical_stem_name(chosen) == VOCAL_STEM or chosen == VOCAL_STEM

    def _apply_subset_chip_selection(self, mode: str, selected: Set[str]) -> None:
        full = self._subset_stems
        if mode == _QUICK_INSTRUMENTAL:
            self._subset.set_selection(set(), full_stems=full, highlight_all_when_empty=False)
        elif mode == _QUICK_VOCALS:
            vocal = self._vocal_stem_in_subset()
            self._subset.set_selection(
                {vocal} if vocal else set(),
                full_stems=full,
                highlight_all_when_empty=False,
            )
        elif mode == _QUICK_ALL:
            self._subset.set_selection(set(), full_stems=full)
        else:
            self._subset.set_selection(selected, full_stems=full)

    def _stored_subset_selection(self) -> Tuple[str, Set[str]]:
        selected = list(self.settings.get("mdx_stems_selected") or [])
        if not selected:
            legacy = self.settings.get("mdx_stems")
            if legacy and legacy != ALL_STEMS:
                selected = [legacy]
        selected_set = set(selected)
        stem_set = set(self._subset_stems)
        primary_on = bool(self.settings.get(self._primary_key))
        secondary_on = bool(self.settings.get(self._secondary_key))

        if self._vocal_stem_in_subset() and self._selection_matches_vocal_stem(selected_set):
            if secondary_on and not primary_on:
                return _QUICK_INSTRUMENTAL, selected_set
            if primary_on and not secondary_on:
                return _QUICK_VOCALS, selected_set
        if not selected_set or selected_set >= stem_set:
            if not primary_on and not secondary_on:
                return _QUICK_ALL, stem_set
        return "custom", selected_set

    def _sync_subset_from_settings(self) -> None:
        mode, selected = self._stored_subset_selection()
        self._subset_mode = mode
        if self._vocal_stem_in_subset():
            self._quick_export.set_active(mode if mode != "custom" else _QUICK_ALL)
        self._apply_subset_chip_selection(mode, selected)
        self._apply_subset_dimming()

    def _persist_subset(self) -> None:
        if self._subset_mode != "custom":
            if self._subset_mode == _QUICK_ALL:
                self.settings.set("mdx_stems_selected", [])
                self.settings.set("mdx_stems", ALL_STEMS)
                self.settings.set(self._primary_key, False)
                self.settings.set(self._secondary_key, False)
            elif self._subset_mode == _QUICK_INSTRUMENTAL:
                self.settings.set("mdx_stems_selected", [VOCAL_STEM])
                self.settings.set("mdx_stems", VOCAL_STEM)
                self.settings.set(self._primary_key, False)
                self.settings.set(self._secondary_key, True)
            elif self._subset_mode == _QUICK_VOCALS:
                self.settings.set("mdx_stems_selected", [VOCAL_STEM])
                self.settings.set("mdx_stems", VOCAL_STEM)
                self.settings.set(self._primary_key, True)
                self.settings.set(self._secondary_key, False)
            return

        selected = self._subset.selected_stems()
        if self._subset.is_all_active() or not selected or set(selected) >= set(self._subset_stems):
            self.settings.set("mdx_stems_selected", [])
            self.settings.set("mdx_stems", ALL_STEMS)
        else:
            self.settings.set("mdx_stems_selected", selected)
            self.settings.set("mdx_stems", selected[0] if len(selected) == 1 else ALL_STEMS)
        self.settings.set(self._primary_key, False)
        self.settings.set(self._secondary_key, False)

    def _subset_export_summary(self) -> str:
        if self._subset_mode == _QUICK_INSTRUMENTAL:
            return "Exporting Instrumental only (derived)"
        if self._subset_mode == _QUICK_VOCALS:
            return "Exporting Vocals only"
        if self._subset_mode == _QUICK_ALL or self._subset.is_all_active():
            return "Exporting all stems"
        selected = self._subset.selected_stems()
        if not selected:
            return "Exporting all stems"
        return "Exporting " + ", ".join(
            stem_display_label(stem, overrides=self._stem_label_overrides) for stem in selected
        )

    def _demucs_focus_stem_list(self) -> List[str]:
        return list(self._demucs_focus._focus_map.values())

    def _sync_demucs_from_settings(self) -> None:
        focus = self.settings.get("demucs_stems", ALL_STEMS)
        primary_on = bool(self.settings.get(self._primary_key))
        secondary_on = bool(self.settings.get(self._secondary_key))

        if focus == ALL_STEMS:
            active = _QUICK_ALL
        elif focus == VOCAL_STEM and secondary_on and not primary_on:
            active = _FOCUS_INSTRUMENTAL
        elif focus == VOCAL_STEM and primary_on and not secondary_on:
            active = _FOCUS_VOCALS
        else:
            active = focus

        self._demucs_focus.set_active_name(active)

        if self._demucs_focus.needs_export_filter():
            primary = focus
            secondary = secondary_stem(focus)
            self._demucs_export_primary = primary
            self._demucs_export_secondary = secondary
            options = build_stem_only_options(
                primary_stem=primary,
                secondary_stem=secondary,
                primary_key=self._primary_key,
                secondary_key=self._secondary_key,
            )
            self._demucs_export.rebuild(options)
            self._demucs_export.sync_from_settings(
                self.settings, self._primary_key, self._secondary_key
            )
            self._demucs_export_block.set_visible(True)
        else:
            self._demucs_export_block.set_visible(False)

    def _persist_demucs(self) -> None:
        active = self._demucs_focus.active_name()
        if active == _QUICK_ALL:
            self.settings.set("demucs_stems", ALL_STEMS)
            self.settings.set(self._primary_key, False)
            self.settings.set(self._secondary_key, False)
            return
        if active == _FOCUS_INSTRUMENTAL:
            self.settings.set("demucs_stems", VOCAL_STEM)
            self.settings.set(self._primary_key, False)
            self.settings.set(self._secondary_key, True)
            return
        if active == _FOCUS_VOCALS:
            self.settings.set("demucs_stems", VOCAL_STEM)
            self.settings.set(self._primary_key, True)
            self.settings.set(self._secondary_key, False)
            return

        self.settings.set("demucs_stems", active)
        if self._demucs_export_block.get_visible():
            self._demucs_export.persist_to_settings(
                self.settings, self._primary_key, self._secondary_key
            )
        else:
            self.settings.set(self._primary_key, True)
            self.settings.set(self._secondary_key, False)

    def _demucs_export_summary(self) -> str:
        if self._demucs_focus.is_all_stems():
            return "Exporting all stems"
        if self._demucs_focus.is_quick_instrumental():
            return "Exporting Instrumental only (derived)"
        if self._demucs_focus.is_quick_vocals():
            return "Exporting Vocals only"
        focus = self._demucs_focus.focus_value()
        if self._demucs_export_block.get_visible():
            summary = self._demucs_export.active_export_label(
                self._demucs_export_primary, self._demucs_export_secondary
            )
            focus_label = stem_display_label(focus)
            return summary.replace("Exporting", f"{focus_label} focus —", 1)
        return f"{stem_display_label(focus)} focus — {stem_display_label(focus)} only"

    def _on_quick_export_changed(self) -> None:
        if self._loading:
            return
        self._subset_mode = self._quick_export.active_name()
        was_loading = self._loading
        self._loading = True
        try:
            if self._subset_mode == _QUICK_ALL:
                self._subset.set_selection(set(), full_stems=self._subset_stems)
            elif self._subset_mode == _QUICK_INSTRUMENTAL:
                self._subset.set_selection(
                    set(),
                    full_stems=self._subset_stems,
                    highlight_all_when_empty=False,
                )
            elif self._subset_mode == _QUICK_VOCALS:
                vocal = self._vocal_stem_in_subset()
                self._subset.set_selection(
                    {vocal} if vocal else set(),
                    full_stems=self._subset_stems,
                    highlight_all_when_empty=False,
                )
        finally:
            self._loading = False
        self._apply_subset_dimming()
        self._notify()

    def _on_subset_changed(self) -> None:
        if self._loading:
            return
        self._subset_mode = "custom"
        self._apply_subset_dimming()
        self._notify()

    def _on_demucs_focus_changed(self) -> None:
        if self._loading:
            return
        if self._demucs_focus.needs_export_filter():
            primary = self._demucs_focus.focus_value()
            secondary = secondary_stem(primary)
            self._demucs_export_primary = primary
            self._demucs_export_secondary = secondary
            options = build_stem_only_options(
                primary_stem=primary,
                secondary_stem=secondary,
                primary_key=self._primary_key,
                secondary_key=self._secondary_key,
            )
            self._demucs_export.rebuild(options)
            was_loading = self._loading
            self._loading = True
            try:
                if not self.settings.get(self._primary_key) and not self.settings.get(self._secondary_key):
                    self.settings.set(self._primary_key, True)
                    self.settings.set(self._secondary_key, False)
                self._demucs_export.sync_from_settings(
                    self.settings, self._primary_key, self._secondary_key
                )
            finally:
                self._loading = was_loading
            self._demucs_export_block.set_visible(True)
        else:
            self._demucs_export_block.set_visible(False)
        self._notify()

    def _notify(self) -> None:
        if self._loading or self._on_changed is None:
            return
        self._on_changed()
