"""Pure model, settings and output projections from supplied evidence."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .export_naming import OutputNamingContext, format_stem_basename
from .job_plan_types import ModelDescriptor, PlannedInput, PlannedOutput
from .model_identity import ModelRecord
from .settings import Settings
from .stem_roles import ModelStemSemantics, StemRoleId
from .stems import (
    FOCUS_PRIMARY,
    FOCUS_SECONDARY,
    StemRoute,
    StemSelection,
    StemSelectionStatus,
    logical_primary_route,
    logical_secondary_route,
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
class OutputRouteEvidence:
    focus: str
    positional: str
    routes: tuple[StemRoute, ...]
    selection: StemSelection | None
    ensemble_multi: bool = False


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


def _ensemble_group_key(route: StemRoute, member_id: str) -> tuple[object, ...]:
    """Combine reviewed roles only; raw literals stay scoped to one member."""
    if isinstance(route.role, StemRoleId):
        return ("reviewed", route.role)
    return ("raw", member_id, route.selection_scope, route.role)


def select_output_routes(
    settings: Settings,
    descriptors: Sequence[ModelDescriptor],
    *,
    command: str,
    evidence: OutputRouteEvidence,
) -> OutputRouteProjection:
    """Canonical routes that this resolved job intends to write."""
    focus = evidence.focus
    positional = evidence.positional
    reason = "unknown"
    selected: tuple[StemRoute, ...] = ()

    if command == "ensemble":
        routes = evidence.routes
        if positional:
            selected = tuple(routes)
            if not evidence.ensemble_multi:
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
            selection = evidence.selection
            assert selection is not None
            selected = tuple(selection.routes if selection.routes else routes)
            reason = "ensemble-focus-matched" if selection.routes else "ensemble-focus-fallback-all"
        return OutputRouteProjection(selected, focus, positional, reason)

    routes = evidence.routes
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
        selection = evidence.selection
        assert selection is not None
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
