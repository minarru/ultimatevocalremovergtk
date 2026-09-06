"""Save-stems controls: exclusive export, MDX subset, and Demucs focus."""

from __future__ import annotations

import typing
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from gi.repository import Adw, GLib, Gtk

from bundled.constants import (
    ALL_STEMS,
    secondary_stem,
)
from core.stem_selection import (
    _FOCUS_INSTRUMENTAL,
    _FOCUS_VOCALS,
    _QUICK_ALL,
    _QUICK_INSTRUMENTAL,
    _QUICK_VOCALS,
    _SUBSET_CUSTOM,
    _TOGGLE_ALL,
    DemucsView,
    ExclusiveView,
    StemSelectionState,
    SubsetView,
)
from core.stems import (
    StemRoute,
    persisted_stem_focus,
)

from ..dialogs.utils import present_modal_dialog, set_form_dialog_content
from ..help_text import (
    MDX_STEMS_HINT,
)
from ..markup import set_row_subtitle
from ..stem_labels import (
    _CHOOSE_STEM as _CHOOSE_STEM,
)
from ..stem_labels import (
    _CHOOSE_STEM_LABEL as _CHOOSE_STEM_LABEL,
)
from ..stem_labels import (
    _COMPLEMENT_DISPLAY as _COMPLEMENT_DISPLAY,
)
from ..stem_labels import (
    _LEAD_VOCAL_PAIR_LABELS as _LEAD_VOCAL_PAIR_LABELS,
)
from ..stem_labels import (
    _QUICK_EXPORT_HINTS as _QUICK_EXPORT_HINTS,
)
from ..stem_labels import (
    _QUICK_EXPORT_LABELS as _QUICK_EXPORT_LABELS,
)
from ..stem_labels import (
    _REFRESH_REPICK_SUMMARY as _REFRESH_REPICK_SUMMARY,
)
from ..stem_labels import (
    _STEM_ALIASES as _STEM_ALIASES,
)
from ..stem_labels import (
    _STEM_ONLY_ORDER as _STEM_ONLY_ORDER,
)
from ..stem_labels import (
    ALL_STEMS_ICON as ALL_STEMS_ICON,
)
from ..stem_labels import (
    STEM_ONLY_ICON_FALLBACK as STEM_ONLY_ICON_FALLBACK,
)
from ..stem_labels import (
    STEM_ONLY_ICONS as STEM_ONLY_ICONS,
)
from ..stem_labels import (
    StemOnlyOption as StemOnlyOption,
)
from ..stem_labels import (
    _exclusive_option_ids as _exclusive_option_ids,
)
from ..stem_labels import (
    _export_label_for_choice as _export_label_for_choice,
)
from ..stem_labels import (
    _stem_only_rank as _stem_only_rank,
)
from ..stem_labels import (
    _subset_option_ids as _subset_option_ids,
)
from ..stem_labels import (
    build_stem_only_options as build_stem_only_options,
)
from ..stem_labels import (
    canonical_stem_name as canonical_stem_name,
)
from ..stem_labels import (
    roformer_lead_vocal_label_overrides as roformer_lead_vocal_label_overrides,
)
from ..stem_labels import (
    stem_display_label as stem_display_label,
)
from ..stem_labels import (
    stem_only_icon as stem_only_icon,
)
from ..stem_labels import (
    stem_only_tooltip as stem_only_tooltip,
)
from ..stem_presentation import StemPresentation, project_stems
from ..template import load_builder, object_from_builder
from .rows import configure_combo_row, get_combo_value, set_combo_tag_values, set_combo_value


