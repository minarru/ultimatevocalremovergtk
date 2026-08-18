"""GTK-free Save Stems persist/sync: ``process.stem_focus`` in lockstep with flags."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Set

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    DRUM_STEM,
    OTHER_STEM,
    VOCAL_STEM,
    secondary_stem,
)
from core.model_stem_semantics import confident_stem_bucket
from core.settings.access import get_flat, set_flat
from core.settings.model import Settings
from core.stems import (
    EnsemblePair,
    StemBucket,
    bucket_for_model_stem,
    concept_is,
    exclusive_flags_for_pair,
    focus_matches_stem,
)

_TOGGLE_ALL = "all"
_QUICK_ALL = "quick_all"
_QUICK_INSTRUMENTAL = "quick_instrumental"
_QUICK_VOCALS = "quick_vocals"
_FOCUS_INSTRUMENTAL = "focus_instrumental"
_FOCUS_VOCALS = "focus_vocals"
_SUBSET_CUSTOM = "custom"

_STEM_ALIASES = {
    "both": "both",
    "all": "both",
    "primary": "primary",
    "secondary": "secondary",
    "vocals": "vocals",
    "vocal": "vocals",
    "instrumental": "instrumental",
    "inst": "instrumental",
    "bass": "bass",
    "drums": "drums",
    "drum": "drums",
    "other": "other",
}


def _stem_focus_tag(
    stem: str,
    *,
    stem_count: int,
    is_karaoke: bool,
    is_karaoke_curated: bool,
    is_bv: bool,
) -> str:
    """Focus-anchor tag for one stem: a bucket tag when recognized, or a
    raw-name tag when not.

    Every unrecognized stem (DeEcho/DeNoise/DeReverb-style pairs, crowd/
    woodwinds removers, ...) collapses to the same StemBucket.UNKNOWN, so
    anchoring on the bucket directly would make two *different* stems on
    the *same* model compare equal -- the anchor would false-match and
    silently flip which stem gets exported, exactly the bug this
    mechanism exists to prevent. Falling back to the casefolded raw name
    keeps each unrecognized stem distinct.
    """
    bucket = confident_stem_bucket(
        stem,
        stem_count=stem_count,
        is_karaoke=is_karaoke,
        is_karaoke_curated=is_karaoke_curated,
        is_bv=is_bv,
    )
    if bucket == StemBucket.UNKNOWN.value:
        return f"raw:{str(stem).strip().casefold()}"
    return bucket


def _exclusive_name_from_settings(
    settings: Any, primary_key: str, secondary_key: str
) -> str:
    primary_on = bool(get_flat(settings, primary_key))
    secondary_on = bool(get_flat(settings, secondary_key))
    if primary_on and not secondary_on:
        return primary_key
    if secondary_on and not primary_on:
        return secondary_key
    return _TOGGLE_ALL


def _persist_exclusive_choice(
    settings: Any, primary_key: str, secondary_key: str, name: str
) -> None:
    set_flat(settings, primary_key, name == primary_key)
    set_flat(settings, secondary_key, name == secondary_key)


def _exclusive_name_from_focus(
    settings: Any,
    *,
    primary_stem: Optional[str],
    secondary_stem_name: Optional[str],
    primary_key: str,
    secondary_key: str,
    is_karaoke: bool,
    is_karaoke_curated: bool,
    is_bv: bool,
    stem_count: int,
    ensemble_pair: Optional[EnsemblePair] = None,
) -> Optional[str]:
    """Resolve the exclusive-mode combo choice from ``process.stem_focus``.

    Returns ``None`` when no focus is recorded yet (caller falls back to
    ``_exclusive_name_from_settings``'s legacy boolean-based read). Once a
    focus is recorded, always returns a definite choice -- ``primary_key``/
    ``secondary_key`` on a match, or ``_TOGGLE_ALL`` when neither of this
    model's stems match (a different, unrelated pair type).
    """
    focus = getattr(settings.process, "stem_focus", "") or ""
    if not focus:
        return None
    if ensemble_pair is not None:
        flags = exclusive_flags_for_pair(focus, ensemble_pair)
        if flags == (True, False):
            return primary_key
        if flags == (False, True):
            return secondary_key
        return _TOGGLE_ALL
    ctx = {
        "stem_count": stem_count,
        "is_karaoke": is_karaoke,
        "is_bv": is_bv,
    }
    if primary_stem and focus_matches_stem(focus, primary_stem, **ctx):
        return primary_key
    if secondary_stem_name and focus_matches_stem(focus, secondary_stem_name, **ctx):
        return secondary_key
    return _TOGGLE_ALL


def _stem_focus_for_choice(
    name: str,
    *,
    primary_stem: Optional[str],
    secondary_stem_name: Optional[str],
    primary_key: str,
    secondary_key: str,
    is_karaoke: bool,
    is_karaoke_curated: bool,
    is_bv: bool,
    stem_count: int,
    ensemble_pair: Optional[EnsemblePair] = None,
) -> str:
    """Focus tag to persist as ``process.stem_focus`` for an exclusive pick."""
    if ensemble_pair is not None:
        primary_b, secondary_b = ensemble_pair.buckets()
        if name == primary_key and primary_b is not StemBucket.UNKNOWN:
            return primary_b.value
        if name == secondary_key and secondary_b is not StemBucket.UNKNOWN:
            return secondary_b.value
        return ""
    if name == primary_key and primary_stem:
        stem = primary_stem
    elif name == secondary_key and secondary_stem_name:
        stem = secondary_stem_name
    else:
        return ""
    return _stem_focus_tag(
        stem,
        stem_count=stem_count,
        is_karaoke=is_karaoke,
        is_karaoke_curated=is_karaoke_curated,
        is_bv=is_bv,
    )


def _write_cli_exclusive(settings: Settings, primary: bool, secondary: bool) -> None:
    settings.process.primary_stem_only = primary
    settings.process.secondary_stem_only = secondary
    settings.demucs.is_primary_stem_only = primary
    settings.demucs.is_secondary_stem_only = secondary


def apply_stem_selection(settings: Settings, selection: str) -> str:
    tokens = {
        _STEM_ALIASES.get(part.strip().casefold(), "")
        for part in str(selection).replace(";", ",").split(",")
        if part.strip()
    }
    if "" in tokens or not tokens:
        raise ValueError(f"invalid stem selection {selection!r}")

    def exclusive(primary: bool, secondary: bool) -> None:
        _write_cli_exclusive(settings, primary, secondary)

    def clear_focus() -> None:
        settings.process.stem_focus = ""

    if "both" in tokens or tokens >= {"vocals", "instrumental"}:
        exclusive(False, False)
        clear_focus()
        settings.demucs.stems = settings.mdx.stems = ALL_STEMS
        settings.mdx.stems_selected = []
        return "both"
    if len(tokens) != 1:
        raise ValueError(f"ambiguous stem selection {selection!r}")
    choice = next(iter(tokens))
    if choice in {"primary", "secondary"}:
        exclusive(choice == "primary", choice == "secondary")
        clear_focus()
        settings.mdx.stems = ALL_STEMS
        settings.mdx.stems_selected = []
        return choice
    if choice in {"vocals", "instrumental"}:
        exclusive(False, False)
        settings.process.stem_focus = (
            StemBucket.VOCALS.value
            if choice == "vocals"
            else StemBucket.INSTRUMENTAL.value
        )
        settings.demucs.stems = settings.mdx.stems = VOCAL_STEM
        settings.mdx.stems_selected = [VOCAL_STEM]
        return choice
    focus = {"bass": BASS_STEM, "drums": DRUM_STEM, "other": OTHER_STEM}[choice]
    exclusive(False, False)
    settings.process.stem_focus = focus
    settings.demucs.stems = focus
    settings.mdx.stems = ALL_STEMS
    settings.mdx.stems_selected = []
    return choice


@dataclass
class ExclusiveView:
    choice: str


@dataclass
class SubsetView:
    mode: str
    selected: Set[str]
    custom_all: bool


@dataclass
class DemucsView:
    active: str
    export_choice: str
    export_filter_visible: bool


class StemSelectionState:
    """Configure context plus persist/sync for one Save Stems section."""

    def __init__(self) -> None:
        self.mode = "hidden"
        self.has_model = False
        self.primary_key = "is_primary_stem_only"
        self.secondary_key = "is_secondary_stem_only"
        self.subset_stems: list[str] = []
        self.exclusive_primary: Optional[str] = None
        self.exclusive_secondary: Optional[str] = None
        self.is_karaoke = False
        self.is_karaoke_curated = False
        self.is_bv = False
        self.stem_count = 2
        self.ensemble_pair: Optional[EnsemblePair] = None
        self.demucs_export_primary: Optional[str] = None
        self.demucs_export_secondary: Optional[str] = None
        self.subset_mode = _QUICK_ALL
        self.demucs_stem_count = 4
        self.demucs_focus_map: dict[str, str] = {}
        self.custom_selected: Set[str] = set()
        self.custom_all = True

    def configure_hidden(self, *, has_model: bool = False) -> None:
        self.mode = "hidden"
        self.has_model = has_model

    def configure_exclusive(
        self,
        *,
        primary_stem: Optional[str],
        secondary_stem: Optional[str],
        primary_key: str,
        secondary_key: str,
        has_model: bool = True,
        is_karaoke: bool = False,
        is_karaoke_curated: bool = False,
        is_bv: bool = False,
        stem_count: int = 2,
        ensemble_pair: Optional[EnsemblePair] = None,
    ) -> None:
        self.mode = "exclusive"
        self.has_model = has_model
        self.primary_key = primary_key
        self.secondary_key = secondary_key
        self.exclusive_primary = primary_stem
        self.exclusive_secondary = secondary_stem
        self.is_karaoke = is_karaoke
        self.is_karaoke_curated = is_karaoke_curated
        self.is_bv = is_bv
        self.stem_count = stem_count
        self.ensemble_pair = ensemble_pair

    def configure_subset(
        self,
        *,
        stems: list[str],
        primary_key: str,
        secondary_key: str,
        has_model: bool = True,
    ) -> None:
        self.mode = "subset"
        self.has_model = has_model
        self.primary_key = primary_key
        self.secondary_key = secondary_key
        self.subset_stems = [s for s in stems if s != ALL_STEMS]
        self.subset_mode = _QUICK_ALL
        self.custom_selected = set()
        self.custom_all = True

    def configure_demucs(
        self,
        *,
        focus_stems: list[str],
        primary_key: str,
        secondary_key: str,
        has_model: bool = True,
        demucs_stem_count: int = 4,
    ) -> None:
        self.mode = "demucs"
        self.has_model = has_model
        self.demucs_stem_count = max(1, demucs_stem_count)
        self.primary_key = primary_key
        self.secondary_key = secondary_key
        self.demucs_focus_map = {}
        for entry in focus_stems:
            if entry == ALL_STEMS:
                self.demucs_focus_map[_QUICK_ALL] = ALL_STEMS
            elif entry == _FOCUS_INSTRUMENTAL:
                self.demucs_focus_map[_FOCUS_INSTRUMENTAL] = _FOCUS_INSTRUMENTAL
            elif entry == _FOCUS_VOCALS:
                self.demucs_focus_map[_FOCUS_VOCALS] = _FOCUS_VOCALS
            else:
                self.demucs_focus_map[entry] = entry

    def vocal_stem_in_subset(self) -> Optional[str]:
        count = len(self.subset_stems)
        for stem in self.subset_stems:
            if concept_is(stem, StemBucket.VOCALS, stem_count=count):
                return stem
        return None

    def selection_matches_vocal_stem(self, selected: Set[str]) -> bool:
        if not selected or len(selected) != 1:
            return False
        chosen = next(iter(selected))
        return concept_is(
            chosen, StemBucket.VOCALS, stem_count=len(self.subset_stems)
        )

    def set_custom_selection(
        self,
        selected: Set[str],
        *,
        highlight_all_when_empty: bool = True,
    ) -> None:
        stem_set = set(self.subset_stems)
        if not selected:
            self.custom_all = highlight_all_when_empty
            self.custom_selected = set()
        elif selected >= stem_set:
            self.custom_all = True
            self.custom_selected = set()
        else:
            self.custom_all = False
            self.custom_selected = set(selected)

    def apply_subset_chip_selection(self, mode: str, selected: Set[str]) -> None:
        if mode == _QUICK_INSTRUMENTAL:
            self.set_custom_selection(set(), highlight_all_when_empty=False)
        elif mode == _QUICK_VOCALS:
            vocal = self.vocal_stem_in_subset()
            self.set_custom_selection(
                {vocal} if vocal else set(),
                highlight_all_when_empty=False,
            )
        elif mode == _QUICK_ALL:
            self.set_custom_selection(set(), highlight_all_when_empty=True)
        else:
            self.set_custom_selection(selected, highlight_all_when_empty=True)

    def stored_subset_selection(self, settings: Any) -> tuple[str, Set[str]]:
        selected = list(settings.mdx.stems_selected or [])
        if not selected:
            legacy = settings.mdx.stems
            if legacy and legacy != ALL_STEMS:
                selected = [legacy]
        selected_set = set(selected)
        stem_set = set(self.subset_stems)
        primary_on = bool(get_flat(settings, self.primary_key))
        secondary_on = bool(get_flat(settings, self.secondary_key))

        if self.vocal_stem_in_subset() and self.selection_matches_vocal_stem(
            selected_set
        ):
            if secondary_on and not primary_on:
                return _QUICK_INSTRUMENTAL, selected_set
            if primary_on and not secondary_on:
                return _QUICK_VOCALS, selected_set
        if not selected_set or selected_set >= stem_set:
            if not primary_on and not secondary_on:
                return _QUICK_ALL, stem_set
        return _SUBSET_CUSTOM, selected_set

    def demucs_focus_value(self, active: str) -> str:
        return self.demucs_focus_map.get(active, ALL_STEMS)

    def demucs_needs_export_filter(self, active: str) -> bool:
        return active not in (_QUICK_ALL, _FOCUS_INSTRUMENTAL, _FOCUS_VOCALS)

    def read(self, settings: Any) -> ExclusiveView | SubsetView | DemucsView | None:
        if self.mode == "exclusive":
            name = _exclusive_name_from_focus(
                settings,
                primary_stem=self.exclusive_primary,
                secondary_stem_name=self.exclusive_secondary,
                primary_key=self.primary_key,
                secondary_key=self.secondary_key,
                is_karaoke=self.is_karaoke,
                is_karaoke_curated=self.is_karaoke_curated,
                is_bv=self.is_bv,
                stem_count=self.stem_count,
                ensemble_pair=self.ensemble_pair,
            )
            if name is None:
                name = _exclusive_name_from_settings(
                    settings, self.primary_key, self.secondary_key
                )
            else:
                _persist_exclusive_choice(
                    settings, self.primary_key, self.secondary_key, name
                )
            return ExclusiveView(choice=name)
        if self.mode == "subset":
            mode, selected = self.stored_subset_selection(settings)
            self.subset_mode = mode
            self.apply_subset_chip_selection(mode, selected)
            return SubsetView(
                mode=mode,
                selected=set(self.custom_selected),
                custom_all=self.custom_all,
            )
        if self.mode == "demucs":
            focus = settings.demucs.stems or ALL_STEMS
            primary_on = bool(get_flat(settings, self.primary_key))
            secondary_on = bool(get_flat(settings, self.secondary_key))
            focus_is_vocals = concept_is(str(focus), StemBucket.VOCALS, stem_count=4)
            if focus == ALL_STEMS:
                active = _QUICK_ALL
            elif focus_is_vocals and secondary_on and not primary_on:
                active = _FOCUS_INSTRUMENTAL
            elif focus_is_vocals and primary_on and not secondary_on:
                active = _FOCUS_VOCALS
            else:
                active = focus
            export_filter = self.demucs_needs_export_filter(active)
            if export_filter:
                native = self.demucs_focus_value(active)
                self.demucs_export_primary = native
                self.demucs_export_secondary = secondary_stem(native)
                export_choice = _exclusive_name_from_settings(
                    settings, self.primary_key, self.secondary_key
                )
            else:
                export_choice = _TOGGLE_ALL
            return DemucsView(
                active=active,
                export_choice=export_choice,
                export_filter_visible=export_filter,
            )
        return None

    def write(
        self,
        settings: Any,
        view: ExclusiveView | SubsetView | DemucsView,
    ) -> None:
        if isinstance(view, ExclusiveView):
            _persist_exclusive_choice(
                settings, self.primary_key, self.secondary_key, view.choice
            )
            settings.process.stem_focus = _stem_focus_for_choice(
                view.choice,
                primary_stem=self.exclusive_primary,
                secondary_stem_name=self.exclusive_secondary,
                primary_key=self.primary_key,
                secondary_key=self.secondary_key,
                is_karaoke=self.is_karaoke,
                is_karaoke_curated=self.is_karaoke_curated,
                is_bv=self.is_bv,
                stem_count=self.stem_count,
                ensemble_pair=self.ensemble_pair,
            )
            return
        if isinstance(view, SubsetView):
            self._write_subset(settings, view)
            return
        self._write_demucs(settings, view)

    def _write_subset(self, settings: Any, view: SubsetView) -> None:
        if view.mode != _SUBSET_CUSTOM:
            if view.mode == _QUICK_ALL:
                settings.mdx.stems_selected = []
                settings.mdx.stems = ALL_STEMS
                settings.process.stem_focus = ""
                set_flat(settings, self.primary_key, False)
                set_flat(settings, self.secondary_key, False)
            elif view.mode == _QUICK_INSTRUMENTAL:
                settings.mdx.stems_selected = [VOCAL_STEM]
                settings.mdx.stems = VOCAL_STEM
                settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
                set_flat(settings, self.primary_key, False)
                set_flat(settings, self.secondary_key, True)
            elif view.mode == _QUICK_VOCALS:
                settings.mdx.stems_selected = [VOCAL_STEM]
                settings.mdx.stems = VOCAL_STEM
                settings.process.stem_focus = StemBucket.VOCALS.value
                set_flat(settings, self.primary_key, True)
                set_flat(settings, self.secondary_key, False)
            return

        if view.custom_all or not view.selected or view.selected >= set(
            self.subset_stems
        ):
            settings.mdx.stems_selected = []
            settings.mdx.stems = ALL_STEMS
            settings.process.stem_focus = ""
        else:
            selected = [stem for stem in self.subset_stems if stem in view.selected]
            settings.mdx.stems_selected = selected
            settings.mdx.stems = selected[0] if len(selected) == 1 else ALL_STEMS
            if len(selected) == 1:
                bucket = bucket_for_model_stem(
                    selected[0], stem_count=len(self.subset_stems)
                )
                settings.process.stem_focus = (
                    bucket.value
                    if bucket is not StemBucket.UNKNOWN
                    else f"raw:{selected[0].strip().casefold()}"
                )
            else:
                settings.process.stem_focus = ""
        set_flat(settings, self.primary_key, False)
        set_flat(settings, self.secondary_key, False)

    def _write_demucs(self, settings: Any, view: DemucsView) -> None:
        active = view.active
        if active == _QUICK_ALL:
            settings.demucs.stems = ALL_STEMS
            settings.process.stem_focus = ""
            set_flat(settings, self.primary_key, False)
            set_flat(settings, self.secondary_key, False)
            return
        if active == _FOCUS_INSTRUMENTAL:
            settings.demucs.stems = VOCAL_STEM
            settings.process.stem_focus = StemBucket.INSTRUMENTAL.value
            set_flat(settings, self.primary_key, False)
            set_flat(settings, self.secondary_key, True)
            return
        if active == _FOCUS_VOCALS:
            settings.demucs.stems = VOCAL_STEM
            settings.process.stem_focus = StemBucket.VOCALS.value
            set_flat(settings, self.primary_key, True)
            set_flat(settings, self.secondary_key, False)
            return

        settings.demucs.stems = active
        if view.export_filter_visible:
            name = view.export_choice or _TOGGLE_ALL
            _persist_exclusive_choice(
                settings, self.primary_key, self.secondary_key, name
            )
            if name == self.primary_key:
                settings.process.stem_focus = _stem_focus_tag(
                    active,
                    stem_count=self.demucs_stem_count,
                    is_karaoke=False,
                    is_karaoke_curated=False,
                    is_bv=False,
                )
            elif name == self.secondary_key:
                settings.process.stem_focus = _stem_focus_tag(
                    secondary_stem(active),
                    stem_count=2,
                    is_karaoke=False,
                    is_karaoke_curated=False,
                    is_bv=False,
                )
            else:
                settings.process.stem_focus = ""
            return
        set_flat(settings, self.primary_key, True)
        set_flat(settings, self.secondary_key, False)
        settings.process.stem_focus = _stem_focus_tag(
            active,
            stem_count=self.demucs_stem_count,
            is_karaoke=False,
            is_karaoke_curated=False,
            is_bv=False,
        )

    def ensure_demucs_export_defaults(self, settings: Any) -> None:
        """When a native-stem focus first shows the export filter, default to primary-only."""
        if not get_flat(settings, self.primary_key) and not get_flat(
            settings, self.secondary_key
        ):
            set_flat(settings, self.primary_key, True)
            set_flat(settings, self.secondary_key, False)

    def expected_output_count(
        self,
        *,
        exclusive_choice: str = _TOGGLE_ALL,
        demucs_active: str = _QUICK_ALL,
        demucs_export_choice: str = _TOGGLE_ALL,
        demucs_export_visible: bool = False,
    ) -> int:
        if not self.has_model or self.mode == "hidden":
            return 0
        if self.mode == "exclusive":
            return 2 if exclusive_choice == _TOGGLE_ALL else 1
        if self.mode == "subset":
            if self.subset_mode in (_QUICK_INSTRUMENTAL, _QUICK_VOCALS):
                return 1
            if self.subset_mode == _QUICK_ALL or self.custom_all:
                return max(1, len(self.subset_stems))
            if not self.custom_selected:
                return max(1, len(self.subset_stems))
            return len(self.custom_selected)
        if self.mode == "demucs":
            if demucs_active in (_FOCUS_INSTRUMENTAL, _FOCUS_VOCALS):
                return 1
            if demucs_active == _QUICK_ALL:
                return max(1, self.demucs_stem_count)
            if demucs_export_visible:
                return 2 if demucs_export_choice == _TOGGLE_ALL else 1
            return 1
        return 0
