"""Pure MDX-C route selection, array resolution and ExportPlan construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np

from bundled.constants import ALL_STEMS, secondary_stem
from core.stem_roles import StemRoleId
from core.stems import StemRoute
from ml import spec_utils

from .mdx_c import (
    _channel_last_for_write,
    _exact_mdx_source_key,
    derive_mdx_complement,
    derive_mdx_multi_complement,
    materialize_mdx_route_sources,
    mdx_combined_secondary_key,
    mdx_export_routing_flags,
    mdx_vocal_split_chain_sources,
)
from .stem_writer import ExportPlan


@dataclass(frozen=True)
class MDXCNativeResult:
    mix: Any
    sources: Any
    samplerate: int
    stem_list: tuple[str, ...]


@dataclass(frozen=True)
class MDXCExportRequest:
    native: MDXCNativeResult
    export_routes: tuple[StemRoute, ...]
    available_routes: tuple[StemRoute, ...]
    selected_stems: tuple[str, ...]
    source_keys: Mapping[str, str]
    mdxnet_stem_select: str | None
    primary_stem: str
    secondary_stem: str
    is_secondary_model: bool
    is_pre_proc_model: bool
    is_ensemble_master: bool
    is_4_stem_ensemble: bool
    is_multi_stem_ensemble: bool
    is_mdx_include_stem_complement: bool
    is_mdx_combine_stems: bool
    is_invert_spec: bool
    exports_primary: bool
    exports_secondary: bool
    # These are numerical array transforms, never I/O or progress callbacks.
    blend: Callable[..., Any]
    match_frequency_pitch: Callable[..., Any]
    primary_source: Any = None
    secondary_source: Any = None
    secondary_source_primary: Any = None
    secondary_source_secondary: Any = None


@dataclass(frozen=True)
class MDXCRouting:
    target_route: StemRoute | None
    target_native_key: str
    dependent_routes: tuple[StemRoute, ...]
    is_reviewed_target_pair: bool
    native_source_map: dict[str, Any]
    reviewed_recipe_routes: tuple[StemRoute, ...]
    is_reviewed_recipe_only: bool
    flags: dict[str, Any]
    is_complement_export: bool

    @property
    def pair_export(self) -> bool:
        return not (
            (self.is_reviewed_recipe_only and not self.is_reviewed_target_pair)
            or self.is_complement_export
            or self.flags["multi_stem_export"]
        )


@dataclass(frozen=True)
class MDXCExportSources:
    sources: dict[str, Any]
    split_sources: Mapping[str, Any]
    samplerate: int
    return_sources: bool
    primary_source: Any
    secondary_source: Any


def prepare_mdx_c_export(request: MDXCExportRequest) -> MDXCRouting:
    sources = request.native.sources
    stem_list = request.native.stem_list
    export_routes = request.export_routes
    available_routes = request.available_routes
    target_native_routes = tuple(route for route in available_routes if route.native is not None)
    target_route = target_native_routes[0] if len(target_native_routes) == 1 else None
    target_native_key = (
        target_route.native.raw
        if target_route is not None and target_route.native is not None
        else ""
    )
    dependent_routes = tuple(
        route
        for route in available_routes
        if route.native is None
        and target_route is not None
        and route.complement_of == target_route.role
    )
    is_reviewed_target_pair = bool(target_native_key and dependent_routes)
    native_source_map: dict[str, Any]
    if isinstance(sources, dict):
        native_source_map = sources
    elif target_route is not None and target_route.native is not None:
        native_source_map = {target_route.native.raw: sources}
    else:
        native_source_map = {}
    reviewed_recipe_routes = tuple(
        route
        for route in export_routes
        if route.native is None
        and isinstance(route.role, StemRoleId)
        and (route.complement_of is not None or route.derived_from)
    )
    is_reviewed_recipe_only = bool(reviewed_recipe_routes) and not any(
        route.native is not None for route in export_routes
    )

    routing = mdx_export_routing_flags(
        stem_list=stem_list,
        export_routes=export_routes,
        mdxnet_stem_select=request.mdxnet_stem_select,
        is_secondary_model=request.is_secondary_model,
        is_pre_proc_model=request.is_pre_proc_model,
        is_ensemble_master=request.is_ensemble_master,
        is_4_stem_ensemble=request.is_4_stem_ensemble,
        include_stem_complement=request.is_mdx_include_stem_complement,
    )
    is_complement_export = routing["is_complement_export"]

    return MDXCRouting(
        target_route,
        target_native_key,
        dependent_routes,
        is_reviewed_target_pair,
        native_source_map,
        reviewed_recipe_routes,
        is_reviewed_recipe_only,
        routing,
        is_complement_export,
    )


def select_mdx_c_primary(request: MDXCExportRequest, prepared: MDXCRouting) -> tuple[Any, Any]:
    if not prepared.pair_export:
        return None, None
    sources = request.native.sources
    stem_list = request.native.stem_list
    target_route = prepared.target_route
    target_native_key = prepared.target_native_key
    is_reviewed_target_pair = prepared.is_reviewed_target_pair

    def _export_source_key(stem: str) -> str:
        return request.source_keys.get(stem, stem)

    working_sources: Any = dict(sources) if isinstance(sources, dict) else sources
    if is_reviewed_target_pair and target_route is not None:
        if isinstance(working_sources, dict):
            resolved = _exact_mdx_source_key(working_sources, target_native_key)
            if resolved is None:
                raise KeyError(
                    f"stem {target_native_key!r} not in sources "
                    f"{sorted(map(str, working_sources.keys()))}"
                )
            source_primary = working_sources[resolved]
        else:
            source_primary = working_sources
    elif len(stem_list) == 1:
        source_primary = working_sources
    else:
        select = str(request.mdxnet_stem_select or "")
        primary = str(request.primary_stem or "")
        if request.is_multi_stem_ensemble or len(stem_list) == 2:
            stem_key = str(stem_list[0])
        elif select == ALL_STEMS:
            stem_key = primary
        elif (
            isinstance(working_sources, dict)
            and _exact_mdx_source_key(working_sources, _export_source_key(select)) is not None
        ):
            stem_key = _export_source_key(select)
        else:
            stem_key = _export_source_key(primary)
        if isinstance(working_sources, dict):
            resolved = _exact_mdx_source_key(working_sources, stem_key)
            if resolved is None:
                raise KeyError(
                    f"stem {stem_key!r} not in sources {sorted(map(str, working_sources.keys()))}"
                )
            source_primary = working_sources[resolved]
        else:
            source_primary = working_sources[stem_key]
    return working_sources, source_primary


def resolve_mdx_c_export(
    request: MDXCExportRequest, prepared: MDXCRouting, primary_selection: tuple[Any, Any]
) -> MDXCExportSources:
    sources = request.native.sources
    mix = request.native.mix
    stem_list = request.native.stem_list
    export_routes = request.export_routes
    available_routes = request.available_routes
    target_route = prepared.target_route
    target_native_key = prepared.target_native_key
    dependent_routes = prepared.dependent_routes
    is_reviewed_target_pair = prepared.is_reviewed_target_pair
    native_source_map = prepared.native_source_map
    reviewed_recipe_routes = prepared.reviewed_recipe_routes
    is_reviewed_recipe_only = prepared.is_reviewed_recipe_only
    routing = prepared.flags
    is_complement_export = prepared.is_complement_export
    selected_stems = request.selected_stems

    def _export_source_key(stem: str) -> str:
        return request.source_keys.get(stem, stem)

    export_sources: dict[str, Any] = {}
    primary_source = request.primary_source
    secondary_source = request.secondary_source
    secondary_source_primary = request.secondary_source_primary
    secondary_source_secondary = request.secondary_source_secondary
    if is_reviewed_recipe_only and not is_reviewed_target_pair:
        pass
    elif is_complement_export:
        stem = selected_stems[0]
        complement_stem = secondary_stem(stem)
        source_key = _exact_mdx_source_key(native_source_map, stem)
        if source_key is None:
            raise KeyError(f"stem {stem!r} not in sources {sorted(map(str, native_source_map))}")
        export_sources[stem] = native_source_map[source_key].T
        export_sources[complement_stem] = derive_mdx_complement(
            native_source_map[source_key],
            mix,
            invert_spec=request.is_invert_spec,
            match_frequency_pitch=request.match_frequency_pitch,
        )
    elif routing["multi_stem_export"]:
        export_stems = routing["export_stems"]
        for stem in export_stems:
            source_key = _exact_mdx_source_key(native_source_map, stem)
            if source_key is None:
                raise KeyError(
                    f"stem {stem!r} not in sources {sorted(map(str, native_source_map))}"
                )
            primary_source = native_source_map[source_key].T
            export_sources[stem] = primary_source
    else:
        working_sources, source_primary = primary_selection

        if is_reviewed_target_pair and target_route is not None:
            if target_route in export_routes:
                if not isinstance(primary_source, np.ndarray):
                    primary_source = source_primary.T
                export_sources[target_native_key] = request.blend(
                    primary_source,
                    secondary_source_primary,
                )

            selected_derived = tuple(route for route in export_routes if route in dependent_routes)
            if selected_derived:
                if not isinstance(secondary_source, np.ndarray):
                    materialized_complement = materialize_mdx_route_sources(
                        available_routes=available_routes,
                        export_routes=selected_derived,
                        native_sources=native_source_map,
                        mix=mix,
                        invert_spec=bool(request.is_invert_spec),
                        match_frequency_pitch=request.match_frequency_pitch,
                    )
                    secondary_source = materialized_complement[selected_derived[0].concept]
                derived_audio = request.blend(
                    secondary_source,
                    secondary_source_secondary,
                )
                for route in selected_derived:
                    export_sources[route.concept] = derived_audio
        elif request.exports_secondary:
            if not isinstance(secondary_source, np.ndarray):
                if isinstance(working_sources, dict) and len(stem_list) > 2:
                    secondary_source = derive_mdx_multi_complement(
                        working_sources,
                        _export_source_key(str(request.primary_stem or "")),
                        mix,
                        combine_stems=bool(request.is_mdx_combine_stems),
                        invert_spec=bool(request.is_invert_spec),
                        match_frequency_pitch=request.match_frequency_pitch,
                    )
                elif request.is_mdx_combine_stems and len(stem_list) == 2:
                    if isinstance(working_sources, dict):
                        sec_key = mdx_combined_secondary_key(
                            working_sources, stem_list, request.secondary_stem
                        )
                        secondary_source = working_sources[sec_key]
                    else:
                        secondary_source = working_sources

                    secondary_source = secondary_source.T
                elif isinstance(working_sources, dict) and _exact_mdx_source_key(
                    working_sources, _export_source_key(request.secondary_stem)
                ):
                    sec_key = _exact_mdx_source_key(
                        working_sources, _export_source_key(request.secondary_stem)
                    )
                    assert sec_key is not None
                    secondary_source = working_sources[sec_key].T
                else:
                    secondary_source, raw_mix = (
                        source_primary,
                        request.match_frequency_pitch(mix),
                    )
                    secondary_source = spec_utils.to_shape(secondary_source, raw_mix.shape)

                    if request.is_invert_spec:
                        secondary_source = spec_utils.invert_stem(raw_mix, secondary_source)
                    else:
                        secondary_source = -secondary_source.T + raw_mix.T
            export_sources[_export_source_key(request.secondary_stem)] = request.blend(
                secondary_source, secondary_source_secondary
            )

        if not is_reviewed_target_pair and request.exports_primary:
            if not isinstance(primary_source, np.ndarray):
                primary_source = source_primary.T

            export_sources[_export_source_key(request.primary_stem)] = request.blend(
                primary_source, secondary_source_primary
            )

    routes_to_materialize = tuple(
        route
        for route in reviewed_recipe_routes
        if route.derived_from or route.concept not in export_sources
    )
    materialized_routes = materialize_mdx_route_sources(
        available_routes=available_routes,
        export_routes=routes_to_materialize,
        native_sources=native_source_map,
        mix=mix,
        invert_spec=bool(request.is_invert_spec),
        match_frequency_pitch=request.match_frequency_pitch,
    )
    for route in routes_to_materialize:
        export_sources[route.concept] = materialized_routes[route.concept]

    secondary_sources = mdx_vocal_split_chain_sources(
        export_sources,
        sources,
        routes=export_routes,
    )
    return MDXCExportSources(
        export_sources,
        secondary_sources,
        request.native.samplerate,
        request.is_secondary_model or request.is_pre_proc_model,
        primary_source,
        secondary_source,
    )


def plan_mdx_c_export(resolved: MDXCExportSources) -> ExportPlan:
    """Publish the resolved native/derived maps without touching engine state."""
    plan = ExportPlan(
        sources=resolved.sources,
        samplerate=resolved.samplerate,
        split_sources=resolved.split_sources,
    )
    if resolved.return_sources:
        plan.return_sources = {**resolved.sources, **resolved.split_sources}
    return plan


def vocal_split_pair_sources(sources: dict[str, Any], mix: Any, *,
                             routes: Any = None) -> dict[str, Any]:
    """Resolve native/derived vocal-split arrays without changing the inputs."""
    if routes is not None:
        from engines.stem_writer import vocal_split_pair_routes

        routes = vocal_split_pair_routes(tuple(routes))
        route_sources: dict[str, Any] = {}
        sources_by_role: dict[StemRoleId, Any] = {}
        for route in routes:
            if route.native is None:
                continue
            wanted = route.native.raw.casefold()
            source_key = next(
                (key for key in sources if str(key).casefold() == wanted),
                None,
            )
            if source_key is None:
                continue
            audio = _channel_last_for_write(sources[source_key])
            route_sources[route.native.raw] = audio
            if isinstance(route.role, StemRoleId):
                sources_by_role[route.role] = audio

        mix_arr = np.asarray(mix) if mix is not None else None
        if mix_arr is not None:
            for route in routes:
                if route.native is not None or not isinstance(route.role, StemRoleId):
                    continue
                dependency = route.complement_of
                existing = sources_by_role.get(dependency) if dependency is not None else None
                if existing is None:
                    continue
                derived = _channel_last_for_write(
                    mix_arr - spec_utils.to_shape(np.asarray(existing).T, mix_arr.shape)
                )
                route_sources[route.concept] = derived
                sources_by_role[route.role] = derived
        return route_sources

    return {str(key): _channel_last_for_write(source) for key, source in sources.items()}