def _fill_export_combo(
    row: Adw.ComboRow, options: List[StemOnlyOption]
) -> Dict[str, StemOnlyOption]:
    set_combo_tag_values(row, [(opt.name, opt.display_label) for opt in options])
    return {opt.name: opt for opt in options}


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
        self._subset_quick_items: List[Tuple[str, str]] = []
        self._subset_quick_supported = False
        self._demucs_focus_items: List[Tuple[str, str]] = []
        self._demucs_export_options: Dict[str, StemOnlyOption] = {}
        self._draft_custom_selected: Set[str] = set()
        self._draft_custom_all = True
        self._custom_checks: Dict[str, Gtk.CheckButton] = {}
        self._host: Optional[Adw.PreferencesGroup] = None
        self._section_visible = False
        self._repick_required = False
        self._repick_restore_token: Optional[object] = None

        builder = load_builder("stem_only")
        self._holder = object_from_builder(builder, "stem_holder", Gtk.Box)
        self._exclusive_row = configure_combo_row(
            object_from_builder(builder, "exclusive_row", Adw.ComboRow), []
        )
        self._exclusive_row.connect("notify::selected", self._on_exclusive_changed)

        self._quick_row = configure_combo_row(
            object_from_builder(builder, "quick_row", Adw.ComboRow), []
        )
        self._quick_row.connect("notify::selected", self._on_quick_export_changed)

        self._custom_row = object_from_builder(builder, "custom_row", Adw.ActionRow)
        self._custom_row.connect("activated", self._open_custom_stems_dialog)

        self._demucs_focus_row = configure_combo_row(
            object_from_builder(builder, "demucs_focus_row", Adw.ComboRow), []
        )
        self._demucs_focus_row.connect("notify::selected", self._on_demucs_focus_changed)

        self._demucs_export_row = configure_combo_row(
            object_from_builder(builder, "demucs_export_row", Adw.ComboRow), []
        )
        self._demucs_export_row.connect("notify::selected", self._on_demucs_export_changed)

        self.selection_warning_row = object_from_builder(
            builder, "selection_warning_row", Adw.ActionRow
        )

        self._rows = (
            self._exclusive_row,
            self._quick_row,
            self._custom_row,
            self._demucs_focus_row,
            self._demucs_export_row,
            self.selection_warning_row,
        )
        # Compatibility aliases used by tests / metadata helpers.

        self._build_custom_stems_dialog(builder)
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

    def _build_custom_stems_dialog(self, builder: Gtk.Builder) -> None:
        self._custom_listbox = object_from_builder(builder, "custom_listbox", Gtk.ListBox)
        content = object_from_builder(builder, "custom_content", Gtk.Box)
        self._custom_dialog = object_from_builder(builder, "custom_dialog", Adw.Dialog)
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
        self._clear_refresh_repick()
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
        routes: Optional[Sequence[StemRoute]] = None,
    ) -> None:
        self._clear_refresh_repick()
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
        )
        if routes is not None:
            self._state.routes = tuple(routes)
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
            routes=self._state.routes,
        )
        was_loading = self._loading
        self._loading = True
        try:
            self._exclusive_options = _fill_export_combo(self._exclusive_row, options)
        finally:
            self._loading = was_loading
        self._exclusive_row.set_visible("exclusive" in self.presentation().visible_rows)
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
        routes: Optional[Sequence[StemRoute]] = None,
    ) -> None:
        self._clear_refresh_repick()
        self._subset_quick_supported = show_quick_export
        self._subset_quick_items = []
        self._state.configure_subset(
            stems=stems,
            primary_key=primary_key,
            secondary_key=secondary_key,
            has_model=has_model,
        )
        if routes is not None:
            self._state.routes = tuple(routes)
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
            if self._subset_quick_supported:
                self._subset_quick_items = [
                    (_QUICK_ALL, _QUICK_EXPORT_LABELS[_QUICK_ALL]),
                    (_QUICK_INSTRUMENTAL, _QUICK_EXPORT_LABELS[_QUICK_INSTRUMENTAL]),
                    (_QUICK_VOCALS, _QUICK_EXPORT_LABELS[_QUICK_VOCALS]),
                ]
            set_combo_tag_values(self._quick_row, self._subset_quick_items)
            self._quick_row.set_visible(self._subset_quick_supported)
            self._custom_row.set_visible("custom" in self.presentation().visible_rows)
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
        routes: Optional[Sequence[StemRoute]] = None,
    ) -> None:
        self._clear_refresh_repick()
        self._state.configure_demucs(
            focus_stems=focus_stems,
            primary_key=primary_key,
            secondary_key=secondary_key,
            has_model=has_model,
            demucs_stem_count=demucs_stem_count,
        )
        if routes is not None:
            self._state.routes = tuple(routes)
            self._state.demucs_focus_map = {
                **self._state.demucs_focus_map,
                **{
                    route.concept: (route.native.raw if route.native is not None else route.concept)
                    for route in routes
                },
            }
        self._stem_label_overrides = None
        self._export_semantics_note = export_semantics_note or ""
        self._hide_all_rows()
        if not has_model:
            self._section_visible = False
            return
        self._section_visible = True
        items: List[Tuple[str, str]] = []
        route_by_native = {
            route.native.casefold(): route
            for route in self._state.routes
            if route.native is not None
        }
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
                route = route_by_native.get(str(entry).strip().casefold())
                if route is None:
                    route = next(
                        (
                            candidate
                            for candidate in self._state.routes
                            if candidate.concept == entry
                        ),
                        None,
                    )
                name = route.concept if route is not None else entry
                label = route.label if route is not None else stem_display_label(entry)
            items.append((name, label))
        self._demucs_focus_items = list(items)
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
        if self._repick_required:
            return
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

    def presentation(self) -> StemPresentation:
        return project_stems(
            self._state,
            exclusive_choice=get_combo_value(self._exclusive_row) or _TOGGLE_ALL,
            exclusive_options=tuple(self._exclusive_options.values()),
            quick_visible=self._quick_row.get_visible(),
            demucs_active=self._demucs_active_name(),
            demucs_export_choice=get_combo_value(self._demucs_export_row) or _TOGGLE_ALL,
            demucs_export_visible=self._demucs_export_row.get_visible(),
            demucs_export_options=tuple(self._demucs_export_options.values()),
            overrides=self._stem_label_overrides,
            repick=self._repick_required,
            semantics=self._export_semantics_note,
        )

    def export_summary(self) -> str:
        return self.presentation().export_summary

    def export_description_lines(self) -> List[str]:
        """Group description lines (summary only; semantics live on the row)."""
        return [self.export_summary()]

    def expected_output_count(self) -> int:
        return self.presentation().expected_count

    def active_hint(self) -> str:
        return self.presentation().hint

    @property
    def repick_required(self) -> bool:
        return self._repick_required

    def require_refresh_repick(self, previous_focus: str) -> bool:
        """Require an explicit pick when a stored exact role disappeared."""
        focus = str(previous_focus or "")
        if not focus or focus in {"primary", "secondary"}:
            self._clear_refresh_repick()
            return False
        valid = any(persisted_stem_focus(route) == focus for route in self._state.routes)
        if valid:
            self._clear_refresh_repick()
            return False
        self._repick_restore_token = None
        self._repick_required = True
        self.selection_warning_row.set_visible(True)
        if self.mode == "exclusive":
            options = [
                StemOnlyOption(
                    _CHOOSE_STEM, "Choose an available stem", _CHOOSE_STEM_LABEL, None, None
                ),
                *self._exclusive_options.values(),
            ]
            was_loading = self._loading
            self._loading = True
            try:
                _fill_export_combo(self._exclusive_row, options)
                set_combo_value(self._exclusive_row, _CHOOSE_STEM)
            finally:
                self._loading = was_loading
        elif self.mode == "subset":
            was_loading = self._loading
            self._loading = True
            try:
                set_combo_tag_values(
                    self._quick_row,
                    [(_CHOOSE_STEM, "Choose Stems"), *self._subset_quick_items],
                )
                self._quick_row.set_visible(True)
                set_combo_value(self._quick_row, _CHOOSE_STEM)
                set_row_subtitle(self._custom_row, "Choose stems again")
            finally:
                self._loading = was_loading
        elif self.mode == "demucs":
            was_loading = self._loading
            self._loading = True
            try:
                set_combo_tag_values(
                    self._demucs_focus_row,
                    [(_CHOOSE_STEM, _CHOOSE_STEM_LABEL), *self._demucs_focus_items],
                )
                set_combo_value(self._demucs_focus_row, _CHOOSE_STEM)
            finally:
                self._loading = was_loading
        return True

    def _clear_refresh_repick(self, *, keep_pending_restore: bool = False) -> None:
        self._repick_required = False
        if not keep_pending_restore:
            self._repick_restore_token = None
        warning = getattr(self, "selection_warning_row", None)
        if warning is not None:
            warning.set_visible(False)

    def _complete_refresh_repick(self, selected: Optional[str] = None) -> None:
        """Remove temporary review choices after one valid explicit replacement."""
        if not self._repick_required:
            return
        token = object()
        self._repick_restore_token = token
        self._clear_refresh_repick(keep_pending_restore=True)
        GLib.idle_add(self._restore_refresh_repick_choices, token, self.mode, selected)

    def _restore_refresh_repick_choices(
        self,
        token: object,
        mode: str,
        selected: Optional[str],
    ) -> bool:
        """Restore a combo after its selection notification has returned to GTK."""
        if token is not self._repick_restore_token or mode != self.mode:
            return False
        self._repick_restore_token = None
        was_loading = self._loading
        self._loading = True
        try:
            if mode == "exclusive":
                _fill_export_combo(
                    self._exclusive_row,
                    list(self._exclusive_options.values()),
                )
                if selected is not None:
                    set_combo_value(self._exclusive_row, selected)
            elif mode == "subset":
                set_combo_tag_values(self._quick_row, self._subset_quick_items)
                self._quick_row.set_visible(self._subset_quick_supported)
                if selected is not None:
                    set_combo_value(self._quick_row, selected)
                self._refresh_custom_subtitle()
                self._apply_subset_dimming()
            elif mode == "demucs":
                set_combo_tag_values(self._demucs_focus_row, self._demucs_focus_items)
                if selected is not None:
                    set_combo_value(self._demucs_focus_row, selected)
        finally:
            self._loading = was_loading
        return False

    # -- Exclusive -------------------------------------------------------------

    def _on_exclusive_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        choice = get_combo_value(self._exclusive_row)
        if choice not in self._exclusive_options:
            return
        self._complete_refresh_repick(choice)
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
        presentation = self.presentation()
        self._quick_row.set_opacity(presentation.quick_opacity)
        self._custom_row.set_opacity(presentation.custom_opacity)
        self._quick_row.set_sensitive(True)
        self._custom_row.set_sensitive(True)

    def _vocal_stem_in_subset(self) -> Optional[str]:
        return self._state.vocal_stem_in_subset()

    def _subset_ids(self) -> Dict[str, str]:
        return _subset_option_ids(self._subset_stems, self._state.routes)

    def _subset_token_id(self, stem: str) -> str:
        return self._subset_ids().get(stem, stem)

    def _subset_route(self, stem: str) -> Optional[StemRoute]:
        return next(
            (
                route
                for route in self._state.routes
                if route.native is not None and route.native.matches(stem)
            ),
            None,
        )

    def _subset_label(self, stem: str) -> str:
        route = self._subset_route(stem)
        if route is not None:
            return route.label
        return stem_display_label(stem, overrides=self._stem_label_overrides)

    def _natives_in_selection(self, selected: Set[str]) -> List[str]:
        ids = self._subset_ids()
        return [
            stem
            for stem in self._subset_stems
            if ids.get(stem, stem) in selected or stem in selected
        ]

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

    def _refresh_custom_subtitle(self) -> None:
        set_row_subtitle(self._custom_row, self.presentation().custom_subtitle)

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

        ids = self._subset_ids()
        for stem in self._subset_stems:
            label = self._subset_label(stem)
            row = Adw.ActionRow(title=label)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.connect("toggled", self._on_draft_stem_toggled)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self._custom_listbox.append(row)
            self._custom_checks[ids.get(stem, stem)] = check

    def _sync_draft_checks(self) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            all_check = self._custom_checks.get(ALL_STEMS)
            if all_check is not None:
                all_check.set_active(self._draft_custom_all)
            ids = self._subset_ids()
            for stem in self._subset_stems:
                concept = ids.get(stem, stem)
                check = self._custom_checks.get(concept)
                if check is not None:
                    check.set_active(
                        (not self._draft_custom_all) and concept in self._draft_custom_selected
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
        present_modal_dialog(
            self._custom_dialog, parent if isinstance(parent, Gtk.Window) else None
        )

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
        ids = self._subset_ids()
        concept_set = {ids.get(stem, stem) for stem in self._subset_stems}
        self._draft_custom_selected = {
            ids.get(stem, stem)
            for stem in self._subset_stems
            if self._custom_checks.get(ids.get(stem, stem))
            and self._custom_checks[ids.get(stem, stem)].get_active()
        }
        if not self._draft_custom_selected or self._draft_custom_selected >= concept_set:
            self._draft_custom_all = True
            self._draft_custom_selected = set()
            if self._custom_checks.get(ALL_STEMS):
                was_loading = self._loading
                self._loading = True
                try:
                    self._custom_checks[ALL_STEMS].set_active(True)
                    for stem in self._subset_stems:
                        check = self._custom_checks.get(ids.get(stem, stem))
                        if check is not None:
                            check.set_active(False)
                finally:
                    self._loading = was_loading

    def _on_custom_stems_save(self) -> None:
        self._custom_all = self._draft_custom_all
        self._custom_selected = set(self._draft_custom_selected)
        self._subset_mode = "custom"
        self._complete_refresh_repick()
        self._refresh_custom_subtitle()
        self._apply_subset_dimming()
        self._custom_dialog.close()
        self._notify()

    def _on_quick_export_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        mode = get_combo_value(self._quick_row)
        valid_modes = {item_id for item_id, _label in self._subset_quick_items}
        if not self._subset_quick_supported or mode not in valid_modes:
            return
        self._complete_refresh_repick(mode)
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
                routes=self._state.demucs_export_routes(primary),
            )
            was_loading = self._loading
            self._loading = True
            try:
                self._demucs_export_options = _fill_export_combo(self._demucs_export_row, options)
                if not from_settings:
                    self._state.ensure_demucs_export_defaults(self.settings, native=primary)
                focus = str(getattr(self.settings.process, "stem_focus", "") or "")
                set_combo_value(
                    self._demucs_export_row,
                    self._state.export_choice_from_focus(primary, focus),
                )
            finally:
                self._loading = was_loading
            self._demucs_export_row.set_visible(True)
        else:
            self._demucs_export_row.set_visible(False)

    def _on_demucs_focus_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        active = get_combo_value(self._demucs_focus_row)
        valid_focuses = {item_id for item_id, _label in self._demucs_focus_items}
        if active not in valid_focuses:
            return
        self._complete_refresh_repick(active)
        self._update_demucs_export_visibility(from_settings=False)
        self._notify()

    def _on_demucs_export_changed(self, *_args: typing.Any) -> None:
        if self._loading or self._repick_required:
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
