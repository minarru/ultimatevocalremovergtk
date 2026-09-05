"""Pure Demucs native-source export planning; no inference, cache or writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import numpy as np

from bundled.constants import (
    INST_STEM,
    VOCAL_STEM,
)
from core.stems import StemRoute, StemRouteKind
from ml import spec_utils

from .stem_writer import ExportPlan


@dataclass(frozen=True)
class DemucsNativeResult:
    sources: Any
    mix: Any
    source_map: Mapping[str, int]
    folded_six_stem_other: bool = False
    inst_mix: Any = None


@dataclass(frozen=True)
class DemucsExportRequest:
    native: DemucsNativeResult
    routes: tuple[StemRoute, ...]
    write_all_sources: bool
    blend: Callable[..., Any]
    blended_sources: Mapping[str, Any] = field(default_factory=dict)
    primary_stem: str = ""
    secondary_stem: str = ""
    is_secondary_model: bool = False
    is_pre_proc_model: bool = False
    is_sec_bv_rebalance: bool = False
    is_demucs_combine_stems: bool = False
    is_invert_spec: bool = False
    is_demucs_pre_proc_model_inst_mix: bool = False
    has_pre_proc_model: bool = False
    is_4_stem_ensemble: bool = False
    write_secondary: bool = False
    exports_primary: bool = False
    secondary_matching_routes: tuple[StemRoute, ...] = ()
    secondary_source_primary: Any = None
    secondary_source_secondary: Any = None

    @property
    def demucs_source_map(self) -> Mapping[str, int]:
        return self.native.source_map


def plan_demucs_export(request: DemucsExportRequest) -> ExportPlan:
    """Build ordered channel-last maps using the supplied pure blend kernel."""
    source = request.native.sources
    mix = request.native.mix
    inst_mix = request.native.inst_mix
    is_no_piano_guitar = request.native.folded_six_stem_other
    samplerate = 44100

    def _demucs_map_key(stem: str) -> str | None:
        if stem in request.demucs_source_map:
            return stem
        want = str(stem).casefold()
        for key in request.demucs_source_map:
            if str(key).casefold() == want:
                return str(key)
        return None

    export_routes = request.routes
    native_export = tuple(route for route in export_routes if route.native is not None)
    write_all_sources = request.write_all_sources

    # ---------------------------------------------------------------------
    # Write-all mode: build a full native-keyed, channel-last sources map.
    # ---------------------------------------------------------------------
    if write_all_sources:
        export_sources = dict(request.blended_sources)

        # Derived instrumental complement is required by nested secondary
        # gather/pre-proc callers on 4/6-stem Demucs.
        if request.is_secondary_model or request.is_pre_proc_model:
            if isinstance(source, np.ndarray) and len(source) > 2:
                vocals_idx = request.demucs_source_map[VOCAL_STEM]
                stem_count = source.shape[0]
                if stem_count == 6 and is_no_piano_guitar:
                    max_idx = stem_count - 2
                    indices = [i for i in range(max_idx) if i != vocals_idx]
                else:
                    indices = [i for i in range(stem_count) if i != vocals_idx]
                instrumental = np.zeros_like(source[0])
                for i in indices:
                    instrumental += source[i]
                export_sources[INST_STEM] = instrumental.T

        split_sources: dict[str, Any] = {}
        if not request.is_sec_bv_rebalance and VOCAL_STEM in export_sources:
            split_sources = {VOCAL_STEM: export_sources[VOCAL_STEM]}

        plan = ExportPlan(
            sources=export_sources,
            samplerate=samplerate,
            split_sources=split_sources,
        )
        if request.is_secondary_model or request.is_pre_proc_model:
            plan.return_sources = export_sources
        return plan

    # ---------------------------------------------------------------------
    # Focused/dual mode: build native + derived maps, then export.
    # ---------------------------------------------------------------------
    secondary_source_primary = request.secondary_source_primary
    secondary_source_secondary = request.secondary_source_secondary
    write_secondary = request.write_secondary

    extra_sources: dict[str, Any] = {}
    extra_inst_mix = 0
    if (
        write_secondary
        and request.is_demucs_pre_proc_model_inst_mix
        and request.has_pre_proc_model
        and not request.is_4_stem_ensemble
    ):
        extra_inst_mix = 1

    native_route = next((route for route in export_routes if route.native is not None), None)
    primary_key = (
        native_route.native.raw
        if native_route is not None and native_route.native is not None
        else request.primary_stem
    )
    primary_map_key = (
        _demucs_map_key(primary_key)
        or _demucs_map_key(request.primary_stem)
        or request.primary_stem
    )

    def _derive_secondary_source(
        *,
        raw_mixture: Any,
        is_inst_mixture: bool,
    ) -> Any:
        """Mirror legacy `secondary_save`, but return an array."""
        assert isinstance(source, np.ndarray)
        if request.is_demucs_combine_stems:
            # Combine stems by summing everything except the chosen primary.
            source_list = list(source)
            if is_inst_mixture:
                source_list = [
                    i
                    for n, i in enumerate(source_list)
                    if n
                    not in [
                        request.demucs_source_map[primary_map_key],
                        request.demucs_source_map[VOCAL_STEM],
                    ]
                ]
            else:
                source_list.pop(request.demucs_source_map[primary_map_key])

            if is_no_piano_guitar:
                source_list = source_list[: len(source_list) - 2]

            derived = np.zeros_like(source_list[0])
            for i in source_list:
                derived += i
            return derived.T

        # Subtract/mirror complements from the original mix.
        if not isinstance(raw_mixture, np.ndarray):
            if mix is None:
                raw_mixture = mix
            else:
                raw_mixture = mix
        stem_primary = source[request.demucs_source_map[primary_map_key]]

        if request.is_invert_spec:
            return spec_utils.invert_stem(raw_mixture, stem_primary)

        raw_mixture = spec_utils.reshape_sources(stem_primary, raw_mixture)
        return -stem_primary.T + raw_mixture.T

    dual_export_sources: dict[str, Any] = {}
    primary_source_map: dict[str, Any] = {}
    secondary_source_map: dict[str, Any] = {}

    if write_secondary:
        derived_label = next(
            (route.label for route in export_routes if route.kind is StemRouteKind.DERIVED),
            request.secondary_stem,
        )

        derived = _derive_secondary_source(raw_mixture=mix, is_inst_mixture=False)
        blended = request.blend(derived, secondary_source_secondary)
        secondary_source_map[request.secondary_stem] = blended
        dual_export_sources[derived_label] = blended
        dual_export_sources[request.secondary_stem] = blended

        if extra_inst_mix:
            sidecar_key = f"{request.secondary_stem} {INST_STEM}"
            extra_sources[sidecar_key] = _derive_secondary_source(
                raw_mixture=inst_mix, is_inst_mixture=True
            )

    for route in native_export:
        if write_secondary and route in request.secondary_matching_routes:
            continue
        native_raw = route.native.raw if route.native is not None else request.primary_stem
        map_key = _demucs_map_key(native_raw)
        if map_key is None:
            continue
        primary_source = source[request.demucs_source_map[map_key]].T
        blended = request.blend(primary_source, secondary_source_primary)
        primary_source_map[map_key] = blended
        dual_export_sources[map_key] = blended

    if not native_export and request.exports_primary:
        primary_source = source[request.demucs_source_map[primary_map_key]].T
        blended = request.blend(primary_source, secondary_source_primary)
        primary_source_map[request.primary_stem] = blended
        dual_export_sources[request.primary_stem] = blended

    secondary_sources = {**primary_source_map, **secondary_source_map}

    plan = ExportPlan(
        sources=dual_export_sources,
        samplerate=samplerate,
        extra_sources=extra_sources,
        split_sources=secondary_sources,
    )
    if request.is_secondary_model or request.is_pre_proc_model:
        plan.return_sources = secondary_sources
    return plan
