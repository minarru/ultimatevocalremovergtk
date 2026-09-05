"""Pure model, settings and output projections from supplied evidence."""

from __future__ import annotations

import copy
import dataclasses
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .export_naming import OutputNamingContext, format_stem_basename
from .job_plan_types import ModelDescriptor, PlannedInput, PlannedOutput
from .model_identity import ModelRecord
from .model_stem_manifest import load_bundled_stem_semantics
from .settings import Settings
from .stem_pairs import is_stem_mode, normalize_stem_pair_id, stem_pair_definition
from .stem_roles import ModelStemSemantics, StemRoleId
from .stems import (
    FOCUS_PRIMARY,
    FOCUS_SECONDARY,
    StemLiteral,
    StemRoute,
    StemRouteKind,
    StemSelectionStatus,
    derived_stem_route,
    logical_primary_route,
    logical_secondary_route,
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


@dataclass(frozen=True)
class DescriptorEvidence:
    checkpoint: str | None
    checkpoint_hash: str | None
    primary_stem: str | None
    secondary_stem: str | None
    backend_target_stem: str | None
    metadata_source: str
    stem_count: int
    is_karaoke: bool
    is_bv: bool
    stem_semantics: ModelStemSemantics | None
    routes: tuple[StemRoute, ...]
    backend_primary_stem: str | None


@dataclass(frozen=True)
class NativeSettingsProjection:
    settings: Settings
    provenance: Mapping[str, str]


@dataclass(frozen=True)
class OutputRouteProjection:
    routes: tuple[StemRoute, ...]
    focus: str
    positional: str
    reason: str


def project_descriptor(record: ModelRecord, evidence: DescriptorEvidence) -> ModelDescriptor:
    return ModelDescriptor(
        id=record.id,
        family=record.family,
        basename=record.basename,
        display=record.display,
        backend_name=record.backend_name,
        artifacts=record.artifacts,
        demucs=record.demucs,
        mdx=record.mdx,
        checkpoint=evidence.checkpoint,
        checkpoint_hash=evidence.checkpoint_hash,
        primary_stem=evidence.primary_stem,
        secondary_stem=evidence.secondary_stem,
        backend_target_stem=evidence.backend_target_stem,
        metadata_source=evidence.metadata_source,
        stem_count=evidence.stem_count,
        is_karaoke=evidence.is_karaoke,
        is_bv=evidence.is_bv,
        stem_semantics=evidence.stem_semantics,
        routes=evidence.routes,
        backend_primary_stem=evidence.backend_primary_stem,
    )


def project_record_descriptors(records: Sequence[ModelRecord]) -> tuple[ModelDescriptor, ...]:
    return tuple(
        ModelDescriptor(
            record.id,
            record.family,
            record.basename,
            record.display,
            record.backend_name,
            record.artifacts,
            record.demucs,
            record.mdx,
        )
        for record in records
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


def _ensemble_group_key(route: StemRoute, member_id: str) -> tuple[object, ...]:
    """Combine reviewed roles only; raw literals stay scoped to one member."""
    if isinstance(route.role, StemRoleId):
        return ("reviewed", route.role)
    return ("raw", member_id, route.selection_scope, route.role)


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


def _ensemble_output_routes(
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


def select_output_routes(
    settings: Settings,
    descriptors: Sequence[ModelDescriptor],
    *,
    command: str,
) -> OutputRouteProjection:
    """Canonical routes that this resolved job intends to write."""
    focus = str(settings.process.stem_focus or "")
    positional = positional_stem_focus(focus)
    reason = "unknown"
    selected: tuple[StemRoute, ...] = ()

    if command == "ensemble":
        routes, _union = _ensemble_output_routes(settings, descriptors)
        if positional:
            selected = tuple(routes)
            if not is_stem_mode(normalize_stem_pair_id(settings.ensemble.main_stem)):
                if positional == FOCUS_PRIMARY:
                    selected = selected[:1]
                    reason = "ensemble-positional-primary"
                elif positional == FOCUS_SECONDARY:
                    selected = selected[1:2]
                    reason = "ensemble-positional-secondary"
                else:
                    reason = "ensemble-positional"
            else:
                reason = "ensemble-positional-multi"
        else:
            selection = select_ensemble_stem_routes(routes, _union, focus)
            selected = tuple(selection.routes if selection.routes else routes)
            reason = "ensemble-focus-matched" if selection.routes else "ensemble-focus-fallback-all"
        return OutputRouteProjection(selected, focus, positional, reason)

    routes = _fallback_descriptor_routes(descriptors[0]) if descriptors else ()
    if positional:
        if positional == FOCUS_PRIMARY:
            primary = descriptors[0].primary_stem if descriptors else None
            logical = logical_primary_route(routes)
            if logical is not None:
                matched = (logical,)
                reason = "positional-primary-logical-match"
            else:
                matched = tuple(
                    route
                    for route in routes
                    if route.native is not None and route.native.matches(primary or "")
                )
            if matched:
                selected = matched
                if reason == "unknown":
                    reason = "positional-primary-native-match"
            else:
                selected = tuple(route for route in routes if route.selected_by_default) or tuple(
                    routes
                )
                reason = f"positional-primary-fallback-defaults primary_stem={primary!r}"
        else:
            secondary = descriptors[0].secondary_stem if descriptors else None
            logical = logical_secondary_route(routes)
            if logical is not None:
                matched = (logical,)
                reason = "positional-secondary-explicit-logical-match"
            else:
                matched = tuple(
                    route
                    for route in routes
                    if (route.native is not None and route.native.matches(secondary or ""))
                    or (route.native is None and route.label == secondary)
                )
            if matched:
                selected = matched
                if reason == "unknown":
                    reason = "positional-secondary-match"
            else:
                selected = tuple(route for route in routes if route.selected_by_default) or tuple(
                    routes
                )
                reason = f"positional-secondary-fallback-defaults secondary_stem={secondary!r}"
    else:
        selection = select_stem_routes(routes, focus)
        if selection.status is StemSelectionStatus.MATCHED and selection.routes:
            selected = tuple(selection.routes)
            reason = "focus-matched"
        elif focus:
            selected = tuple(route for route in routes if route.selected_by_default) or tuple(
                routes
            )
            reason = "focus-unmatched-fallback-defaults"
        else:
            selected = tuple(
                selection.routes
                if selection.routes
                else tuple(route for route in routes if route.selected_by_default) or tuple(routes)
            )
            reason = "empty-focus-defaults"
        if (
            focus
            and not positional
            and settings.mdx.is_mdx_include_stem_complement
            and any(route.native is not None for route in selected)
        ):
            selected = tuple(
                dict.fromkeys(
                    (
                        *selected,
                        *(route for route in routes if route.native is None and route.conditional),
                    )
                )
            )
            reason = f"{reason}+complement"

    return OutputRouteProjection(selected, focus, positional, reason)


def project_native_settings(
    settings: Settings,
    provenance: Mapping[str, str],
    records: Sequence[ModelRecord],
    models: Sequence[Any],
    metadata_sources: Sequence[str],
) -> NativeSettingsProjection:
    """Resolve automatic MDX compensation; Demucs segment is a setting, not metadata."""
    effective = settings
    sources = dict(provenance)
    for record, model, source in zip(records, models, metadata_sources, strict=False):
        if record.family == "mdx" and effective.mdx.compensate is None:
            value = getattr(model, "compensate", None)
            if value is not None:
                if effective is settings:
                    effective = copy.deepcopy(settings)
                effective.mdx.compensate = float(value)
                sources["mdx.compensate"] = source
    return NativeSettingsProjection(effective, sources)


def project_input(
    path: str, naming: OutputNamingContext, routes: Sequence[StemRoute], *, command: str
) -> PlannedInput:
    outputs = tuple(
        PlannedOutput(
            os.path.join(
                naming.export_directory,
                f"{format_stem_basename(naming.track_base, stem)}.{naming.extension}",
            ),
            stem,
            route.conditional,
            route.concept,
            route.role,
            route.filename_tag,
        )
        for route in routes
        for stem in (route.filename_tag if command == "ensemble" else route.label,)
    )
    return PlannedInput(path, naming, outputs)
