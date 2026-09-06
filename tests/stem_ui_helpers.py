"""Legacy test vocabulary over the real Save Stems controls."""

from __future__ import annotations

import typing
from typing import Dict, List, Set

from bundled.constants import ALL_STEMS
from core.stem_selection import _QUICK_ALL
from ui.widgets.rows import get_combo_value, set_combo_value
from ui.widgets.stem_only import SaveStemsSection


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
    def _chips(self) -> Dict[str, "_ChipProxy"]:
        ids = self._section._subset_ids()
        chips: Dict[str, _ChipProxy] = {ALL_STEMS: _ChipProxy(self._section, ALL_STEMS)}
        for stem in self._section._subset_stems:
            proxy = _ChipProxy(self._section, stem)
            chips[stem] = proxy
            concept = ids.get(stem, stem)
            chips.setdefault(concept, proxy)
        return chips

    def rebuild(self, stems: List[str], *, stem_label_overrides: typing.Any = None) -> None:
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
        return self._section._natives_in_selection(self._section._custom_selected)

    def is_all_active(self) -> bool:
        return self._section._custom_all


class _ChipProxy:
    def __init__(self, section: "SaveStemsSection", stem: str):
        self._section = section
        self._stem = stem

    def get_active(self) -> bool:
        if self._stem == ALL_STEMS:
            return self._section._custom_all
        concept = self._section._subset_token_id(self._stem)
        return (not self._section._custom_all) and (
            concept in self._section._custom_selected
            or self._stem in self._section._custom_selected
        )


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
