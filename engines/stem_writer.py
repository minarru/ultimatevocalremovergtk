"""Stem export: ensemble buffers, vocal-split pairing, deverb, and disk write.

:func:`write_audio` is duck-typed on the separator. :func:`export_source_map`
is the in-engine post-pass: loop ``run_export_routes`` then ``write_audio``.
This module must not import the engine attribute mixin at load time.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import soundfile as sf

from bundled.constants import (
    BV_VOCAL_STEM_LABEL,
    DONE,
    FLAC,
    INFERENCE_STEP_DEVERBING,
    INST_WITH_BACKING_VOCALS_STEM,
    INST_WITH_LEAD_VOCALS_STEM,
    LEAD_VOCAL_STEM,
    LEAD_VOCAL_STEM_LABEL,
    SAVING_STEM,
)
from core.model_stem_semantics import is_vocal_target
from core.stems import (
    StemBucket,
    StemLiteral,
    export_stem_key,
    filename_tag,
    resolve_in_sources,
    run_export_routes,
    stem_concept,
)
from ml import spec_utils

from .export import save_format
from .vr_utils import vr_denoiser


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
    if capture_only or ensemble_buffer:
        if buffer_stem_name:
            # Ensemble combine keys must match disk export tags
            # (export_stem_key / filename_tag), not raw yaml ids.
            if ensemble_buffer:
                key = export_stem_key(sep, buffer_stem_name, for_ensemble=True)
                buffer_key = (
                    filename_tag(key)
                    if isinstance(key, (StemBucket, StemLiteral))
                    else str(key)
                )
            else:
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
            paths = getattr(sep, "_ensemble_stem_paths", None)
            if paths is None:
                paths = {}
                sep._ensemble_stem_paths = paths
            paths[buffer_key] = path
        return

    from core.stem_levels import export_format_can_clip, scale_to_peak_limit

    if sep.is_prevent_export_clipping and export_format_can_clip(
        sep.save_format, sep.wav_type_set
    ):
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
    stem_name: str | None,
    stem_source: Any,
    *,
    samplerate: int,
    buffer_stem_name: str | None,
    is_not_ensemble: bool,
    is_inst_invert: bool = False,
) -> None:
    local = stem_concept(sep, stem_name)
    inst_stem_name = (
        INST_WITH_LEAD_VOCALS_STEM
        if local is StemBucket.LEAD_VOCALS
        else INST_WITH_BACKING_VOCALS_STEM
    )
    inst_stem_path = sep.audio_file_base_voc_split(inst_stem_name)
    stem_source = -stem_source if is_inst_invert else stem_source
    inst_stem_source = spec_utils.combine_arrarys(
        [sep.master_inst_source, stem_source], is_swap=True
    )
    _save_with_message(
        sep,
        inst_stem_path,
        inst_stem_name,
        inst_stem_source,
        samplerate=samplerate,
        buffer_stem_name=buffer_stem_name,
        is_not_ensemble=is_not_ensemble,
    )


def _save_voc_split_vocal(
    sep: Any,
    stem_name: str | None,
    stem_source: Any,
    *,
    samplerate: int,
    buffer_stem_name: str | None,
    is_not_ensemble: bool,
) -> None:
    local = stem_concept(sep, stem_name)
    voc_split_stem_name = (
        LEAD_VOCAL_STEM_LABEL
        if local is StemBucket.LEAD_VOCALS
        else BV_VOCAL_STEM_LABEL
    )
    voc_split_stem_path = sep.audio_file_base_voc_split(voc_split_stem_name)
    _save_with_message(
        sep,
        voc_split_stem_path,
        voc_split_stem_name,
        stem_source,
        samplerate=samplerate,
        buffer_stem_name=buffer_stem_name,
        is_not_ensemble=is_not_ensemble,
    )


def write_audio(
    sep: Any,
    stem_path: str,
    stem_source: Any,
    samplerate: int,
    stem_name: str | None = None,
) -> None:
    bucket = stem_concept(sep, stem_name)
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
    is_bv_model_lead = (
        sep.is_bv_model_rebalenced and sep.is_vocal_split_model and is_lead
    )
    is_bv_rebalance_lead = (
        sep.is_bv_model_rebalenced and sep.is_vocal_split_model and is_backing
    )
    is_no_vocal_save = (
        sep.is_inst_only_voc_splitter and is_vocal_family
    ) or is_bv_model_lead
    is_not_ensemble = not sep.is_ensemble_mode or sep.is_vocal_split_model
    is_do_not_save_inst = (
        sep.is_save_vocal_only and sep.is_sec_bv_rebalance and is_inst_family
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
                _save_voc_split_vocal(
                    sep,
                    stem_name,
                    stem_source,
                    samplerate=samplerate,
                    buffer_stem_name=stem_name,
                    is_not_ensemble=is_not_ensemble,
                )
                if is_bv_rebalance_lead:
                    _save_voc_split_vocal(
                        sep,
                        LEAD_VOCAL_STEM,
                        bv_rebalance_lead_source,
                        samplerate=samplerate,
                        buffer_stem_name=stem_name,
                        is_not_ensemble=is_not_ensemble,
                    )
            else:
                if not is_no_vocal_save:
                    _save_with_message(
                        sep,
                        stem_path,
                        stem_name,
                        stem_source,
                        samplerate=samplerate,
                        buffer_stem_name=stem_name,
                        is_not_ensemble=is_not_ensemble,
                    )

            if sep.is_save_inst_vocal_splitter and not sep.is_save_vocal_only:
                _save_voc_split_instrumental(
                    sep,
                    stem_name,
                    stem_source,
                    samplerate=samplerate,
                    buffer_stem_name=stem_name,
                    is_not_ensemble=is_not_ensemble,
                )
                if is_bv_rebalance_lead:
                    _save_voc_split_instrumental(
                        sep,
                        LEAD_VOCAL_STEM,
                        bv_rebalance_lead_source,
                        samplerate=samplerate,
                        buffer_stem_name=stem_name,
                        is_not_ensemble=is_not_ensemble,
                        is_inst_invert=True,
                    )

            sep._report_save_progress()

    # Yaml instruments are often ``vocals``, not canonical ``Vocals``.
    if stem_name and is_vocal_target(stem_name):
        sep.master_vocal_path = stem_path


def export_source_map(
    sep: Any,
    sources: Mapping[str, Any],
    samplerate: int,
) -> None:
    """Write each ``run_export_routes`` stem from an in-memory map.

    Recipe stays with the caller: ``sources`` must already hold derived
    complements under the names ``write_audio`` expects. Missing keys are
    skipped so unused stems are not computed here. ``write_audio`` remains
    the only disk/buffer path.
    """
    routes = run_export_routes(sep)
    if not routes:
        return
    sep.begin_save_phase(len(routes))
    for route in routes:
        lookup: Any = route.native if route.native is not None else route.label
        key = resolve_in_sources(sources, lookup)
        if key is None and route.label:
            key = resolve_in_sources(sources, route.label)
        if key is None:
            continue
        stem_name = (
            route.native.raw if route.native is not None else str(route.label)
        )
        path = sep.stem_export_wav_path(stem_name)
        sep.write_audio(path, sources[key], samplerate, stem_name=stem_name)


__all__ = ["write_audio", "export_source_map"]
