"""Compatibility attributes backed by live context and per-pass state.

Writes to ordinary engine options shadow them for the current pass (for example
secondary stem selection). MDX OOM segment settings deliberately update the
run-local ModelConfig owner, so rebuilt separators observe the same override.
"""

from __future__ import annotations

from typing import Any, Callable, Generic, TypeVar, overload

from .runtime import EngineRunContext, EngineState

T = TypeVar("T")


class RunValue(Generic[T]):
    def __init__(
        self,
        read: Callable[[EngineLegacyOptions], T],
        *,
        write: Callable[[Any, T], None] | None = None,
    ):
        self.read = read
        self.write = write
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, instance: None, owner: type | None = None) -> RunValue[T]: ...
    @overload
    def __get__(self, instance: Any, owner: type | None = None) -> T: ...
    def __get__(self, instance: Any, owner: type | None = None) -> T | RunValue[T]:
        if instance is None:
            return self
        if self.name in instance.__dict__:
            return instance.__dict__[self.name]
        return self.read(instance)

    def __set__(self, instance: Any, value: T) -> None:
        if self.write is not None and "context" in instance.__dict__:
            self.write(instance, value)
        else:
            instance.__dict__[self.name] = value


class EngineLegacyOptions:
    context: EngineRunContext
    state: EngineState
    progress_value = RunValue(
        lambda sep: sep.state.progress_value,
        write=lambda sep, value: setattr(sep.state, "progress_value", value),
    )
    progress_total = RunValue(
        lambda sep: sep.state.progress_total,
        write=lambda sep, value: setattr(sep.state, "progress_total", value),
    )
    _infer_progress = RunValue(
        lambda sep: sep.state._infer_progress,
        write=lambda sep, value: setattr(sep.state, "_infer_progress", value),
    )
    _save_stem_total = RunValue(
        lambda sep: sep.state._save_stem_total,
        write=lambda sep, value: setattr(sep.state, "_save_stem_total", value),
    )
    _save_stem_index = RunValue(
        lambda sep: sep.state._save_stem_index,
        write=lambda sep, value: setattr(sep.state, "_save_stem_index", value),
    )
    set_progress_bar = RunValue(lambda sep: sep.context.process.set_progress_bar)
    write_to_console = RunValue(lambda sep: sep.context.process.write_to_console)
    check_run_control = RunValue(lambda sep: sep.context.process.check_run_control)
    export_path = RunValue(lambda sep: sep.context.process.export_path)
    cached_source_callback = RunValue(lambda sep: sep.context.process.cached_source_callback)
    cached_model_source_holder = RunValue(
        lambda sep: sep.context.process.cached_model_source_holder
    )
    is_4_stem_ensemble = RunValue(lambda sep: sep.context.process.is_4_stem_ensemble)
    list_all_models = RunValue(lambda sep: sep.context.process.list_all_models)
    process_iteration = RunValue(lambda sep: sep.context.process.process_iteration)
    settings = RunValue(lambda sep: sep.context.model.settings)
    is_pitch_change = RunValue(lambda sep: sep.context.common.is_pitch_change)
    semitone_shift = RunValue(lambda sep: sep.context.common.semitone_shift)
    is_match_frequency_pitch = RunValue(lambda sep: sep.context.mdx.is_match_frequency_pitch)
    overlap = RunValue(lambda sep: sep.context.demucs.overlap)
    overlap_mdx = RunValue(lambda sep: sep.context.mdx.overlap_mdx)
    overlap_mdx23 = RunValue(lambda sep: sep.context.mdx.overlap_mdx23)
    is_mdx_combine_stems = RunValue(lambda sep: sep.context.mdx.is_mdx_combine_stems)
    is_mdx_include_stem_complement = RunValue(
        lambda sep: sep.context.mdx.is_mdx_include_stem_complement
    )
    is_mdx_c = RunValue(lambda sep: sep.context.mdx.is_mdx_c)
    mdx_c_configs = RunValue(lambda sep: sep.context.mdx.mdx_c_configs)
    mdxnet_stem_select = RunValue(lambda sep: sep.context.mdx.mdxnet_stem_select)
    mixer_path = RunValue(lambda sep: sep.context.mdx.mixer_path)
    model_samplerate = RunValue(lambda sep: sep.context.vr.model_samplerate)
    model_capacity = RunValue(lambda sep: sep.context.vr.model_capacity)
    is_vr_51_model = RunValue(lambda sep: sep.context.vr.is_vr_51_model)
    is_pre_proc_model = RunValue(lambda sep: sep.context.common.is_pre_proc_model)
    process_method = RunValue(lambda sep: sep.context.identity.process_method)
    model_path = RunValue[Any](lambda sep: sep.context.identity.model_path)
    model_name = RunValue(lambda sep: sep.context.identity.model_name)
    model_basename = RunValue(lambda sep: sep.context.identity.model_basename)
    wav_type_set = RunValue(lambda sep: sep.context.export.wav_type_set)
    mp3_bit_set = RunValue(lambda sep: sep.context.export.mp3_bit_set)
    flac_bit_set = RunValue(lambda sep: sep.context.export.flac_bit_set)
    save_format = RunValue(lambda sep: sep.context.export.save_format)
    is_gpu_conversion = RunValue(lambda sep: sep.context.model.is_gpu_conversion)
    is_normalization = RunValue(lambda sep: sep.context.export.is_normalization)
    is_ensemble_mode = RunValue(lambda sep: sep.context.ensemble.is_ensemble_mode)
    _ensemble_stem_buffers = RunValue(
        lambda sep: sep.state._ensemble_stem_buffers,
        write=lambda sep, value: setattr(sep.state, "_ensemble_stem_buffers", value),
    )
    _ensemble_stem_paths = RunValue(
        lambda sep: sep.state._ensemble_stem_paths,
        write=lambda sep, value: setattr(sep.state, "_ensemble_stem_paths", value),
    )
    secondary_model = RunValue(lambda sep: sep.context.secondary.secondary_model)
    primary_model_primary_stem = RunValue(
        lambda sep: sep.context.routing.primary_model_primary_stem
    )
    primary_stem_native = RunValue(lambda sep: sep.context.routing.primary_stem_native)
    is_invert_spec = RunValue(lambda sep: sep.context.mdx.is_invert_spec)
    is_deverb_vocals = RunValue(lambda sep: sep.context.common.is_deverb_vocals)
    is_mixer_mode = RunValue(lambda sep: sep.context.mdx.is_mixer_mode)
    secondary_model_scale = RunValue(lambda sep: sep.context.secondary.secondary_model_scale)
    is_demucs_pre_proc_model_inst_mix = RunValue(
        lambda sep: sep.context.demucs.is_demucs_pre_proc_model_inst_mix
    )
    primary_source_map = RunValue(
        lambda sep: sep.state.primary_source_map,
        write=lambda sep, value: setattr(sep.state, "primary_source_map", value),
    )
    secondary_source_map = RunValue(
        lambda sep: sep.state.secondary_source_map,
        write=lambda sep, value: setattr(sep.state, "secondary_source_map", value),
    )
    primary_source: Any = RunValue[Any](
        lambda sep: sep.state.primary_source,
        write=lambda sep, value: setattr(sep.state, "primary_source", value),
    )
    secondary_source: Any = RunValue[Any](
        lambda sep: sep.state.secondary_source,
        write=lambda sep, value: setattr(sep.state, "secondary_source", value),
    )
    secondary_source_primary: Any = RunValue[Any](
        lambda sep: sep.state.secondary_source_primary,
        write=lambda sep, value: setattr(sep.state, "secondary_source_primary", value),
    )
    secondary_source_secondary: Any = RunValue[Any](
        lambda sep: sep.state.secondary_source_secondary,
        write=lambda sep, value: setattr(sep.state, "secondary_source_secondary", value),
    )
    ensemble_primary_stem = RunValue(lambda sep: sep.context.ensemble.ensemble_primary_stem)
    is_multi_stem_ensemble = RunValue(lambda sep: sep.context.ensemble.is_multi_stem_ensemble)
    DENOISER_MODEL = RunValue(lambda sep: sep.context.common.DENOISER_MODEL)
    DEVERBER_MODEL = RunValue(lambda sep: sep.context.common.DEVERBER_MODEL)
    vocal_split_model = RunValue(lambda sep: sep.context.secondary.vocal_split_model)
    is_vocal_split_model = RunValue(lambda sep: sep.context.common.is_vocal_split_model)
    is_inst_only_voc_splitter = RunValue(lambda sep: sep.context.common.is_inst_only_voc_splitter)
    is_karaoke = RunValue(lambda sep: sep.context.common.is_karaoke)
    is_bv_model = RunValue(lambda sep: sep.context.common.is_bv_model)
    is_sec_bv_rebalance = RunValue(lambda sep: sep.context.common.is_sec_bv_rebalance)
    deverb_vocal_opt = RunValue(lambda sep: sep.context.common.deverb_vocal_opt)
    is_save_vocal_only = RunValue(lambda sep: sep.context.common.is_save_vocal_only)
    device_set = RunValue(lambda sep: sep.context.device.device_set)
    is_roformer = RunValue(lambda sep: sep.context.mdx.is_roformer)
    roformer_config = RunValue(lambda sep: sep.context.mdx.mdx_c_configs)
    is_mdx_ckpt = RunValue(lambda sep: sep.context.mdx.is_mdx_ckpt)
    is_denoise = RunValue(lambda sep: sep.context.mdx.is_denoise)
    is_denoise_model = RunValue(lambda sep: sep.context.mdx.is_denoise_model)
    is_mdx_c_seg_def = RunValue(
        lambda sep: sep.context.mdx.is_mdx_c_seg_def,
        write=lambda sep, value: setattr(sep.context.mdx, "is_mdx_c_seg_def", value),
    )
    mdx_batch_size = RunValue(lambda sep: sep.context.mdx.mdx_batch_size)
    compensate = RunValue(lambda sep: sep.context.mdx.compensate)
    mdx_segment_size = RunValue(
        lambda sep: sep.context.mdx.mdx_segment_size,
        write=lambda sep, value: setattr(sep.context.mdx, "mdx_segment_size", value),
    )
    mdx_stem_count = RunValue(lambda sep: sep.context.mdx.mdx_stem_count)
    mdx_model_stems = RunValue(lambda sep: sep.context.model.mdx_model_stems)
    chunks = RunValue(lambda sep: sep.context.mdx.chunks)
    margin = RunValue(lambda sep: sep.context.mdx.margin)
    secondary_model_4_stem = RunValue(lambda sep: sep.context.model.secondary_model_4_stem)
    secondary_model_4_stem_scale = RunValue(
        lambda sep: sep.context.model.secondary_model_4_stem_scale
    )
    segment = RunValue(lambda sep: sep.context.demucs.segment)
    demucs_version = RunValue(lambda sep: sep.context.demucs.demucs_version)
    demucs_source_list = RunValue(lambda sep: sep.context.model.demucs_source_list)
    demucs_source_map = RunValue(lambda sep: sep.context.demucs.demucs_source_map)
    is_demucs_combine_stems = RunValue(lambda sep: sep.context.demucs.is_demucs_combine_stems)
    demucs_stem_count = RunValue(lambda sep: sep.context.demucs.demucs_stem_count)
    pre_proc_model = RunValue(lambda sep: sep.context.secondary.pre_proc_model)
    shifts = RunValue(lambda sep: sep.context.demucs.shifts)
    mp = RunValue(lambda sep: sep.context.vr.vr_model_param)
    high_end_process = RunValue(lambda sep: sep.context.vr.is_high_end_process)
    is_tta = RunValue(lambda sep: sep.context.vr.is_tta)
    is_post_process = RunValue(lambda sep: sep.context.vr.is_post_process)
    batch_size = RunValue(lambda sep: sep.context.vr.batch_size)
    window_size = RunValue(lambda sep: sep.context.vr.window_size)
    post_process_threshold = RunValue(lambda sep: sep.context.vr.post_process_threshold)
    opus_bit_set = RunValue(lambda sep: getattr(sep.context.export, "opus_bit_set", "192k"))
    is_match_mix_level = RunValue(
        lambda sep: bool(getattr(sep.context.export, "is_match_mix_level", False))
    )
    is_prevent_export_clipping = RunValue(
        lambda sep: bool(getattr(sep.context.export, "is_prevent_export_clipping", False))
    )
    amplification_threshold = RunValue(
        lambda sep: float(getattr(sep.context.export, "amplification_threshold", 0.0) or 0.0)
    )
    process_data = RunValue(lambda sep: sep.context.process)
    device: Any = RunValue[Any](
        lambda sep: sep.state.device, write=lambda sep, value: setattr(sep.state, "device", value)
    )
    run_type: Any = RunValue[Any](
        lambda sep: sep.state.run_type,
        write=lambda sep, value: setattr(sep.state, "run_type", value),
    )
    _backend_name: Any = RunValue[Any](
        lambda sep: sep.state._backend_name,
        write=lambda sep, value: setattr(sep.state, "_backend_name", value),
    )
    demucs: Any = RunValue[Any](
        lambda sep: sep.state.demucs, write=lambda sep, value: setattr(sep.state, "demucs", value)
    )
    model_run: Any = RunValue[Any](
        lambda sep: sep.state.model_run,
        write=lambda sep, value: setattr(sep.state, "model_run", value),
    )
    _inference_model: Any = RunValue[Any](
        lambda sep: sep.state._inference_model,
        write=lambda sep, value: setattr(sep.state, "_inference_model", value),
    )
    _ort_session: Any = RunValue[Any](
        lambda sep: sep.state._ort_session,
        write=lambda sep, value: setattr(sep.state, "_ort_session", value),
    )
    _weight_cache_key: Any = RunValue[Any](
        lambda sep: sep.state._weight_cache_key,
        write=lambda sep, value: setattr(sep.state, "_weight_cache_key", value),
    )
    primary_model_name: Any = RunValue[Any](
        lambda sep: sep.state.primary_model_name,
        write=lambda sep, value: setattr(sep.state, "primary_model_name", value),
    )
    primary_sources: Any = RunValue[Any](
        lambda sep: sep.state.primary_sources,
        write=lambda sep, value: setattr(sep.state, "primary_sources", value),
    )
    master_inst_source: Any = RunValue[Any](
        lambda sep: sep.state.master_inst_source,
        write=lambda sep, value: setattr(sep.state, "master_inst_source", value),
    )
    master_vocal_source: Any = RunValue[Any](
        lambda sep: sep.state.master_vocal_source,
        write=lambda sep, value: setattr(sep.state, "master_vocal_source", value),
    )
    master_vocal_path: Any = RunValue[Any](
        lambda sep: sep.state.master_vocal_path,
        write=lambda sep, value: setattr(sep.state, "master_vocal_path", value),
    )
    set_master_inst_source: Any = RunValue[Any](
        lambda sep: sep.state.set_master_inst_source,
        write=lambda sep, value: setattr(sep.state, "set_master_inst_source", value),
    )
    audio_file_base_voc_split: Any = RunValue[Any](
        lambda sep: sep.state.audio_file_base_voc_split,
        write=lambda sep, value: setattr(sep.state, "audio_file_base_voc_split", value),
    )
