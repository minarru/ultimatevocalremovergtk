"""Stem export: ensemble buffers, vocal-split pairing, deverb, and disk write.

:func:`write_audio` is duck-typed on the separator. :func:`export_source_map`
loops ``run_export_routes`` then ``write_audio``. :func:`finish_export` is the
job-level post-pass: export, then vocal-split chain.
This module must not import the engine attribute mixin at load time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
import soundfile as sf

from bundled.constants import (
    DONE,
    FLAC,
    INFERENCE_STEP_DEVERBING,
    SAVING_STEM,
)
from core.audio_io import save_format
from core.debug_log import log_event
from core.model_stem_manifest import load_bundled_stem_semantics
from core.stem_roles import StemRoleId
from core.stems import (
    StemBucket,
    StemLiteral,
    StemRoute,
    StemRouteKind,
    route_matches_stem,
    run_export_routes,
    stem_concept,
)
from ml import spec_utils

from .vr_utils import vr_denoiser

_VOCAL_SPLIT_PAIR_ROLES = frozenset(("vocal.lead", "vocal.backing"))


def vocal_split_pair_routes(routes: tuple[StemRoute, ...]) -> tuple[StemRoute, ...]:
    """Keep only the exact reviewed lead/backing routes for splitter output."""
    return tuple(
        route
        for route in routes
        if isinstance(route.role, StemRoleId) and route.role.value in _VOCAL_SPLIT_PAIR_ROLES
    )


def vocal_split_export_routes(sep: Any) -> tuple[StemRoute, ...]:
    """Executable routes scheduled after applying the reviewed pair recipe."""
    routes = run_export_routes(sep)
    if not bool(getattr(sep, "is_vocal_split_model", False)):
        return routes
    routes = vocal_split_pair_routes(routes)
    if bool(getattr(sep, "is_bv_model_rebalenced", False)):
        return tuple(
            route
            for route in routes
            if isinstance(route.role, StemRoleId) and route.role.value == "vocal.backing"
        )
    return routes


def _reviewed_output_route(role_value: str) -> StemRoute | None:
    role = StemRoleId(role_value)
    definition = load_bundled_stem_semantics().roles.get(role)
    if definition is None:
        return None
    return StemRoute(
        native=None,
        role=role,
        label=definition.display,
        filename_tag=definition.filename_tag,
        kind=StemRouteKind.DERIVED,
    )


def _save_audio_file(
    sep: Any,
    path: str,
    source: Any,
    *,
    samplerate: int,
    buffer_stem_name: str | None,
    is_not_ensemble: bool,
) -> None:
    # Ensemble scratch / long-file chunking: keep arrays in memory and
    # skip disk when the caller asked to capture stems only, or when
    # this is an ensemble member that should not keep every output.
    capture_only = bool(getattr(sep, "capture_stems_only", False))
    ensemble_buffer = (
        sep.is_ensemble_mode
        and not sep.is_vocal_split_model
        and not getattr(sep, "is_save_all_outputs_ensemble", False)
    )
    if buffer_stem_name and (capture_only or sep.is_ensemble_mode):
        paths = getattr(sep, "_ensemble_stem_paths", None)
        if paths is None:
            paths = {}
            sep._ensemble_stem_paths = paths
        paths[buffer_stem_name] = path
    if capture_only or ensemble_buffer:
        if buffer_stem_name:
            # Route callers pass the stable filename tag. Legacy/non-route
            # sidecars pass their own already-presented capture name.
            buffer_key = buffer_stem_name
            buffers = getattr(sep, "_ensemble_stem_buffers", None)
            if buffers is None:
                buffers = {}
                sep._ensemble_stem_buffers = buffers
            # Long-file chunking stores raw chunks (normalize after
            # concat / ensemble). Classic ensemble members keep the
            # historical pre-combine normalize.
            if capture_only:
                buffers[buffer_key] = np.asarray(source)
            else:
                buffers[buffer_key] = np.asarray(
                    spec_utils.normalize(
                        source,
                        sep.is_normalization,
                        min_peak=sep.amplification_threshold,
                    )
                )
        return

    from core.stem_levels import export_format_can_clip, scale_to_peak_limit

    if sep.is_prevent_export_clipping and export_format_can_clip(sep.save_format, sep.wav_type_set):
        source, _gain = scale_to_peak_limit(source)

    source = spec_utils.normalize(
        source,
        sep.is_normalization,
        min_peak=sep.amplification_threshold,
    )

    if is_not_ensemble and sep.save_format == FLAC:
        from core.audio_io import flac_subtype, replace_audio_suffix

        flac_path = replace_audio_suffix(path, ".flac")
        sf.write(
            flac_path,
            source,
            samplerate,
            format="FLAC",
            subtype=flac_subtype(sep.flac_bit_set),
        )
        return

    sf.write(path, source, samplerate, subtype=sep.wav_type_set)

    if is_not_ensemble:
        save_format(path, sep.save_format, sep.mp3_bit_set, sep.flac_bit_set)


def _deverb_vocals(
    sep: Any,
    stem_path: str,
    stem_source: Any,
    *,
    samplerate: int,
    buffer_stem_name: str | None,
    is_not_ensemble: bool,
) -> None:
    sep.write_to_console(INFERENCE_STEP_DEVERBING, base_text="")
    stem_source_deverbed, stem_source_2 = vr_denoiser(
        stem_source,
        sep.device,
        is_deverber=True,
        model_path=sep.DEVERBER_MODEL,
        settings=sep.settings,
        on_batch=sep.deverb_progress_callback(),
        check_run_control=sep.check_run_control,
    )
    _save_audio_file(
        sep,
        stem_path.replace(".wav", "_deverbed.wav"),
        stem_source_deverbed,
        samplerate=samplerate,
        buffer_stem_name=buffer_stem_name,
        is_not_ensemble=is_not_ensemble,
    )
    _save_audio_file(
        sep,
        stem_path.replace(".wav", "_reverb_only.wav"),
        stem_source_2,
        samplerate=samplerate,
        buffer_stem_name=buffer_stem_name,
        is_not_ensemble=is_not_ensemble,
    )


def _save_with_message(
    sep: Any,
    stem_path: str,
    stem_name: str | None,
    stem_source: Any,
    *,
    samplerate: int,
    buffer_stem_name: str | None,
    is_not_ensemble: bool,
) -> None:
    saved_bucket = stem_concept(sep, stem_name)
    is_deverb = sep.is_deverb_vocals and (
        sep.deverb_vocal_opt == stem_name
        or (
            sep.deverb_vocal_opt == "ALL"
            and saved_bucket
            in (
                StemBucket.VOCALS,
                StemBucket.LEAD_VOCALS,
                StemBucket.BACKING_VOCALS,
            )
        )
    )

    sep.write_to_console(f"{SAVING_STEM[0]}{stem_name}{SAVING_STEM[1]}")

    if is_deverb and is_not_ensemble:
        _deverb_vocals(
            sep,
            stem_path,
            stem_source,
            samplerate=samplerate,
            buffer_stem_name=buffer_stem_name,
            is_not_ensemble=is_not_ensemble,
        )

    _save_audio_file(
        sep,
        stem_path,
        stem_source,
        samplerate=samplerate,
        buffer_stem_name=buffer_stem_name,
        is_not_ensemble=is_not_ensemble,
    )
    sep.write_to_console(DONE, base_text="")


def _save_voc_split_instrumental(
    sep: Any,
    stem_source: Any,
    *,
    samplerate: int,
    is_not_ensemble: bool,
    is_inst_invert: bool = False,
    is_lead: bool,
) -> None:
    output_route = _reviewed_output_route(
        "mix.instrumental_with_lead_vocals" if is_lead else "mix.instrumental_with_backing_vocals"
    )
    if output_route is None:
        return
    inst_stem_path = sep.audio_file_base_voc_split(output_route.label)
    stem_source = -stem_source if is_inst_invert else stem_source
    inst_stem_source = spec_utils.combine_arrarys(
        [sep.master_inst_source, stem_source], is_swap=True
    )
    _save_with_message(
        sep,
        inst_stem_path,
        output_route.label,
        inst_stem_source,
        samplerate=samplerate,
        buffer_stem_name=output_route.filename_tag,
        is_not_ensemble=is_not_ensemble,
    )


def _save_voc_split_vocal(
    sep: Any,
    stem_source: Any,
    *,
    samplerate: int,
    is_not_ensemble: bool,
    output_route: StemRoute,
) -> None:
    voc_split_stem_path = sep.audio_file_base_voc_split(output_route.label)
    _save_with_message(
        sep,
        voc_split_stem_path,
        output_route.label,
        stem_source,
        samplerate=samplerate,
        buffer_stem_name=output_route.filename_tag,
        is_not_ensemble=is_not_ensemble,
    )


def write_audio(
    sep: Any,
    stem_path: str,
    stem_source: Any,
    samplerate: int,
    stem_name: str | None = None,
    *,
    route: StemRoute | None = None,
) -> None:
    role_value = (
        route.role.value if route is not None and isinstance(route.role, StemRoleId) else ""
    )
    reviewed_buckets = {
        "vocal.vocals": StemBucket.VOCALS,
        "vocal.lead": StemBucket.LEAD_VOCALS,
        "vocal.backing": StemBucket.BACKING_VOCALS,
        "mix.instrumental": StemBucket.INSTRUMENTAL,
        "mix.instrumental_with_backing_vocals": StemBucket.INST_WITH_BV,
        "mix.instrumental_with_lead_vocals": StemBucket.INST_WITH_LEAD,
    }
    bucket = reviewed_buckets.get(role_value, StemBucket.UNKNOWN)
    if route is None:
        bucket = stem_concept(sep, stem_name)
    elif isinstance(route.role, StemLiteral):
        # Raw routes stay raw for identity/ensemble purposes, but legacy
        # operational controls (vocal-chain handoff, deverb/save-only flags)
        # still need the backend-native side. This does not mutate/promote the
        # route role and is never used for source lookup or grouping.
        bucket = stem_concept(
            sep,
            route.native.raw if route.native is not None else route.label,
        )
    display_name = route.label if route is not None else stem_name
    buffer_tag = route.filename_tag if route is not None else stem_name
    if sep.is_vocal_split_model:
        if bucket is StemBucket.UNKNOWN:
            return

    is_lead = bucket is StemBucket.LEAD_VOCALS
    is_backing = bucket is StemBucket.BACKING_VOCALS
    is_vocal_family = bucket in (
        StemBucket.VOCALS,
        StemBucket.LEAD_VOCALS,
        StemBucket.BACKING_VOCALS,
    )
    is_inst_family = bucket in (
        StemBucket.INSTRUMENTAL,
        StemBucket.INST_WITH_BV,
        StemBucket.INST_WITH_LEAD,
    )
    is_bv_model_lead = sep.is_bv_model_rebalenced and sep.is_vocal_split_model and is_lead
    is_bv_rebalance_lead = sep.is_bv_model_rebalenced and sep.is_vocal_split_model and is_backing
    is_no_vocal_save = (sep.is_inst_only_voc_splitter and is_vocal_family) or is_bv_model_lead
    is_not_ensemble = not sep.is_ensemble_mode or sep.is_vocal_split_model
    is_do_not_save_inst = sep.is_save_vocal_only and sep.is_sec_bv_rebalance and is_inst_family
    vocal_output_route = None
    if sep.is_vocal_split_model and is_vocal_family:
        vocal_output_route = (
            route
            if route is not None
            and isinstance(route.role, StemRoleId)
            and route.role.value in _VOCAL_SPLIT_PAIR_ROLES
            else _reviewed_output_route("vocal.lead" if is_lead else "vocal.backing")
        )

    # Bound unconditionally: every read below sits behind the same
    # ``is_bv_rebalance_lead`` guard that assigns it.
    bv_rebalance_lead_source = None
    if is_bv_rebalance_lead:
        master_voc_source = spec_utils.match_array_shapes(
            sep.master_vocal_source, stem_source, is_swap=True
        )
        bv_rebalance_lead_source = stem_source - master_voc_source

    if not is_bv_model_lead and not is_do_not_save_inst:
        if sep.is_vocal_split_model or not sep.is_secondary_model:
            if sep.is_vocal_split_model and not sep.is_inst_only_voc_splitter:
                if vocal_output_route is not None:
                    _save_voc_split_vocal(
                        sep,
                        stem_source,
                        samplerate=samplerate,
                        is_not_ensemble=is_not_ensemble,
                        output_route=vocal_output_route,
                    )
                if is_bv_rebalance_lead:
                    lead_route = _reviewed_output_route("vocal.lead")
                    if lead_route is not None:
                        _save_voc_split_vocal(
                            sep,
                            bv_rebalance_lead_source,
                            samplerate=samplerate,
                            is_not_ensemble=is_not_ensemble,
                            output_route=lead_route,
                        )
            else:
                if not is_no_vocal_save:
                    _save_with_message(
                        sep,
                        stem_path,
                        display_name,
                        stem_source,
                        samplerate=samplerate,
                        buffer_stem_name=buffer_tag,
                        is_not_ensemble=is_not_ensemble,
                    )

            if sep.is_save_inst_vocal_splitter and not sep.is_save_vocal_only:
                _save_voc_split_instrumental(
                    sep,
                    stem_source,
                    samplerate=samplerate,
                    is_not_ensemble=is_not_ensemble,
                    is_lead=is_lead,
                )
                if is_bv_rebalance_lead:
                    _save_voc_split_instrumental(
                        sep,
                        bv_rebalance_lead_source,
                        samplerate=samplerate,
                        is_not_ensemble=is_not_ensemble,
                        is_inst_invert=True,
                        is_lead=True,
                    )

            sep._report_save_progress()

    # Yaml instruments are often ``vocals``, not canonical ``Vocals``.
    if display_name and bucket is StemBucket.VOCALS:
        sep.master_vocal_path = stem_path


def _exact_source_key(sources: Mapping[str, Any], value: str) -> str | None:
    """Exact/case-tolerant source key resolution without semantic aliases."""
    if value in sources:
        return value
    wanted = value.casefold()
    for key in sources:
        if str(key).casefold() == wanted:
            return str(key)
    return None


def export_source_map(
    sep: Any,
    sources: Mapping[str, Any],
    samplerate: int,
    *,
    extra_sources: Mapping[str, Any] | None = None,
) -> None:
    """Write each ``run_export_routes`` stem from an in-memory map.

    Recipe stays with the caller: exact backend keys are authoritative, while
    derived routes may resolve one semantically equivalent source key. Missing
    individual routes are skipped, but a non-empty export that schedules no
    writes raises instead of reporting false success. ``write_audio`` remains
    the only disk/buffer path.
    """
    extra_sources = extra_sources or {}
    routes = vocal_split_export_routes(sep)
    if not routes and not extra_sources:
        return
    log_event(
        "audio",
        "export_started",
        route_count=len(routes),
        source_count=len(sources),
        extra_source_count=len(extra_sources),
    )
    sep.begin_save_phase(len(routes) + len(extra_sources))
    write_calls = 0
    for route in routes:
        if route.native is not None:
            key = _exact_source_key(sources, route.native.raw)
        else:
            key = _exact_source_key(sources, route.concept)
        if (
            key is None
            and route.native is None
            and isinstance(route.role, StemLiteral)
            and route.role.tag.startswith("legacy:")
        ):
            key = _exact_source_key(sources, route.label)
            if key is None:
                semantic_matches = [
                    source_key
                    for source_key in sources
                    if route_matches_stem(route, source_key, sep)
                ]
                if len(semantic_matches) > 1:
                    log_event(
                        "audio",
                        "export_source_ambiguous",
                        level="error",
                        route=route.concept,
                        matches=semantic_matches,
                    )
                    raise RuntimeError(
                        "Ambiguous export source for "
                        f"{route.concept!r}: matched {semantic_matches!r}"
                    )
                if semantic_matches:
                    key = semantic_matches[0]
        if key is None:
            continue
        stem_name = route.label
        path = sep.stem_export_wav_path(stem_name, route=route)
        log_event(
            "audio",
            "write_scheduled",
            level="trace",
            stem=stem_name,
            output_path=path,
        )
        sep.write_audio(
            path,
            sources[key],
            samplerate,
            stem_name=stem_name,
            route=route,
        )
        write_calls += 1

    for stem_name, stem_source in extra_sources.items():
        if stem_source is None:
            continue
        path = sep.stem_export_wav_path(stem_name)
        log_event(
            "audio",
            "write_scheduled",
            level="trace",
            stem=stem_name,
            output_path=path,
        )
        sep.write_audio(path, stem_source, samplerate, stem_name=stem_name)
        write_calls += 1

    has_export_candidates = bool(routes and sources) or any(
        source is not None for source in extra_sources.values()
    )
    if has_export_candidates and write_calls == 0:
        requested = [{"concept": route.concept, "label": route.label} for route in routes]
        available = list(sources)
        log_event(
            "audio",
            "export_no_writes",
            level="error",
            requested=requested,
            available=available,
        )
        raise RuntimeError(
            "No audio writes were scheduled for a non-empty export: "
            f"requested={requested!r}, available={available!r}"
        )
    log_event("audio", "export_completed", write_count=write_calls)


@dataclass
class ExportPlan:
    """In-memory stem export recipe assembled by ``seperate()``."""

    sources: dict[str, Any] = field(default_factory=dict)
    samplerate: int = 44100
    extra_sources: dict[str, Any] = field(default_factory=dict)
    split_sources: Mapping[str, Any] | None = None
    return_sources: Mapping[str, Any] | None = None


def finish_export(sep: Any, plan: ExportPlan) -> dict[str, Any]:
    """Write ``plan`` then run the vocal-split chain; return the caller payload."""
    export_source_map(
        sep,
        plan.sources,
        plan.samplerate,
        extra_sources=plan.extra_sources,
    )
    if plan.split_sources is None:
        split_payload = plan.sources
    else:
        split_payload = plan.split_sources
    if split_payload:
        sep.process_vocal_split_chain(dict(split_payload))
    payload = plan.return_sources if plan.return_sources is not None else plan.sources
    return dict(payload)


__all__ = [
    "ExportPlan",
    "export_source_map",
    "finish_export",
    "vocal_split_export_routes",
    "vocal_split_pair_routes",
    "write_audio",
]
