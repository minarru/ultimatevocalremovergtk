"""Immutable presentation over the existing core stem selection reducer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from bundled.constants import ALL_STEMS
from core.stem_selection import (
    _FOCUS_INSTRUMENTAL,
    _FOCUS_VOCALS,
    _QUICK_ALL,
    _QUICK_INSTRUMENTAL,
    _QUICK_VOCALS,
    _TOGGLE_ALL,
    StemSelectionState,
)
from core.stems import StemBucket, concept_is

from .help_text import (
    DEMUCS_STEMS_SAVE_HELP,
    MDX_STEMS_HINT,
    SAVE_STEM_ONLY_HELP,
    SAVE_STEMS_NO_MODEL_HELP,
)
from .stem_labels import (
    _REFRESH_REPICK_SUMMARY,
    StemOnlyOption,
    _export_label_for_choice,
    _subset_option_ids,
    stem_display_label,
)


@dataclass(frozen=True)
class StemPresentation:
    mode: str
    visible_rows: tuple[str, ...]
    choices: tuple[StemOnlyOption, ...]
    export_summary: str
    custom_subtitle: str
    quick_opacity: float
    custom_opacity: float
    expected_count: int
    hint: str


def project_stems(
    state: StemSelectionState,
    *,
    exclusive_choice: str = _TOGGLE_ALL,
    exclusive_options: Sequence[StemOnlyOption] = (),
    quick_visible: bool = False,
    demucs_active: str = _QUICK_ALL,
    demucs_export_choice: str = _TOGGLE_ALL,
    demucs_export_visible: bool = False,
    demucs_export_options: Sequence[StemOnlyOption] = (),
    overrides: Mapping[str, str] | None = None,
    repick: bool = False,
    semantics: str = '',
) -> StemPresentation:
    ids = _subset_option_ids(state.subset_stems, state.routes)
    selected = [
        stem
        for stem in state.subset_stems
        if stem in state.custom_selected or ids.get(stem, stem) in state.custom_selected
    ]

    def route_for(stem: str):
        return next(
            (
                route
                for route in state.routes
                if route.native is not None and route.native.matches(stem)
            ),
            None,
        )

    def label(stem: str) -> str:
        route = route_for(stem)
        return (
            route.label
            if route is not None
            else stem_display_label(stem, overrides=dict(overrides) if overrides else None)
        )

    labels = [label(stem) for stem in selected]
    custom = state.subset_mode == 'custom'
    subtitle = (
        'Open to choose specific stems'
        if not custom
        else ALL_STEMS
        if state.custom_all or not state.custom_selected
        else ', '.join(labels) or ALL_STEMS
    )
    visible: tuple[str, ...] = ()
    summary = SAVE_STEMS_NO_MODEL_HELP
    if state.has_model:
        if state.mode == 'exclusive':
            visible = ('exclusive',)
            summary = _export_label_for_choice(
                exclusive_choice, {option.name: option for option in exclusive_options}
            )
        elif state.mode == 'subset':
            visible = ('quick', 'custom') if quick_visible else ('custom',)
            if state.subset_mode == _QUICK_INSTRUMENTAL:
                summary = 'Exporting Instrumental only (derived)'
            elif state.subset_mode == _QUICK_VOCALS:
                summary = 'Exporting Vocals only'
            elif state.subset_mode == _QUICK_ALL or state.custom_all or not selected:
                summary = 'Exporting all stems'
            elif (
                len(selected) == 1
                and route_for(selected[0]) is None
                and concept_is(selected[0], StemBucket.OTHER, stem_count=len(state.subset_stems))
            ):
                summary = 'Exporting Other stem'
            else:
                summary = 'Exporting ' + ', '.join(labels)
        elif state.mode == 'demucs':
            visible = (
                ('demucs_focus', 'demucs_export')
                if state.demucs_needs_export_filter(demucs_active)
                else ('demucs_focus',)
            )
            if demucs_active == _QUICK_ALL:
                summary = 'Exporting all stems'
            elif demucs_active == _FOCUS_INSTRUMENTAL:
                summary = 'Exporting Instrumental only (derived)'
            elif demucs_active == _FOCUS_VOCALS:
                summary = 'Exporting Vocals only'
            else:
                focus = stem_display_label(state.demucs_focus_value(demucs_active))
                summary = (
                    _export_label_for_choice(
                        demucs_export_choice,
                        {option.name: option for option in demucs_export_options},
                    ).replace('Exporting', f'{focus} focus —', 1)
                    if demucs_export_visible
                    else f'{focus} focus — {focus} only'
                )
        if repick:
            summary = _REFRESH_REPICK_SUMMARY
    count = (
        0
        if repick
        else state.expected_output_count(
            exclusive_choice=exclusive_choice,
            demucs_active=demucs_active,
            demucs_export_choice=demucs_export_choice,
            demucs_export_visible=demucs_export_visible,
        )
    )
    hint = semantics or (
        MDX_STEMS_HINT
        if state.mode == 'subset'
        else DEMUCS_STEMS_SAVE_HELP
        if state.mode == 'demucs'
        else SAVE_STEM_ONLY_HELP
    )
    return StemPresentation(
        state.mode,
        visible,
        tuple(exclusive_options if state.mode == 'exclusive' else demucs_export_options),
        summary,
        subtitle,
        0.55 if quick_visible and custom else 1.0,
        0.55 if quick_visible and not custom else 1.0,
        count,
        hint,
    )
