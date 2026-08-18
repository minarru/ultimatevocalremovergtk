"""Save-stems controls: exclusive export, MDX subset, and Demucs focus."""

from __future__ import annotations
import typing

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
from core.stem_selection import (
    DemucsView,
    ExclusiveView,
    StemSelectionState,
    SubsetView,
    _FOCUS_INSTRUMENTAL,
    _FOCUS_VOCALS,
    _QUICK_ALL,
    _QUICK_INSTRUMENTAL,
    _QUICK_VOCALS,
    _SUBSET_CUSTOM,
    _TOGGLE_ALL,
    _exclusive_name_from_settings,
)
from core.stems import (
    EnsemblePair,
    StemBucket,
    bucket_for_model_stem,
    canonical_stem_alias,
    concept_is,
)

from ..dialogs.utils import present_modal_dialog, set_form_dialog_content
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
from ..markup import set_row_subtitle
from ..spacing import inset_md
from .rows import get_combo_value, make_combo_row, set_combo_tag_values, set_combo_value

# Stable display order for "<stem> Only" entries.
_STEM_ONLY_ORDER = (INST_STEM, VOCAL_STEM, BASS_STEM, DRUM_STEM, OTHER_STEM)

STEM_ONLY_ICON_FALLBACK = "audio-x-generic-symbolic"

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

# UI-only: names with no ensemble/bucket significance today. Kept separate
# from the shared core table on purpose -- folding them in would change
# core/stems.canonical_ensemble_stem_tag's output for these
# stems (verified: it passes them through unchanged today). See
# docs/superpowers/specs/2026-08-09-stem-export-semantics-design.md.
_STEM_ALIASES: Dict[str, str] = {
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


def roformer_lead_vocal_label_overrides(model: typing.Any) -> Optional[Dict[str, str]]:
    """Return stem display overrides for the selected model."""
    return stem_display_overrides(model)


def canonical_stem_name(stem: Optional[str]) -> Optional[str]:
    """Normalize model/yaml stem strings to canonical UVR labels."""
    if not stem:
        return stem
    shared = canonical_stem_alias(stem)
    if shared is not None:
        return shared
    if stem in _STEM_ALIASES:
        return _STEM_ALIASES[stem]
    lowered = stem.lower()
    if lowered in _STEM_ALIASES:
        return _STEM_ALIASES[lowered]
    if stem.startswith(NO_STEM) and len(stem) > len(NO_STEM):
        suffix = stem[len(NO_STEM) :]
        canonical_suffix = canonical_stem_alias(suffix) or _STEM_ALIASES.get(suffix.lower(), suffix)
        if canonical_suffix == suffix and suffix[:1].islower():
            canonical_suffix = suffix.title()
        return f"{NO_STEM}{canonical_suffix}"
    return stem


def stem_display_label(stem: Optional[str], *, overrides: Optional[Dict[str, str]] = None) -> str:
    """Human-readable label for combos, checklists, and export summaries."""
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

_QUICK_EXPORT_HINTS = {
    _QUICK_ALL: STEM_ONLY_ALL_HINT,
    _QUICK_INSTRUMENTAL: QUICK_EXPORT_INSTRUMENTAL_HINT,
    _QUICK_VOCALS: QUICK_EXPORT_VOCALS_HINT,
}


def stem_only_icon(stem: Optional[str]) -> Optional[str]:
    if not stem:
        return None
    if stem == ALL_STEMS:
        return ALL_STEMS_ICON
    canonical = canonical_stem_name(stem) or stem
    return STEM_ONLY_ICONS.get(canonical, STEM_ONLY_ICON_FALLBACK)


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
    stem_label_overrides: Optional[Dict[str, str]] = None,
) -> List[StemOnlyOption]:
    """Build export entries for All Stems + each stem's Only option."""
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
                    if bucket_for_model_stem(
                        stem_display_label(entry[0], overrides=stem_label_overrides),
                        stem_count=2,  # a primary/secondary pair, by construction
                    )
                    in (
                        StemBucket.VOCALS,
                        StemBucket.LEAD_VOCALS,
                        StemBucket.BACKING_VOCALS,
                    )
                    else 1,
                    _stem_only_rank(
                        stem_display_label(entry[0], overrides=stem_label_overrides)
                    ),
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


