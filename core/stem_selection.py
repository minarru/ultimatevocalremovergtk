"""GTK-free Save Stems persist/sync: ``process.stem_focus`` is the exclusive pick."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional, Sequence, Set

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    DRUM_STEM,
    OTHER_STEM,
    VOCAL_STEM,
    secondary_stem,
)
from core.model_stem_manifest import load_bundled_stem_semantics
from core.model_stem_semantics import confident_stem_bucket
from core.settings.model import Settings
from core.stem_roles import StemRoleId
from core.stems import (
    FOCUS_PRIMARY,
    FOCUS_SECONDARY,
    EnsemblePair,
    StemBucket,
    StemRoute,
    StemSelectionStatus,
    concept_is,
    derived_stem_route,
    exclusive_flags_for_pair,
    model_stem_routes,
    persisted_stem_focus,
    positional_stem_focus,
    select_stem_routes,
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

_LEGACY_ROUTE_ROLES = {
    StemBucket.VOCALS.value: "vocal.vocals",
    StemBucket.INSTRUMENTAL.value: "mix.instrumental",
    StemBucket.BASS.value: "instrument.bass",
    StemBucket.DRUMS.value: "instrument.drums",
    StemBucket.OTHER.value: "residual.other",
    StemBucket.GUITAR.value: "instrument.guitar",
    StemBucket.PIANO.value: "instrument.piano",
    StemBucket.LEAD_VOCALS.value: "vocal.lead",
    StemBucket.BACKING_VOCALS.value: "vocal.backing",
    StemBucket.INST_WITH_BV.value: "mix.instrumental_with_backing_vocals",
    StemBucket.INST_WITH_LEAD.value: "mix.instrumental_with_lead_vocals",
}

_LEGACY_REMOVAL_ROLES = {
    "no bass": "instrument.bass.removed",
    "no drums": "instrument.drums.removed",
    "noreverb": "effect.reverb.removed",
    "no reverb": "effect.reverb.removed",
    "nodry": "effect.reverb",
    "no dry": "effect.reverb",
    "noecho": "effect.echo.removed",
    "no echo": "effect.echo.removed",
}


def _legacy_role_for_tokens(tokens: Sequence[str]) -> str:
    """Map only exact legacy presentation values to one reviewed role.

    Save Stems does not yet receive an assembled model's exact route inventory.
    Its compatibility values can still be promoted when they are an exact
    reviewed role ID, display label, or filename tag.  Any collision or unknown
    stays unrepresentable here rather than guessing a semantic role.
    """
    candidates: set[str] = set()
    for token in tokens:
        normalized = str(token or "").strip().casefold()
        if not normalized:
            continue
        direct = _LEGACY_REMOVAL_ROLES.get(normalized)
        if direct is not None:
            candidates.add(direct)
        for role, definition in load_bundled_stem_semantics().roles.items():
            if normalized in {
                role.value.casefold(),
                definition.display.casefold(),
                definition.filename_tag.casefold(),
            }:
                candidates.add(role.value)
    return next(iter(candidates)) if len(candidates) == 1 else ""


def _persist_legacy_value(value: str) -> str:
    """Promote one identity-less compatibility value when it is reviewed."""
    return _LEGACY_ROUTE_ROLES.get(value) or _legacy_role_for_tokens((value,))


def _persist_route_focus(route: StemRoute) -> str:
    """Persist semantic roles, never an unscoped raw/display compatibility tag."""
    if isinstance(route.role, StemRoleId):
        return persisted_stem_focus(route)
    bucket_role = _LEGACY_ROUTE_ROLES.get(route.concept)
    if bucket_role is not None:
        return bucket_role
    literal = route.role.tag.removeprefix("legacy:")
    if literal.startswith("raw:"):
        literal = literal[4:]
    return _legacy_role_for_tokens((literal, route.label, route.filename_tag))


def _identityless_route_for_persisted_role(
    routes: Sequence[StemRoute], focus: str
) -> Optional[StemRoute]:
    """Re-select one legacy route from its exact persisted reviewed role ID."""
    try:
        role = StemRoleId(focus).value
    except ValueError:
        return None
    matches = [route for route in routes if _persist_route_focus(route) == role]
    return matches[0] if len(matches) == 1 else None


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


def _route_model(
    *,
    primary: Optional[str] = None,
    secondary: Optional[str] = None,
    natives: tuple[str, ...] = (),
    demucs_natives: tuple[str, ...] = (),
    is_karaoke: bool = False,
    is_bv: bool = False,
    demucs_stem_count: int = 0,
) -> Any:
    """Duck-typed context for :func:`model_stem_routes` (not a dry ModelConfig)."""
    return SimpleNamespace(
        primary_stem=primary,
        secondary_stem=secondary,
        is_karaoke=is_karaoke,
        is_bv_model=is_bv,
        is_vocal_split_model=False,
        mdx_model_stems=natives,
        demucs_source_list=demucs_natives,
        mdx_stem_count=len(natives),
        demucs_stem_count=demucs_stem_count or len(demucs_natives),
    )


def _exclusive_inventory(
    *,
    primary_stem: Optional[str],
    secondary_stem_name: Optional[str],
    is_karaoke: bool,
    is_bv: bool,
    ensemble_pair: Optional[EnsemblePair],
) -> tuple[StemRoute, ...]:
    """Route inventory for exclusive Save Stems.

    Ensemble pairs use derived bucket routes so native ``other`` is not
    remapped to Instrumental by a 2-stem ``stem_count``.
    """
    if ensemble_pair is not None:
        primary_b, secondary_b = ensemble_pair.buckets()
        routes: list[StemRoute] = []
        if primary_b is not StemBucket.UNKNOWN:
            routes.append(
                derived_stem_route(primary_b, label=primary_stem)
            )
        elif primary_stem:
            routes.append(derived_stem_route(primary_stem, label=primary_stem))
        if secondary_b is not StemBucket.UNKNOWN:
            routes.append(
                derived_stem_route(secondary_b, label=secondary_stem_name)
            )
        elif secondary_stem_name:
            routes.append(
                derived_stem_route(secondary_stem_name, label=secondary_stem_name)
            )
        return tuple(routes)
    natives = tuple(
        stem for stem in (primary_stem, secondary_stem_name) if stem
    )
    if not natives:
        return ()
    return model_stem_routes(
        _route_model(
            primary=primary_stem,
            secondary=secondary_stem_name,
            natives=natives,
            is_karaoke=is_karaoke,
            is_bv=is_bv,
        )
    )


def _route_for_native(
    routes: Sequence[StemRoute], stem: str
) -> Optional[StemRoute]:
    for route in routes:
        if route.native is not None and route.native.matches(stem):
            return route
    return None


def _cli_concept_inventory() -> tuple[StemRoute, ...]:
    return (
        StemRoute(None, StemRoleId("vocal.vocals"), label="Vocals"),
        StemRoute(None, StemRoleId("mix.instrumental"), label="Instrumental"),
        StemRoute(None, StemRoleId("instrument.bass"), label="Bass"),
        StemRoute(None, StemRoleId("instrument.drums"), label="Drums"),
        StemRoute(None, StemRoleId("residual.other"), label="Other"),
    )


_CLI_CONCEPTS = {
    "vocals": "vocal.vocals",
    "instrumental": "mix.instrumental",
    "bass": "instrument.bass",
    "drums": "instrument.drums",
    "other": "residual.other",
}


def apply_stem_selection(settings: Settings, selection: str) -> str:
    tokens = {
        _STEM_ALIASES.get(part.strip().casefold(), "")
        for part in str(selection).replace(";", ",").split(",")
        if part.strip()
    }
    if "" in tokens or not tokens:
        raise ValueError(f"invalid stem selection {selection!r}")
    state = StemSelectionState()
    if "both" in tokens or tokens >= {"vocals", "instrumental"}:
        state.write_cli_positional(settings, "both")
        return "both"
    if len(tokens) != 1:
        raise ValueError(f"ambiguous stem selection {selection!r}")
    choice = next(iter(tokens))
    if choice in {"primary", "secondary"}:
        state.write_cli_positional(settings, choice)
        return choice
    state.write_cli_concept(settings, _CLI_CONCEPTS[choice])
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


def _debug_stem_focus_persist(
    mode: str,
    view: ExclusiveView | SubsetView | DemucsView,
    *,
    focus: str,
    detail: str = "",
) -> None:
    """Opt-in trace when Save Stems writes ``process.stem_focus`` (``uvr-settings``)."""
    try:
        from core.debug_log import debug

        if isinstance(view, ExclusiveView):
            choice = view.choice
        elif isinstance(view, SubsetView):
            choice = view.mode
        else:
            choice = view.active
        suffix = f" {detail}" if detail else ""
        debug(
            "settings",
            f"stem_focus persist mode={mode} choice={choice!r} "
            f"focus={focus!r}{suffix}",
        )
    except Exception:
        pass


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
        self.routes: tuple[StemRoute, ...] = ()

    def configure_hidden(self, *, has_model: bool = False) -> None:
        self.mode = "hidden"
        self.has_model = has_model
        self.routes = ()

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
        self.routes = _exclusive_inventory(
            primary_stem=primary_stem,
            secondary_stem_name=secondary_stem,
            is_karaoke=is_karaoke,
            is_bv=is_bv,
            ensemble_pair=ensemble_pair,
        )

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
        natives = tuple(self.subset_stems)
        self.routes = (
            model_stem_routes(
                _route_model(
                    primary=natives[0] if natives else None,
                    natives=natives,
                )
            )
            if natives
            else ()
        )

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
        natives: list[str] = []
        for entry in focus_stems:
            if entry == ALL_STEMS:
                self.demucs_focus_map[_QUICK_ALL] = ALL_STEMS
            elif entry == _FOCUS_INSTRUMENTAL:
                self.demucs_focus_map[_FOCUS_INSTRUMENTAL] = _FOCUS_INSTRUMENTAL
            elif entry == _FOCUS_VOCALS:
                self.demucs_focus_map[_FOCUS_VOCALS] = _FOCUS_VOCALS
            else:
                natives.append(entry)
        self.routes = (
            model_stem_routes(
                _route_model(
                    demucs_natives=tuple(natives),
                    demucs_stem_count=self.demucs_stem_count,
                )
            )
            if natives
            else ()
        )
        for entry in natives:
            concept = self._concept_for_subset_token(entry)
            route = _route_for_native(self.routes, entry)
            persist = (
                route.native.raw
                if route is not None and route.native is not None
                else entry
            )
            self.demucs_focus_map[concept] = persist

    def demucs_export_routes(self, native: str) -> tuple[StemRoute, ...]:
        return _exclusive_inventory(
            primary_stem=native,
            secondary_stem_name=secondary_stem(native),
            is_karaoke=False,
            is_bv=False,
            ensemble_pair=None,
        )

    def _demucs_persist_native(self, active: str) -> str:
        if active in self.demucs_focus_map:
            return self.demucs_focus_map[active]
        concept = self._concept_for_subset_token(active)
        return self.demucs_focus_map.get(concept, active)

    def export_choice_from_focus(self, native: str, focus: str) -> str:
        inventory = self.demucs_export_routes(native)
        positional = positional_stem_focus(focus)
        if positional == FOCUS_PRIMARY and inventory:
            return inventory[0].concept
        if positional == FOCUS_SECONDARY and len(inventory) > 1:
            return inventory[1].concept
        selection = select_stem_routes(inventory, focus)
        if (
            selection.status is StemSelectionStatus.MATCHED
            and len(selection.routes) == 1
        ):
            return selection.routes[0].concept
        route = _identityless_route_for_persisted_role(inventory, focus)
        if route is not None:
            return route.concept
        return _TOGGLE_ALL

    def _primary_route(self) -> Optional[StemRoute]:
        if not self.routes:
            return None
        if self.exclusive_primary:
            match = _route_for_native(self.routes, self.exclusive_primary)
            if match is not None:
                return match
        return self.routes[0]

    def _secondary_route(self) -> Optional[StemRoute]:
        if self.exclusive_secondary:
            match = _route_for_native(self.routes, self.exclusive_secondary)
            if match is not None:
                return match
        if len(self.routes) < 2:
            return None
        return self.routes[1]

    def _concept_for_flag(self, flag: str) -> str:
        if flag == self.primary_key:
            route = self._primary_route()
            return route.concept if route is not None else _TOGGLE_ALL
        if flag == self.secondary_key:
            route = self._secondary_route()
            return route.concept if route is not None else _TOGGLE_ALL
        return _TOGGLE_ALL

    def _flag_name_for_route(self, route: StemRoute) -> str:
        if self.ensemble_pair is not None:
            flags = exclusive_flags_for_pair(route.concept, self.ensemble_pair)
            if flags == (True, False):
                return self.primary_key
            if flags == (False, True):
                return self.secondary_key
            return _TOGGLE_ALL
        primary = self._primary_route()
        if primary is not None and primary.concept == route.concept:
            return self.primary_key
        secondary = self._secondary_route()
        if secondary is not None and secondary.concept == route.concept:
            return self.secondary_key
        return _TOGGLE_ALL

    def _persist_focus_for_exclusive_route(self, route: StemRoute) -> str:
        """Use a semantic role when known, otherwise preserve a side choice."""
        persisted = _persist_route_focus(route)
        if persisted:
            return persisted
        flag = self._flag_name_for_route(route)
        if flag == self.primary_key:
            return FOCUS_PRIMARY
        if flag == self.secondary_key:
            return FOCUS_SECONDARY
        return ""

    def _concept_for_native(self, stem: str) -> str:
        route = _route_for_native(self.routes, stem)
        if route is not None:
            return route.concept
        count = self.demucs_stem_count if self.mode == "demucs" else self.stem_count
        return _stem_focus_tag(
            stem,
            stem_count=count,
            is_karaoke=self.is_karaoke,
            is_karaoke_curated=self.is_karaoke_curated,
            is_bv=self.is_bv,
        )

    def _concept_for_subset_token(self, token: str) -> str:
        selection = select_stem_routes(self.routes, token)
        if (
            selection.status is StemSelectionStatus.MATCHED
            and selection.routes
        ):
            return selection.routes[0].concept
        return self._concept_for_native(token)

    def _focus_from_inventory(self, requested: str) -> str:
        selection = select_stem_routes(self.routes, requested)
        if (
            selection.status is StemSelectionStatus.MATCHED
            and selection.routes
        ):
            return _persist_route_focus(selection.routes[0])
        return _persist_legacy_value(requested) or requested

    def _subset_concepts(self) -> Set[str]:
        return {self._concept_for_subset_token(stem) for stem in self.subset_stems}

    def _natives_for_subset_concepts(self, concepts: Set[str]) -> list[str]:
        natives: list[str] = []
        seen: set[str] = set()
        for stem in self.subset_stems:
            concept = self._concept_for_subset_token(stem)
            if concept not in concepts or concept in seen:
                continue
            route = _route_for_native(self.routes, stem)
            if route is not None and route.native is None:
                continue
            persist = (
                route.native.raw
                if route is not None and route.native is not None
                else stem
            )
            natives.append(persist)
            seen.add(concept)
        return natives

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
        concepts = {self._concept_for_subset_token(token) for token in selected}
        concept_set = self._subset_concepts()
        if not concepts:
            self.custom_all = highlight_all_when_empty
            self.custom_selected = set()
        elif concepts >= concept_set:
            self.custom_all = True
            self.custom_selected = set()
        else:
            self.custom_all = False
            self.custom_selected = concepts

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
        focus = str(getattr(settings.process, "stem_focus", "") or "")

        concepts = {
            self._concept_for_subset_token(token) for token in selected_set
        }
        if self.vocal_stem_in_subset() and self.selection_matches_vocal_stem(
            selected_set
        ):
            if concept_is(focus, StemBucket.INSTRUMENTAL, stem_count=2):
                return _QUICK_INSTRUMENTAL, concepts
            if concept_is(focus, StemBucket.VOCALS, stem_count=2):
                return _QUICK_VOCALS, concepts
        if not selected_set or selected_set >= stem_set:
            if not focus:
                return _QUICK_ALL, self._subset_concepts()
        return _SUBSET_CUSTOM, concepts

    def demucs_focus_value(self, active: str) -> str:
        return self.demucs_focus_map.get(active, ALL_STEMS)

    def demucs_needs_export_filter(self, active: str) -> bool:
        return active not in (_QUICK_ALL, _FOCUS_INSTRUMENTAL, _FOCUS_VOCALS)

    def read(self, settings: Any) -> ExclusiveView | SubsetView | DemucsView | None:
        if self.mode == "exclusive":
            focus = str(getattr(settings.process, "stem_focus", "") or "")
            positional = positional_stem_focus(focus)
            if positional == FOCUS_PRIMARY:
                route = self._primary_route()
                return ExclusiveView(
                    choice=route.concept if route is not None else _TOGGLE_ALL
                )
            if positional == FOCUS_SECONDARY:
                route = self._secondary_route()
                return ExclusiveView(
                    choice=route.concept if route is not None else _TOGGLE_ALL
                )
            selection = select_stem_routes(self.routes, focus)
            if (
                selection.status is StemSelectionStatus.MATCHED
                and len(selection.routes) == 1
            ):
                return ExclusiveView(choice=selection.routes[0].concept)
            route = _identityless_route_for_persisted_role(self.routes, focus)
            if route is not None:
                return ExclusiveView(choice=route.concept)
            return ExclusiveView(choice=_TOGGLE_ALL)
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
            native_focus = settings.demucs.stems or ALL_STEMS
            stem_focus = str(getattr(settings.process, "stem_focus", "") or "")
            focus_is_vocals = concept_is(
                str(native_focus), StemBucket.VOCALS, stem_count=4
            )
            if native_focus == ALL_STEMS:
                active = _QUICK_ALL
            elif focus_is_vocals and concept_is(
                stem_focus, StemBucket.INSTRUMENTAL, stem_count=2
            ):
                active = _FOCUS_INSTRUMENTAL
            elif focus_is_vocals and (
                concept_is(stem_focus, StemBucket.VOCALS, stem_count=2)
                or positional_stem_focus(stem_focus) == FOCUS_PRIMARY
            ):
                active = _FOCUS_VOCALS
            else:
                active = self._concept_for_subset_token(str(native_focus))
            export_filter = self.demucs_needs_export_filter(active)
            if export_filter:
                native = self._demucs_persist_native(active)
                self.demucs_export_primary = native
                self.demucs_export_secondary = secondary_stem(native)
                export_choice = self.export_choice_from_focus(native, stem_focus)
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
        detail = ""
        if isinstance(view, ExclusiveView):
            detail = self._write_exclusive(settings, view)
        elif isinstance(view, SubsetView):
            self._write_subset(settings, view)
        else:
            self._write_demucs(settings, view)
        _debug_stem_focus_persist(
            self.mode,
            view,
            focus=str(getattr(settings.process, "stem_focus", "") or ""),
            detail=detail,
        )

    def write_cli_concept(self, settings: Settings, concept: str) -> None:
        """Persist a CLI concept pick into ``process.stem_focus``."""
        selection = select_stem_routes(_cli_concept_inventory(), concept)
        if (
            selection.status is not StemSelectionStatus.MATCHED
            or len(selection.routes) != 1
        ):
            raise ValueError(f"invalid stem selection {concept!r}")
        route = selection.routes[0]
        settings.process.stem_focus = _persist_route_focus(route)
        if route.concept in (
            "vocal.vocals",
            "mix.instrumental",
        ):
            settings.demucs.stems = settings.mdx.stems = VOCAL_STEM
            settings.mdx.stems_selected = [VOCAL_STEM]
            return
        settings.demucs.stems = {
            "instrument.bass": BASS_STEM,
            "instrument.drums": DRUM_STEM,
            "residual.other": OTHER_STEM,
        }[route.concept]
        settings.mdx.stems = ALL_STEMS
        settings.mdx.stems_selected = []

    def write_cli_positional(
        self, settings: Settings, choice: str
    ) -> None:
        """Persist a CLI positional pick as a stem_focus sentinel."""
        if choice == "both":
            settings.process.stem_focus = ""
            settings.demucs.stems = settings.mdx.stems = ALL_STEMS
            settings.mdx.stems_selected = []
            return
        settings.process.stem_focus = (
            FOCUS_PRIMARY if choice == "primary" else FOCUS_SECONDARY
        )
        settings.mdx.stems = ALL_STEMS
        settings.mdx.stems_selected = []

    def _write_exclusive(self, settings: Any, view: ExclusiveView) -> str:
        if view.choice == _TOGGLE_ALL:
            settings.process.stem_focus = ""
            return "reason=all-stems"
        selection = select_stem_routes(self.routes, view.choice)
        if (
            selection.status is not StemSelectionStatus.MATCHED
            or len(selection.routes) != 1
        ):
            settings.process.stem_focus = ""
            return (
                f"reason=exclusive-unmatched status={selection.status.value} "
                f"routes={len(selection.routes)}"
            )
        settings.process.stem_focus = self._persist_focus_for_exclusive_route(
            selection.routes[0]
        )
        return "reason=exclusive-matched"

    def _write_subset(self, settings: Any, view: SubsetView) -> None:
        if view.mode != _SUBSET_CUSTOM:
            if view.mode == _QUICK_ALL:
                settings.mdx.stems_selected = []
                settings.mdx.stems = ALL_STEMS
                settings.process.stem_focus = ""
            elif view.mode == _QUICK_INSTRUMENTAL:
                settings.mdx.stems_selected = [VOCAL_STEM]
                settings.mdx.stems = VOCAL_STEM
                settings.process.stem_focus = self._focus_from_inventory(
                    StemBucket.INSTRUMENTAL.value
                )
            elif view.mode == _QUICK_VOCALS:
                settings.mdx.stems_selected = [VOCAL_STEM]
                settings.mdx.stems = VOCAL_STEM
                settings.process.stem_focus = self._focus_from_inventory(
                    StemBucket.VOCALS.value
                )
            return

        concepts = {self._concept_for_subset_token(token) for token in view.selected}
        if view.custom_all or not concepts or concepts >= self._subset_concepts():
            settings.mdx.stems_selected = []
            settings.mdx.stems = ALL_STEMS
            settings.process.stem_focus = ""
        else:
            natives = self._natives_for_subset_concepts(concepts)
            settings.mdx.stems_selected = natives
            settings.mdx.stems = natives[0] if len(natives) == 1 else ALL_STEMS
            if len(natives) == 1:
                route = _route_for_native(self.routes, natives[0])
                settings.process.stem_focus = (
                    _persist_route_focus(route) if route is not None else ""
                )
            else:
                settings.process.stem_focus = ""

    def _write_demucs(self, settings: Any, view: DemucsView) -> None:
        active = view.active
        if active == _QUICK_ALL:
            settings.demucs.stems = ALL_STEMS
            settings.process.stem_focus = ""
            return
        if active == _FOCUS_INSTRUMENTAL:
            settings.demucs.stems = VOCAL_STEM
            settings.process.stem_focus = self._focus_from_inventory(
                StemBucket.INSTRUMENTAL.value
            )
            return
        if active == _FOCUS_VOCALS:
            settings.demucs.stems = VOCAL_STEM
            settings.process.stem_focus = self._focus_from_inventory(
                StemBucket.VOCALS.value
            )
            return

        persist = self._demucs_persist_native(active)
        settings.demucs.stems = persist
        if view.export_filter_visible:
            name = view.export_choice or _TOGGLE_ALL
            inventory = self.demucs_export_routes(persist)
            if name == self.primary_key and inventory:
                name = inventory[0].concept
            elif name == self.secondary_key and len(inventory) > 1:
                name = inventory[1].concept
            if name == _TOGGLE_ALL:
                settings.process.stem_focus = ""
                return
            selection = select_stem_routes(inventory, name)
            if (
                selection.status is not StemSelectionStatus.MATCHED
                or len(selection.routes) != 1
            ):
                settings.process.stem_focus = ""
                return
            settings.process.stem_focus = _persist_route_focus(selection.routes[0])
            return
        route = _route_for_native(self.routes, persist)
        settings.process.stem_focus = _persist_route_focus(route) if route else ""

    def ensure_demucs_export_defaults(
        self, settings: Any, native: Optional[str] = None
    ) -> None:
        """When a native-stem focus first shows the export filter, default to primary."""
        if str(getattr(settings.process, "stem_focus", "") or ""):
            return
        if not native:
            native = str(getattr(settings.demucs, "stems", "") or "")
        if not native or native == ALL_STEMS:
            return
        inventory = self.demucs_export_routes(native)
        if inventory:
            settings.process.stem_focus = _persist_route_focus(inventory[0])

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
