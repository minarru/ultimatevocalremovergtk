"""GTK-free commands and immutable snapshots for Separation's stem dialog.

The configured state adapter owns settings encoding. This controller owns the
current selection and consumes its resolved routes without resolving models.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from bundled.constants import ALL_STEMS
from core.settings import Settings
from core.stem_roles import StemRoleId
from core.stem_selection import (
    _QUICK_ALL,
    _QUICK_INSTRUMENTAL,
    _QUICK_VOCALS,
    _SUBSET_CUSTOM,
    _TOGGLE_ALL,
    DemucsView,
    ExclusiveView,
    StemSelectionState,
    SubsetView,
    _persist_route_focus,
    _route_for_exact_persisted_role,
)
from core.stems import (
    StemRoute,
    StemRouteKind,
    StemSelectionStatus,
    routes_matching_stems,
    select_stem_routes,
)

if TYPE_CHECKING:
    from core.model_config import ModelConfig

SelectionValue = ExclusiveView | SubsetView | DemucsView
ControlMode = Literal[
    'pair', 'native_subset', 'derived', 'demucs_all', 'demucs_focus', 'unavailable'
]


def output_id(route: StemRoute) -> str:
    """Opaque UI identity; labels and filename presentation never identify rows."""
    return json.dumps(
        (
            route.concept,
            route.native.raw if route.native else None,
            route.selection_scope,
            route.kind.value,
        ),
        separators=(',', ':'),
    )


def _valid_native_sidecar(value: object) -> bool:
    # Imported JSON can retain malformed values despite the typed settings model.
    return isinstance(value, list) and all(isinstance(token, str) for token in value)


@dataclass(frozen=True)
class OutputChoice:
    id: str
    route: StemRoute
    selected: bool
    editable: bool
    explanation: str
    enabled: bool = True

    @property
    def checked(self) -> bool:
        return self.selected


@dataclass(frozen=True)
class StemControlsSnapshot:
    mode: ControlMode
    choices: tuple[OutputChoice, ...]
    presets: tuple[tuple[str, str], ...]
    modes: tuple[tuple[str, str], ...]
    focus_choices: tuple[tuple[str, str], ...]
    selected_ids: frozenset[str]
    summary: str
    main_count: int
    additional_output_note: str
    review_required: bool
    revision: int
    model_id: str
    active_mode_id: str
    active_focus_id: str


class StemControls:
    def __init__(self, state: StemSelectionState | None = None, model_id: str = '') -> None:
        self.state = state or StemSelectionState()
        self.model_id = ''
        self.view: SelectionValue | None = None
        self.revision = 0
        self.review_required = False
        self._dirty = False
        self._routes: tuple[StemRoute, ...] = ()
        self._layout = 'hidden'
        self._native_alias_ambiguity = False
        self._native_memory: frozenset[str] | None = None
        self._include_complement = False
        self.configure(model_id, self.state)

    @property
    def value(self) -> SelectionValue | None:
        return self.view

    def configure(
        self, model_id: str, state: StemSelectionState, model: ModelConfig | None = None
    ) -> None:
        """Reconcile an already resolved context; invalidate deferred commands."""
        old = self.snapshot()
        same_context = model_id == self.model_id
        same_layout = self._layout == state.mode
        self.state = state
        self.model_id = model_id
        self._routes = tuple(state.routes)
        self._native_alias_ambiguity = state.mode == 'subset' and any(
            routes_matching_stems(self._routes, [route.native.raw]) != (route,)
            for route in self._routes
            if route.native is not None
        )
        self._layout = state.mode
        if state.mode == 'demucs':
            state.subset_stems = [r.native.raw for r in self._routes if r.native]
        self.revision += 1
        if not same_context:
            self.view = None
            self.review_required = False
            self._native_memory = None
            self._dirty = False
        elif old.selected_ids:
            available = {output_id(r) for r in self._routes}
            if not old.selected_ids <= available:
                self.require_review()
        if self.view is None or not same_layout:
            self.view = self._default_view()

    def _default_view(self) -> SelectionValue | None:
        if self._layout in ('subset', 'demucs'):
            return SubsetView(_QUICK_ALL, set(), True)
        if self._layout == 'exclusive':
            return ExclusiveView(_TOGGLE_ALL)
        return None

    def require_review(self) -> None:
        self.review_required = True
        self._dirty = False

    def _exact_route(self, focus: str, routes: tuple[StemRoute, ...]) -> StemRoute | None:
        if routes == self._routes and focus in ('primary', 'secondary'):
            return (
                self.state._primary_route() if focus == 'primary' else self.state._secondary_route()
            )
        selection = select_stem_routes(routes, focus)
        if selection.status is StemSelectionStatus.MATCHED and len(selection.routes) == 1:
            return selection.routes[0]
        return _route_for_exact_persisted_role(
            routes,
            focus,
            stem_pair_id=self.state.stem_pair_id,
            is_karaoke=self.state.is_karaoke,
            is_bv=self.state.is_bv,
        )

    def refresh_options(self, settings: Settings) -> None:
        """Refresh recipe annotations without replacing an in-progress selection."""
        self._include_complement = settings.mdx.is_mdx_include_stem_complement

    def sync_from_settings(self, settings: Settings) -> None:
        """Read without rewriting imported encodings or dismissing stale review."""
        self._include_complement = settings.mdx.is_mdx_include_stem_complement
        self._dirty = False
        focus = settings.process.stem_focus or ''
        view = (
            self._read_demucs_native(settings)
            if self._layout == 'demucs'
            else self.state.read(settings)
        )
        if self._layout in ('subset', 'exclusive') and focus:
            route = self._exact_route(focus, self._routes)
            if route is None:
                self.require_review()
            elif self._layout == 'subset':
                if route.native is None:
                    if route in self._derived_routes():
                        view = ExclusiveView(route.concept)
                    else:
                        self.require_review()
                else:
                    view = SubsetView(_SUBSET_CUSTOM, {route.concept}, False)
            else:
                view = ExclusiveView(route.concept)
        elif self._layout == 'subset':
            selected = settings.mdx.stems_selected or (
                [settings.mdx.stems] if settings.mdx.stems != ALL_STEMS else []
            )
            if any(
                not any(r.native and r.native.matches(token) for r in self._routes)
                for token in selected
            ):
                self.require_review()
        self.view = view
        if isinstance(view, SubsetView):
            _, inventory = self._inventory()
            if not self._native_selection_supported(self._selected(inventory)):
                self.require_review()
        self._mirror_subset()
        if isinstance(view, SubsetView) and not self.review_required:
            self._native_memory = self.snapshot().selected_ids

    def _read_demucs_native(self, settings: Settings) -> SubsetView:
        """Project legacy focused settings without migrating them on read."""
        natives = tuple(r for r in self._routes if r.native is not None)
        focus = settings.process.stem_focus or ''
        selected = settings.demucs.stems_selected
        if not focus and not _valid_native_sidecar(selected):
            self.require_review()
            return SubsetView(_QUICK_ALL, set(), True)
        if focus:
            # Positional primary refers to the legacy focused native source.
            # Secondary is a remainder, which is not a native subset encoding.
            if focus == 'primary' and settings.demucs.stems != ALL_STEMS:
                route = next(
                    (r for r in natives if r.native and r.native.matches(settings.demucs.stems)),
                    None,
                )
            elif focus == 'secondary':
                route = None
            else:
                selection = select_stem_routes(natives, focus)
                route = (
                    selection.routes[0]
                    if selection.status is StemSelectionStatus.MATCHED
                    and len(selection.routes) == 1
                    else None
                )
            if route is not None and route.native is not None:
                return SubsetView(_SUBSET_CUSTOM, {route.concept}, False)
            self.require_review()
        elif selected:
            exact = {r.native.raw for r in natives if r.native is not None}
            if not set(selected) <= exact:
                self.require_review()
            return SubsetView(
                _SUBSET_CUSTOM,
                {r.concept for r in natives if r.native and r.native.raw in selected},
                False,
            )
        elif settings.demucs.stems != ALL_STEMS:
            # The legacy focused Both selection includes a remainder. Do not
            # silently turn it into the focused native alone or every source.
            self.require_review()
        return SubsetView(_QUICK_ALL, set(), True)

    def _derived_routes(self) -> tuple[StemRoute, ...]:
        return tuple(
            r
            for r in self._routes
            if r.native is None
            and r.kind is StemRouteKind.DERIVED
            and not r.selected_by_default
            and isinstance(r.role, StemRoleId)
            and (r.derived_from or r.complement_of)
        )

    def _inventory(self) -> tuple[ControlMode, tuple[StemRoute, ...]]:
        if not self.state.has_model or not self._routes or self.view is None:
            return 'unavailable', ()
        if self._layout in ('subset', 'demucs'):
            if isinstance(self.view, ExclusiveView):
                return 'derived', tuple(
                    r for r in self._derived_routes() if r.concept == self.view.choice
                )
            return 'native_subset', tuple(r for r in self._routes if r.native is not None)
        return 'pair', self._routes

    def _selected(self, routes: tuple[StemRoute, ...]) -> frozenset[str]:
        if self.review_required:
            return frozenset()
        view = self.view
        if isinstance(view, ExclusiveView):
            selected = tuple(
                r for r in routes if view.choice == _TOGGLE_ALL or r.concept == view.choice
            )
        elif isinstance(view, DemucsView):
            selected = tuple(
                r
                for r in routes
                if view.export_choice == _TOGGLE_ALL or r.concept == view.export_choice
            )
        elif isinstance(view, SubsetView):
            if view.mode == _QUICK_ALL or view.custom_all:
                selected = tuple(r for r in routes if r.selected_by_default)
            elif view.mode in (_QUICK_VOCALS, _QUICK_INSTRUMENTAL):
                role = 'vocal.vocals' if view.mode == _QUICK_VOCALS else 'mix.instrumental'
                selected = tuple(r for r in routes if r.concept == role)
            else:
                selected = tuple(r for r in routes if r.concept in view.selected)
        else:
            selected = ()
        return frozenset(output_id(r) for r in selected)

    def snapshot(self) -> StemControlsSnapshot:
        mode, routes = self._inventory()
        selected = self._selected(routes)
        choices = []
        for route in routes:
            ident = output_id(route)
            checked = ident in selected
            explanation = ''
            if route.kind is StemRouteKind.DERIVED:
                dependencies = [r.label for r in self._routes if r.role in route.derived_from]
                derived = (
                    'Combined from ' + ', '.join(dependencies) + '.'
                    if dependencies
                    else 'Derived output.'
                )
                explanation = ' '.join(filter(None, (derived, explanation)))
            proposed = selected - {ident} if checked else selected | {ident}
            enabled = mode != 'native_subset' or self._native_selection_supported(
                frozenset(proposed)
            )
            if not enabled:
                explanation = 'This selection change is not supported by the current exporter.'
            choices.append(OutputChoice(ident, route, checked, True, explanation, enabled))
        modes: tuple[tuple[str, str], ...] = ()
        presets: tuple[tuple[str, str], ...] = ()
        if self._layout == 'subset' and self._derived_routes():
            modes = (('native_subset', 'Individual stems'),) + tuple(
                (output_id(r), r.label) for r in self._derived_routes()
            )
        if mode == 'native_subset':
            presets = (('all', ALL_STEMS),)
            for role, label in (('vocal.vocals', 'Vocals'), ('mix.instrumental', 'Instrumental')):
                matches = [
                    r for r in routes if isinstance(r.role, StemRoleId) and r.role.value == role
                ]
                if len(matches) == 1:
                    presets += ((output_id(matches[0]), label),)
        summary = ', '.join(c.route.label for c in choices if c.selected)
        if self.review_required:
            summary = 'Outputs changed. Choose the stems to save.'
        elif mode == 'unavailable':
            summary = 'Select a model to choose outputs.'
        note = ''
        if (
            self._layout == 'subset'
            and self._include_complement
            and mode == 'native_subset'
            and len(selected) == 1
        ):
            note = 'Include complement may save an additional output; review Model options.'
        active_mode = output_id(routes[0]) if mode == 'derived' and routes else mode
        active_focus = self.view.active if isinstance(self.view, DemucsView) else ''
        return StemControlsSnapshot(
            mode,
            tuple(choices),
            presets,
            modes,
            (),
            selected,
            summary,
            len(selected),
            note,
            self.review_required,
            self.revision,
            self.model_id,
            active_mode,
            active_focus,
        )

    def _current(self, revision: int | None) -> bool:
        return (revision is None or revision == self.revision) and self.state.has_model

    def _mirror_subset(self) -> None:
        if isinstance(self.view, SubsetView):
            self.state.subset_mode = self.view.mode
            self.state.custom_selected = set(self.view.selected)
            self.state.custom_all = self.view.custom_all

    def adopt_view(self, view: SelectionValue) -> None:
        self.view = view
        self.review_required = False
        self._dirty = True
        self._mirror_subset()
        if isinstance(view, SubsetView):
            self._native_memory = self.snapshot().selected_ids

    def _native_selection_supported(self, selected: frozenset[str]) -> bool:
        if not self._native_alias_ambiguity:
            return True
        routes = tuple(r for r in self._routes if r.native is not None)
        defaults = frozenset(output_id(r) for r in routes if r.selected_by_default)
        if not selected or selected == defaults:
            return True
        chosen = tuple(r for r in routes if output_id(r) in selected)
        if len(chosen) == 1 and _persist_route_focus(chosen[0], self._routes):
            return True
        natives = [r.native.raw for r in routes if r.native and output_id(r) in selected]
        resolved = routes_matching_stems(self._routes, natives)
        return frozenset(output_id(r) for r in resolved) == selected

    def _set_selection(self, selected: frozenset[str]) -> bool:
        mode, routes = self._inventory()
        chosen = tuple(r for r in routes if output_id(r) in selected)
        if not chosen:
            return False
        if mode == 'native_subset':
            if not self._native_selection_supported(selected):
                return False
            defaults = frozenset(output_id(r) for r in routes if r.selected_by_default)
            self.adopt_view(
                SubsetView(
                    _QUICK_ALL if selected == defaults else _SUBSET_CUSTOM,
                    {r.concept for r in chosen},
                    selected == defaults,
                )
            )
        elif mode in ('pair', 'derived'):
            self.adopt_view(
                ExclusiveView(
                    _TOGGLE_ALL
                    if mode == 'pair' and len(chosen) == len(routes)
                    else chosen[0].concept
                )
            )
        else:
            return False
        return True

    def toggle_output(self, output_id: str, active: bool, *, revision: int | None = None) -> bool:
        if not self._current(revision):
            return False
        snapshot = self.snapshot()
        choice = next((c for c in snapshot.choices if c.id == output_id), None)
        if choice is None or not choice.editable or choice.selected == active:
            return False
        selected = set(snapshot.selected_ids)
        if active:
            selected.add(output_id)
        else:
            selected.discard(output_id)
        return self._set_selection(frozenset(selected))

    def select_all(self, *, revision: int | None = None) -> bool:
        if not self._current(revision):
            return False
        mode, routes = self._inventory()
        if mode == 'unavailable':
            return False
        selected = frozenset(
            output_id(r) for r in routes if mode != 'native_subset' or r.selected_by_default
        )
        return self._set_selection(selected)

    def choose_preset(self, preset_id: str, *, revision: int | None = None) -> bool:
        if not self._current(revision) or preset_id not in dict(self.snapshot().presets):
            return False
        if preset_id == 'all':
            return self.select_all(revision=revision)
        return self._set_selection(frozenset((preset_id,)))

    def choose_mode(self, mode_id: str, *, revision: int | None = None) -> bool:
        if not self._current(revision) or mode_id not in dict(self.snapshot().modes):
            return False
        if mode_id == 'native_subset':
            native_routes = tuple(r for r in self._routes if r.native is not None)
            available = frozenset(output_id(r) for r in native_routes)
            defaults = frozenset(output_id(r) for r in native_routes if r.selected_by_default)
            remembered = self._native_memory
            selected = remembered if remembered and remembered <= available else defaults
            if not selected or not self._native_selection_supported(selected):
                return False
            self.adopt_view(
                SubsetView(
                    _QUICK_ALL if selected == defaults else _SUBSET_CUSTOM,
                    {r.concept for r in native_routes if output_id(r) in selected},
                    selected == defaults,
                )
            )
            return True
        if isinstance(self.view, SubsetView):
            self._native_memory = self.snapshot().selected_ids
        route = next(r for r in self._derived_routes() if output_id(r) == mode_id)
        self.adopt_view(ExclusiveView(route.concept))
        return True

    def choose_focus(self, focus_id: str, *, revision: int | None = None) -> bool:
        """Legacy focus controls have no native-subset action."""
        return False

    def persist_to_settings(self, settings: Settings) -> None:
        if (
            not self._dirty
            or self.review_required
            or self.view is None
            or not self.snapshot().main_count
        ):
            return
        if self._layout == 'subset' and isinstance(self.view, ExclusiveView):
            # Existing exact-focus mode has no native subset sidecar. Clearing
            # through the adapter keeps stale native choices out of the writer.
            self.state.write(settings, SubsetView(_QUICK_ALL, set(), True))
        self.state.write(settings, self.view)
        self._dirty = False