def _fill_export_combo(row: Adw.ComboRow, options: List[StemOnlyOption]) -> Dict[str, StemOnlyOption]:
    set_combo_tag_values(row, [(opt.name, opt.display_label) for opt in options])
    return {opt.name: opt for opt in options}


def _export_label_for_choice(name: str, options: Dict[str, StemOnlyOption]) -> str:
    if name == _TOGGLE_ALL:
        return "Exporting all outputs"
    option = options.get(name)
    if option is not None:
        return f"Exporting {option.display_label} only"
    return "Exporting selected outputs"


class SaveStemsSection:
    """Unified Save stems widget for method views and ensemble."""

    def __init__(self, *, settings: typing.Any, on_changed: Optional[Callable[[], None]] = None):
        self.settings = settings
        self._on_changed = on_changed
        self._loading = False
        self._state = StemSelectionState()

        self._stem_label_overrides: Optional[Dict[str, str]] = None
        self._export_semantics_note = ""
        self._exclusive_options: Dict[str, StemOnlyOption] = {}
        self._demucs_export_options: Dict[str, StemOnlyOption] = {}
        self._draft_custom_selected: Set[str] = set()
        self._draft_custom_all = True
        self._custom_checks: Dict[str, Gtk.CheckButton] = {}
        self._host: Optional[Adw.PreferencesGroup] = None
        self._section_visible = False

        self._exclusive_row = make_combo_row("Export", [])
        self._exclusive_row.connect("notify::selected", self._on_exclusive_changed)

        self._quick_row = make_combo_row("Quick export", [])
        self._quick_row.connect("notify::selected", self._on_quick_export_changed)

        self._custom_row = Adw.ActionRow(
            title="Custom stems",
            subtitle="Open to choose specific stems",
            activatable=True,
        )
        self._custom_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        self._custom_row.connect("activated", self._open_custom_stems_dialog)

        self._demucs_focus_row = make_combo_row("Stem focus", [])
        self._demucs_focus_row.connect("notify::selected", self._on_demucs_focus_changed)

        self._demucs_export_row = make_combo_row("Export", [])
        self._demucs_export_row.connect("notify::selected", self._on_demucs_export_changed)

        self._rows = (
            self._exclusive_row,
            self._quick_row,
            self._custom_row,
            self._demucs_focus_row,
            self._demucs_export_row,
        )
        # Holder until attach_to() reparents rows into the outer Save stems group.
        self._holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for row in self._rows:
            self._holder.append(row)

        # Compatibility aliases used by tests / metadata helpers.
        self._exclusive_block = self._exclusive_row
        self._quick_block = self._quick_row
        self._subset_block = self._custom_row
        self._demucs_focus_block = self._demucs_focus_row
        self._demucs_export_block = self._demucs_export_row

        self._build_custom_stems_dialog()
        self._hide_all_rows()

    @property
    def widget(self) -> Gtk.Widget:
        """Hint/tooltip target: host PreferencesGroup once attached."""
        return self._host if self._host is not None else self._holder

    @property
    def mode(self) -> str:
        return self._state.mode

    @mode.setter
    def mode(self, value: str) -> None:
        self._state.mode = value

    @property
    def _has_model(self) -> bool:
        return self._state.has_model

    @_has_model.setter
    def _has_model(self, value: bool) -> None:
        self._state.has_model = value

    @property
    def _primary_key(self) -> str:
        return self._state.primary_key

    @_primary_key.setter
    def _primary_key(self, value: str) -> None:
        self._state.primary_key = value

    @property
    def _secondary_key(self) -> str:
        return self._state.secondary_key

    @_secondary_key.setter
    def _secondary_key(self, value: str) -> None:
        self._state.secondary_key = value

    @property
    def _subset_stems(self) -> List[str]:
        return self._state.subset_stems

    @_subset_stems.setter
    def _subset_stems(self, value: List[str]) -> None:
        self._state.subset_stems = list(value)

    @property
    def _exclusive_primary(self) -> Optional[str]:
        return self._state.exclusive_primary

    @_exclusive_primary.setter
    def _exclusive_primary(self, value: Optional[str]) -> None:
        self._state.exclusive_primary = value

    @property
    def _exclusive_secondary(self) -> Optional[str]:
        return self._state.exclusive_secondary

    @_exclusive_secondary.setter
    def _exclusive_secondary(self, value: Optional[str]) -> None:
        self._state.exclusive_secondary = value

    @property
    def _exclusive_is_karaoke(self) -> bool:
        return self._state.is_karaoke

    @_exclusive_is_karaoke.setter
    def _exclusive_is_karaoke(self, value: bool) -> None:
        self._state.is_karaoke = value

    @property
    def _exclusive_is_karaoke_curated(self) -> bool:
        return self._state.is_karaoke_curated

    @_exclusive_is_karaoke_curated.setter
    def _exclusive_is_karaoke_curated(self, value: bool) -> None:
        self._state.is_karaoke_curated = value

    @property
    def _exclusive_is_bv(self) -> bool:
        return self._state.is_bv

    @_exclusive_is_bv.setter
    def _exclusive_is_bv(self, value: bool) -> None:
        self._state.is_bv = value

    @property
    def _exclusive_stem_count(self) -> int:
        return self._state.stem_count

    @_exclusive_stem_count.setter
    def _exclusive_stem_count(self, value: int) -> None:
        self._state.stem_count = value

    @property
    def _exclusive_pair(self) -> Optional[EnsemblePair]:
        return self._state.ensemble_pair

    @_exclusive_pair.setter
    def _exclusive_pair(self, value: Optional[EnsemblePair]) -> None:
        self._state.ensemble_pair = value

    @property
    def _demucs_export_primary(self) -> Optional[str]:
        return self._state.demucs_export_primary

    @_demucs_export_primary.setter
    def _demucs_export_primary(self, value: Optional[str]) -> None:
        self._state.demucs_export_primary = value

    @property
    def _demucs_export_secondary(self) -> Optional[str]:
        return self._state.demucs_export_secondary

    @_demucs_export_secondary.setter
    def _demucs_export_secondary(self, value: Optional[str]) -> None:
        self._state.demucs_export_secondary = value

    @property
    def _subset_mode(self) -> str:
        return self._state.subset_mode

    @_subset_mode.setter
    def _subset_mode(self, value: str) -> None:
        self._state.subset_mode = value

    @property
    def _demucs_stem_count(self) -> int:
        return self._state.demucs_stem_count

    @_demucs_stem_count.setter
    def _demucs_stem_count(self, value: int) -> None:
        self._state.demucs_stem_count = value

    @property
    def _demucs_focus_map(self) -> Dict[str, str]:
        return self._state.demucs_focus_map

    @_demucs_focus_map.setter
    def _demucs_focus_map(self, value: Dict[str, str]) -> None:
        self._state.demucs_focus_map = value

    @property
    def _custom_selected(self) -> Set[str]:
        return self._state.custom_selected

    @_custom_selected.setter
    def _custom_selected(self, value: Set[str]) -> None:
        self._state.custom_selected = set(value)

    @property
    def _custom_all(self) -> bool:
        return self._state.custom_all

    @_custom_all.setter
    def _custom_all(self, value: bool) -> None:
        self._state.custom_all = value

    def attach_to(self, group: Adw.PreferencesGroup) -> None:
        """Add export rows directly to ``group`` (avoids a nested PreferencesGroup)."""
        for row in self._rows:
            parent = row.get_parent()
            if parent is self._holder:
                self._holder.remove(row)
            elif isinstance(parent, (Gtk.Box, Adw.PreferencesGroup)) and parent is not group:
                parent.remove(row)
            if row.get_parent() is None:
                group.add(row)
        self._host = group

    def _build_custom_stems_dialog(self) -> None:
        self._custom_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._custom_listbox.add_css_class("boxed-list")

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(280)
        scroller.set_vexpand(True)
        scroller.set_child(self._custom_listbox)

        description = Gtk.Label(
            label="Choose which stems to export. Selecting All stems clears individual picks.",
            wrap=True,
            xalign=0.0,
        )
        description.add_css_class("dim-label")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inset_md(content)
        content.append(description)
        content.append(scroller)

        self._custom_dialog = Adw.Dialog()
        self._custom_dialog.set_title("Custom stems")
        self._custom_dialog.set_content_width(400)
        self._custom_dialog.set_content_height(480)
        self._custom_dialog.set_follows_content_size(True)
        set_form_dialog_content(
            self._custom_dialog,
            content,
            on_save=self._on_custom_stems_save,
            save_label="Save",
        )

    def configure_hidden(self, *, has_model: bool = False) -> None:
        self._state.configure_hidden(has_model=has_model)
        self._stem_label_overrides = None
        self._export_semantics_note = ""
        self._section_visible = False
        self._hide_all_rows()

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
        is_karaoke: bool = False,
        is_karaoke_curated: bool = False,
        is_bv: bool = False,
        stem_count: int = 2,
        ensemble_pair: Optional[EnsemblePair] = None,
    ) -> None:
        self._state.configure_exclusive(
            primary_stem=primary_stem,
            secondary_stem=secondary_stem,
            primary_key=primary_key,
            secondary_key=secondary_key,
            has_model=has_model,
            is_karaoke=is_karaoke,
            is_karaoke_curated=is_karaoke_curated,
            is_bv=is_bv,
            stem_count=stem_count,
            ensemble_pair=ensemble_pair,
        )
        self._stem_label_overrides = stem_label_overrides
        self._export_semantics_note = export_semantics_note or ""
        self._hide_all_rows()
        if not has_model:
            self._section_visible = False
            return
        self._section_visible = True
        options = build_stem_only_options(
            primary_stem=primary_stem,
            secondary_stem=secondary_stem,
            primary_key=primary_key,
            secondary_key=secondary_key,
            stem_label_overrides=stem_label_overrides,
        )
        was_loading = self._loading
        self._loading = True
        try:
            self._exclusive_options = _fill_export_combo(self._exclusive_row, options)
        finally:
            self._loading = was_loading
        self._exclusive_row.set_visible(True)
        self._apply_semantics_tooltip(self._exclusive_row)

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
        self._state.configure_subset(
            stems=stems,
            primary_key=primary_key,
            secondary_key=secondary_key,
            has_model=has_model,
        )
        self._stem_label_overrides = stem_label_overrides
        self._export_semantics_note = export_semantics_note or ""
        self._hide_all_rows()
        if not has_model:
            self._section_visible = False
            return
        self._section_visible = True
        was_loading = self._loading
        self._loading = True
        try:
            if show_quick_export:
                set_combo_tag_values(
                    self._quick_row,
                    [
                        (_QUICK_ALL, _QUICK_EXPORT_LABELS[_QUICK_ALL]),
                        (_QUICK_INSTRUMENTAL, _QUICK_EXPORT_LABELS[_QUICK_INSTRUMENTAL]),
                        (_QUICK_VOCALS, _QUICK_EXPORT_LABELS[_QUICK_VOCALS]),
                    ],
                )
                self._quick_row.set_visible(True)
            self._custom_row.set_visible(True)
        finally:
            self._loading = was_loading
        target = self._quick_row if show_quick_export else self._custom_row
        self._apply_semantics_tooltip(target)
        self._refresh_custom_subtitle()
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
        self._state.configure_demucs(
            focus_stems=focus_stems,
            primary_key=primary_key,
            secondary_key=secondary_key,
            has_model=has_model,
            demucs_stem_count=demucs_stem_count,
        )
        self._stem_label_overrides = None
        self._export_semantics_note = export_semantics_note or ""
        self._hide_all_rows()
        if not has_model:
            self._section_visible = False
            return
        self._section_visible = True
        items: List[Tuple[str, str]] = []
        for entry in focus_stems:
            if entry == ALL_STEMS:
                name, label = _QUICK_ALL, ALL_STEMS
            elif entry == _FOCUS_INSTRUMENTAL:
                name = _FOCUS_INSTRUMENTAL
                label = _QUICK_EXPORT_LABELS[_QUICK_INSTRUMENTAL]
            elif entry == _FOCUS_VOCALS:
                name = _FOCUS_VOCALS
                label = _QUICK_EXPORT_LABELS[_QUICK_VOCALS]
            else:
                name = entry
                label = stem_display_label(entry)
            items.append((name, label))
        was_loading = self._loading
        self._loading = True
        try:
            set_combo_tag_values(self._demucs_focus_row, items)
        finally:
            self._loading = was_loading
        self._demucs_focus_row.set_visible(True)
        self._apply_semantics_tooltip(self._demucs_focus_row)

    def sync_from_settings(self) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            view = self._state.read(self.settings)
            if isinstance(view, ExclusiveView):
                set_combo_value(self._exclusive_row, view.choice)
            elif isinstance(view, SubsetView):
                if self._quick_row.get_visible() and self._state.vocal_stem_in_subset():
                    set_combo_value(
                        self._quick_row,
                        view.mode if view.mode != _SUBSET_CUSTOM else _QUICK_ALL,
                    )
                self._apply_subset_dimming()
            elif isinstance(view, DemucsView):
                set_combo_value(self._demucs_focus_row, view.active)
                self._update_demucs_export_visibility(from_settings=True)
        finally:
            self._loading = was_loading
        self._refresh_primary_semantics()

    def persist_to_settings(self) -> None:
        if self.mode == "exclusive":
            self._state.write(
                self.settings,
                ExclusiveView(choice=get_combo_value(self._exclusive_row) or _TOGGLE_ALL),
            )
        elif self.mode == "subset":
            self._state.write(
                self.settings,
                SubsetView(
                    mode=self._subset_mode,
                    selected=set(self._custom_selected),
                    custom_all=self._custom_all,
                ),
            )
        elif self.mode == "demucs":
            active = self._demucs_active_name()
            self._state.write(
                self.settings,
                DemucsView(
                    active=active,
                    export_choice=get_combo_value(self._demucs_export_row) or _TOGGLE_ALL,
                    export_filter_visible=self._demucs_export_row.get_visible(),
                ),
            )

    def export_summary(self) -> str:
        if not self._has_model:
            return SAVE_STEMS_NO_MODEL_HELP
        if self.mode == "exclusive":
            name = get_combo_value(self._exclusive_row) or _TOGGLE_ALL
            return _export_label_for_choice(name, self._exclusive_options)
        if self.mode == "subset":
            return self._subset_export_summary()
        if self.mode == "demucs":
            return self._demucs_export_summary()
        return SAVE_STEMS_NO_MODEL_HELP

    def export_description_lines(self) -> List[str]:
        """Group description lines (summary only; semantics live on the row)."""
        return [self.export_summary()]

    def expected_output_count(self) -> int:
        return self._state.expected_output_count(
            exclusive_choice=get_combo_value(self._exclusive_row) or _TOGGLE_ALL,
            demucs_active=self._demucs_active_name(),
            demucs_export_choice=get_combo_value(self._demucs_export_row) or _TOGGLE_ALL,
            demucs_export_visible=self._demucs_export_row.get_visible(),
        )

    def active_hint(self) -> str:
        if self._export_semantics_note:
            return self._export_semantics_note
        if self.mode == "subset":
            return MDX_STEMS_HINT
        if self.mode == "demucs":
            return DEMUCS_STEMS_SAVE_HELP
        return SAVE_STEM_ONLY_HELP

    # -- Exclusive -------------------------------------------------------------

    def _on_exclusive_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        self._notify()

    # -- Subset / custom stems -------------------------------------------------

    def _hide_all_rows(self) -> None:
        for row in (
            self._exclusive_row,
            self._quick_row,
            self._custom_row,
            self._demucs_focus_row,
            self._demucs_export_row,
        ):
            row.set_visible(False)
        self._quick_row.set_sensitive(True)
        self._custom_row.set_sensitive(True)

    def _apply_subset_dimming(self) -> None:
        """Dim the inactive path so Quick vs Custom ownership is obvious."""
        if not self._quick_row.get_visible():
            self._quick_row.set_opacity(1.0)
            self._custom_row.set_opacity(1.0)
            self._quick_row.set_sensitive(True)
            self._custom_row.set_sensitive(True)
            return
        custom_active = self._subset_mode == "custom"
        self._quick_row.set_opacity(0.55 if custom_active else 1.0)
        self._custom_row.set_opacity(1.0 if custom_active else 0.55)
        self._quick_row.set_sensitive(True)
        self._custom_row.set_sensitive(True)

    def _vocal_stem_in_subset(self) -> Optional[str]:
        return self._state.vocal_stem_in_subset()

    def _set_custom_selection(
        self,
        selected: Set[str],
        *,
        highlight_all_when_empty: bool = True,
    ) -> None:
        self._state.set_custom_selection(
            selected, highlight_all_when_empty=highlight_all_when_empty
        )
        self._refresh_custom_subtitle()

    def _apply_subset_chip_selection(self, mode: str, selected: Set[str]) -> None:
        self._state.apply_subset_chip_selection(mode, selected)
        self._refresh_custom_subtitle()

    def _subset_export_summary(self) -> str:
        if self._subset_mode == _QUICK_INSTRUMENTAL:
            return "Exporting Instrumental only (derived)"
        if self._subset_mode == _QUICK_VOCALS:
            return "Exporting Vocals only"
        if self._subset_mode == _QUICK_ALL or self._custom_all:
            return "Exporting all stems"
        selected = [stem for stem in self._subset_stems if stem in self._custom_selected]
        if not selected:
            return "Exporting all stems"
        if len(selected) == 1 and concept_is(
            selected[0], StemBucket.OTHER, stem_count=len(self._subset_stems)
        ):
            return "Exporting Other stem"
        return "Exporting " + ", ".join(
            stem_display_label(stem, overrides=self._stem_label_overrides) for stem in selected
        )

    def _refresh_custom_subtitle(self) -> None:
        if self._subset_mode != "custom":
            set_row_subtitle(self._custom_row, "Open to choose specific stems")
            return
        if self._custom_all or not self._custom_selected:
            set_row_subtitle(self._custom_row, ALL_STEMS)
            return
        labels = [
            stem_display_label(stem, overrides=self._stem_label_overrides)
            for stem in self._subset_stems
            if stem in self._custom_selected
        ]
        set_row_subtitle(self._custom_row, ", ".join(labels) if labels else ALL_STEMS)

    def _rebuild_custom_checklist(self) -> None:
        child = self._custom_listbox.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._custom_listbox.remove(child)
            child = nxt
        self._custom_checks = {}

        all_row = Adw.ActionRow(title=ALL_STEMS)
        all_check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        all_check.connect("toggled", self._on_draft_all_toggled)
        all_row.add_prefix(all_check)
        all_row.set_activatable_widget(all_check)
        self._custom_listbox.append(all_row)
        self._custom_checks[ALL_STEMS] = all_check

        for stem in self._subset_stems:
            label = stem_display_label(stem, overrides=self._stem_label_overrides)
            row = Adw.ActionRow(title=label)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.connect("toggled", self._on_draft_stem_toggled)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self._custom_listbox.append(row)
            self._custom_checks[stem] = check

    def _sync_draft_checks(self) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            all_check = self._custom_checks.get(ALL_STEMS)
            if all_check is not None:
                all_check.set_active(self._draft_custom_all)
            for stem in self._subset_stems:
                check = self._custom_checks.get(stem)
                if check is not None:
                    check.set_active(
                        (not self._draft_custom_all) and stem in self._draft_custom_selected
                    )
        finally:
            self._loading = was_loading

    def _open_custom_stems_dialog(self, *_args: typing.Any) -> None:
        if self._subset_mode == "custom":
            self._draft_custom_all = self._custom_all
            self._draft_custom_selected = set(self._custom_selected)
        else:
            self._draft_custom_all = True
            self._draft_custom_selected = set()
        self._rebuild_custom_checklist()
        self._sync_draft_checks()
        parent = self.widget.get_root()
        present_modal_dialog(self._custom_dialog, parent if isinstance(parent, Gtk.Window) else None)

    def _on_draft_all_toggled(self, button: Gtk.CheckButton) -> None:
        if self._loading or not button.get_active():
            return
        was_loading = self._loading
        self._loading = True
        try:
            for stem, check in self._custom_checks.items():
                if stem != ALL_STEMS:
                    check.set_active(False)
        finally:
            self._loading = was_loading
        self._draft_custom_all = True
        self._draft_custom_selected = set()

    def _on_draft_stem_toggled(self, _button: Gtk.CheckButton) -> None:
        if self._loading:
            return
        was_loading = self._loading
        self._loading = True
        try:
            all_check = self._custom_checks.get(ALL_STEMS)
            if all_check is not None:
                all_check.set_active(False)
        finally:
            self._loading = was_loading
        self._draft_custom_all = False
        self._draft_custom_selected = {
            stem
            for stem in self._subset_stems
            if self._custom_checks.get(stem) and self._custom_checks[stem].get_active()
        }
        if not self._draft_custom_selected or self._draft_custom_selected >= set(
            self._subset_stems
        ):
            self._draft_custom_all = True
            self._draft_custom_selected = set()
            if self._custom_checks.get(ALL_STEMS):
                was_loading = self._loading
                self._loading = True
                try:
                    self._custom_checks[ALL_STEMS].set_active(True)
                    for stem in self._subset_stems:
                        self._custom_checks[stem].set_active(False)
                finally:
                    self._loading = was_loading

    def _on_custom_stems_save(self) -> None:
        self._custom_all = self._draft_custom_all
        self._custom_selected = set(self._draft_custom_selected)
        self._subset_mode = "custom"
        self._refresh_custom_subtitle()
        self._apply_subset_dimming()
        self._custom_dialog.close()
        self._notify()

    def _on_quick_export_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        mode = get_combo_value(self._quick_row) or _QUICK_ALL
        self._subset_mode = mode
        self._apply_subset_chip_selection(mode, set())
        self._apply_subset_dimming()
        tip = self._export_semantics_note or _QUICK_EXPORT_HINTS.get(mode) or MDX_STEMS_HINT
        self._quick_row.set_tooltip_text(tip)
        self._notify()

    # -- Demucs ----------------------------------------------------------------

    def _demucs_active_name(self) -> str:
        return get_combo_value(self._demucs_focus_row) or _QUICK_ALL

    def _demucs_focus_value(self) -> str:
        return self._state.demucs_focus_value(self._demucs_active_name())

    def _demucs_is_quick_vocals(self) -> bool:
        return self._demucs_active_name() == _FOCUS_VOCALS

    def _demucs_is_quick_instrumental(self) -> bool:
        return self._demucs_active_name() == _FOCUS_INSTRUMENTAL

    def _demucs_is_all_stems(self) -> bool:
        return self._demucs_active_name() == _QUICK_ALL

    def _demucs_needs_export_filter(self) -> bool:
        return self._state.demucs_needs_export_filter(self._demucs_active_name())

    def _update_demucs_export_visibility(self, *, from_settings: bool) -> None:
        if self._demucs_needs_export_filter():
            primary = self._demucs_focus_value()
            secondary = secondary_stem(primary)
            self._demucs_export_primary = primary
            self._demucs_export_secondary = secondary
            options = build_stem_only_options(
                primary_stem=primary,
                secondary_stem=secondary,
                primary_key=self._primary_key,
                secondary_key=self._secondary_key,
            )
            was_loading = self._loading
            self._loading = True
            try:
                self._demucs_export_options = _fill_export_combo(self._demucs_export_row, options)
                if not from_settings:
                    self._state.ensure_demucs_export_defaults(self.settings)
                name = _exclusive_name_from_settings(
                    self.settings, self._primary_key, self._secondary_key
                )
                set_combo_value(self._demucs_export_row, name)
            finally:
                self._loading = was_loading
            self._demucs_export_row.set_visible(True)
        else:
            self._demucs_export_row.set_visible(False)

    def _demucs_export_summary(self) -> str:
        if self._demucs_is_all_stems():
            return "Exporting all stems"
        if self._demucs_is_quick_instrumental():
            return "Exporting Instrumental only (derived)"
        if self._demucs_is_quick_vocals():
            return "Exporting Vocals only"
        focus = self._demucs_focus_value()
        focus_label = stem_display_label(focus)
        if self._demucs_export_row.get_visible():
            name = get_combo_value(self._demucs_export_row) or _TOGGLE_ALL
            summary = _export_label_for_choice(name, self._demucs_export_options)
            return summary.replace("Exporting", f"{focus_label} focus —", 1)
        return f"{focus_label} focus — {focus_label} only"

    def _on_demucs_focus_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        self._update_demucs_export_visibility(from_settings=False)
        self._notify()

    def _on_demucs_export_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        self._notify()

    # -- Semantics / notify ----------------------------------------------------

    def _apply_semantics_tooltip(self, row: Adw.PreferencesRow) -> None:
        """Put long guidance on the tooltip only (not the row subtitle)."""
        if isinstance(row, Adw.ComboRow):
            row.set_subtitle("")
        row.set_tooltip_text(self._export_semantics_note or self.active_hint())

    def _refresh_primary_semantics(self) -> None:
        if self.mode == "exclusive":
            self._apply_semantics_tooltip(self._exclusive_row)
        elif self.mode == "subset":
            target = self._quick_row if self._quick_row.get_visible() else self._custom_row
            self._apply_semantics_tooltip(target)
        elif self.mode == "demucs":
            self._apply_semantics_tooltip(self._demucs_focus_row)

    def _notify(self) -> None:
        if self._loading or self._on_changed is None:
            return
        self._on_changed()

    # -- Test helpers (preserve prior internal call shapes) --------------------

    class _QuickExportProxy:
        def __init__(self, section: "SaveStemsSection"):
            self._section = section

        def set_active(self, name: str) -> None:
            was_loading = self._section._loading
            self._section._loading = True
            try:
                set_combo_value(self._section._quick_row, name)
            finally:
                self._section._loading = was_loading

        def active_name(self) -> str:
            return get_combo_value(self._section._quick_row) or _QUICK_ALL

    class _SubsetProxy:
        def __init__(self, section: "SaveStemsSection"):
            self._section = section

        @property
        def _chips(self) -> Dict[str, "SaveStemsSection._ChipProxy"]:
            return {
                stem: SaveStemsSection._ChipProxy(self._section, stem)
                for stem in [ALL_STEMS, *self._section._subset_stems]
            }

        def rebuild(self, stems: List[str], *, stem_label_overrides: typing.Any=None) -> None:
            self._section._subset_stems = list(stems)
            if stem_label_overrides is not None:
                self._section._stem_label_overrides = stem_label_overrides
            self._section._rebuild_custom_checklist()

        def set_selection(
            self,
            selected: Set[str],
            *,
            full_stems: List[str],
            highlight_all_when_empty: bool = True,
        ) -> None:
            self._section._subset_stems = list(full_stems)
            self._section._set_custom_selection(
                selected, highlight_all_when_empty=highlight_all_when_empty
            )

        def selected_stems(self) -> List[str]:
            if self._section._custom_all:
                return []
            return [
                stem
                for stem in self._section._subset_stems
                if stem in self._section._custom_selected
            ]

        def is_all_active(self) -> bool:
            return self._section._custom_all

    class _ChipProxy:
        def __init__(self, section: "SaveStemsSection", stem: str):
            self._section = section
            self._stem = stem

        def get_active(self) -> bool:
            if self._stem == ALL_STEMS:
                return self._section._custom_all
            return (not self._section._custom_all) and self._stem in self._section._custom_selected

    class _DemucsFocusProxy:
        def __init__(self, section: "SaveStemsSection"):
            self._section = section

        def set_active_name(self, name: str) -> None:
            was_loading = self._section._loading
            self._section._loading = True
            try:
                set_combo_value(self._section._demucs_focus_row, name)
            finally:
                self._section._loading = was_loading

        def active_name(self) -> str:
            return self._section._demucs_active_name()

        def focus_value(self) -> str:
            return self._section._demucs_focus_value()

        def is_quick_vocals(self) -> bool:
            return self._section._demucs_is_quick_vocals()

        def is_quick_instrumental(self) -> bool:
            return self._section._demucs_is_quick_instrumental()

        def is_all_stems(self) -> bool:
            return self._section._demucs_is_all_stems()

        def needs_export_filter(self) -> bool:
            return self._section._demucs_needs_export_filter()

        @property
        def _focus_map(self) -> Dict[str, str]:
            return self._section._demucs_focus_map

    @property
    def _quick_export(self) -> _QuickExportProxy:
        return self._QuickExportProxy(self)

    @property
    def _subset(self) -> _SubsetProxy:
        return self._SubsetProxy(self)

    @property
    def _demucs_focus(self) -> _DemucsFocusProxy:
        return self._DemucsFocusProxy(self)
