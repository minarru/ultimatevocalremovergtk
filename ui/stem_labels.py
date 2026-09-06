"""Pure labels and stable native/concept choice IDs for Save Stems."""

from __future__ import annotations

import typing
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

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
)
from core.model_stem_semantics import (
    VOCALS_OTHER_DISPLAY_OVERRIDES,
    stem_display_overrides,
)
from core.stem_roles import StemLiteral
from core.stem_selection import (
    _QUICK_ALL,
    _QUICK_INSTRUMENTAL,
    _QUICK_VOCALS,
    _TOGGLE_ALL,
)
from core.stems import (
    StemBucket,
    StemRoute,
    bucket_for_model_stem,
    canonical_stem_alias,
    persisted_stem_focus,
)

from .help_text import (
    QUICK_EXPORT_INSTRUMENTAL_HINT,
    QUICK_EXPORT_VOCALS_HINT,
    STEM_ONLY_ALL_HINT,
    primary_stem_only_tooltip,
    secondary_stem_only_tooltip,
)

# Stable display order for "<stem> Only" entries.
_STEM_ONLY_ORDER = (INST_STEM, VOCAL_STEM, BASS_STEM, DRUM_STEM, OTHER_STEM)
_CHOOSE_STEM = "choose"
_CHOOSE_STEM_LABEL = "Choose Stem"
_REFRESH_REPICK_SUMMARY = "Choose a stem again after the model refresh"

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
    return (
        f"Export only {stem_display_label(stem, overrides=overrides)}; skip the other output file"
    )


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
    routes: Optional[Sequence[StemRoute]] = None,
) -> List[StemOnlyOption]:
    """Build export entries for All Stems + each stem's Only option."""
    options = [
        StemOnlyOption(_TOGGLE_ALL, STEM_ONLY_ALL_HINT, ALL_STEMS, ALL_STEMS_ICON, None),
    ]
    if routes and any(
        not isinstance(route.role, StemLiteral) or not route.role.tag.startswith("legacy:")
        for route in routes
    ):
        ordered_routes = sorted(routes, key=lambda route: not route.logical_primary)
        for index, route in enumerate(ordered_routes):
            stored_id = persisted_stem_focus(route)
            if not stored_id:
                continue
            settings_key = primary_key if index == 0 else secondary_key
            options.append(
                StemOnlyOption(
                    stored_id,
                    f"Export only {route.label}; skip the other output file",
                    route.label,
                    stem_only_icon(route.label),
                    settings_key,
                )
            )
        if len(options) > 1:
            return options
    if primary_stem and secondary_stem:
        entries = [
            (primary_stem, primary_key),
            (secondary_stem, secondary_key),
        ]
        option_ids = _exclusive_option_ids(
            primary_stem, secondary_stem, primary_key, secondary_key, routes
        )
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
                    _stem_only_rank(stem_display_label(entry[0], overrides=stem_label_overrides)),
                )
            )
        else:
            entries.sort(key=lambda entry: _stem_only_rank(entry[0]))
        for stem, key in entries:
            display = stem_display_label(stem, overrides=stem_label_overrides)
            options.append(
                StemOnlyOption(
                    option_ids.get(stem, key),
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


def _exclusive_option_ids(
    primary_stem: str,
    secondary_stem: str,
    primary_key: str,
    secondary_key: str,
    routes: Optional[Sequence[StemRoute]],
) -> Dict[str, str]:
    ids = {primary_stem: primary_key, secondary_stem: secondary_key}
    if not routes:
        return ids
    unused = list(routes)
    for stem in (primary_stem, secondary_stem):
        match = next(
            (route for route in unused if route.native is not None and route.native.matches(stem)),
            None,
        )
        if match is not None:
            ids[stem] = match.concept
            unused.remove(match)
    for stem in (primary_stem, secondary_stem):
        if ids[stem] in (primary_key, secondary_key) and unused:
            ids[stem] = unused.pop(0).concept
    return ids


def _subset_option_ids(
    stems: Sequence[str],
    routes: Optional[Sequence[StemRoute]],
) -> Dict[str, str]:
    ids = {stem: stem for stem in stems}
    if not routes:
        return ids
    unused = [route for route in routes if route.native is not None]
    for stem in stems:
        match = next(
            (route for route in unused if route.native is not None and route.native.matches(stem)),
            None,
        )
        if match is not None:
            ids[stem] = match.concept
            unused.remove(match)
    return ids


def _export_label_for_choice(name: str, options: Dict[str, StemOnlyOption]) -> str:
    if name == _TOGGLE_ALL:
        return "Exporting all outputs"
    option = options.get(name)
    if option is not None:
        return f"Exporting {option.display_label} only"
    return "Exporting selected outputs"
