"""Conditional route and registry observations for pure planning projections.

Legacy helpers may acquire the manifest, log invalid focus, or materialize model
routes. Keep those calls here, in their original conditional order.
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

from .job_plan_types import ModelDescriptor
from .job_projection import OutputRouteEvidence, _ensemble_group_key
from .model_stem_manifest import load_bundled_stem_semantics
from .settings import Settings
from .stem_pairs import is_stem_mode, normalize_stem_pair_id, stem_pair_definition
from .stem_roles import StemRoleId
from .stems import (
    StemLiteral,
    StemRoute,
    StemRouteKind,
    derived_stem_route,
    model_stem_routes,
    positional_stem_focus,
    select_ensemble_stem_routes,
    select_stem_routes,
)

_FOUR_STEM_ROLES = (
    StemRoleId("instrument.bass"),
    StemRoleId("instrument.drums"),
    StemRoleId("residual.other"),
    StemRoleId("vocal.vocals"),
)


def _reviewed_route(role: StemRoleId, *, selected_by_default: bool = True) -> StemRoute:
    """Construct a final ensemble route from registry-owned presentation data."""
    definition = load_bundled_stem_semantics().roles[role]
    return StemRoute(
        native=None,
        role=role,
        label=definition.display,
        filename_tag=definition.filename_tag,
        kind=StemRouteKind.DERIVED,
        selected_by_default=selected_by_default,
    )


def _fallback_descriptor_routes(descriptor: ModelDescriptor) -> tuple[StemRoute, ...]:
    """Route inventory for older callers constructing descriptors directly."""
    if descriptor.routes:
        return descriptor.routes

    class _DescriptorModel:
        primary_stem = descriptor.primary_stem
        secondary_stem = descriptor.secondary_stem
        mdx_model_stems = tuple(
            stem for stem in (descriptor.primary_stem, descriptor.secondary_stem) if stem
        )
        demucs_source_list: tuple[str, ...] = ()
        mdx_stem_count = descriptor.stem_count
        demucs_stem_count = 0
        is_karaoke = descriptor.is_karaoke
        is_bv_model = descriptor.is_bv
        is_vocal_split_model = False

    routes = model_stem_routes(_DescriptorModel())
    if routes:
        return routes
    return (
        derived_stem_route(StemLiteral("Primary"), label="Primary", selected_by_default=True),
        derived_stem_route(StemLiteral("Secondary"), label="Secondary", selected_by_default=True),
    )


def collect_ensemble_routes(
    settings: Settings, descriptors: Sequence[ModelDescriptor]
) -> tuple[tuple[StemRoute, ...], tuple[StemRoute, ...]]:
    """Return viable final routes and the union before contributor filtering."""
    pair_id = normalize_stem_pair_id(settings.ensemble.main_stem)
    pair = stem_pair_definition(pair_id)
    if pair is not None:
        routes = tuple(_reviewed_route(role) for role in pair.roles)
        return routes, routes

    if pair_id == "mode.four_stem":
        standard = tuple(_reviewed_route(role) for role in _FOUR_STEM_ROLES)
        counts = {route.role: 0 for route in standard}
        for _index, descriptor in enumerate(descriptors):
            member_roles = {
                route.role
                for route in _fallback_descriptor_routes(descriptor)
                if route.selected_by_default and isinstance(route.role, StemRoleId)
            }
            for role in counts:
                counts[role] += int(role in member_roles)
        union = tuple(route for route in standard if counts[route.role] >= 1)
        viable = tuple(route for route in standard if counts[route.role] >= 2)
        return viable, union

    contributors: dict[tuple[object, ...], list[StemRoute]] = {}
    contributor_members: dict[tuple[object, ...], set[str]] = {}
    order: list[tuple[object, ...]] = []
    for index, descriptor in enumerate(descriptors):
        member_id = descriptor.id or f"member-{index}"
        seen_member: set[tuple[object, ...]] = set()
        for route in _fallback_descriptor_routes(descriptor):
            key = _ensemble_group_key(route, member_id)
            if key in seen_member or not route.selected_by_default:
                continue
            seen_member.add(key)
            if key not in contributors:
                contributors[key] = []
                contributor_members[key] = set()
                order.append(key)
            contributors[key].append(route)
            contributor_members[key].add(member_id)
    union = tuple(contributors[key][0] for key in order)
    viable = tuple(
        dataclasses.replace(contributors[key][0], selected_by_default=True)
        for key in order
        if len(contributor_members[key]) >= 2
    )
    return viable, union


def collect_output_route_evidence(
    settings: Settings, descriptors: Sequence[ModelDescriptor], *, command: str
) -> OutputRouteEvidence:
    focus = str(settings.process.stem_focus or "")
    positional = positional_stem_focus(focus)
    if command == "ensemble":
        routes, union = collect_ensemble_routes(settings, descriptors)
        if positional:
            multi = is_stem_mode(normalize_stem_pair_id(settings.ensemble.main_stem))
            return OutputRouteEvidence(focus, positional, routes, None, multi)
        selection = select_ensemble_stem_routes(routes, union, focus)
        return OutputRouteEvidence(focus, positional, routes, selection)
    routes = _fallback_descriptor_routes(descriptors[0]) if descriptors else ()
    selection = None if positional else select_stem_routes(routes, focus)
    return OutputRouteEvidence(focus, positional, routes, selection)
