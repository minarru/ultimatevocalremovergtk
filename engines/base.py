from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

import numpy as np
import torch

from bundled.constants import *
from bundled.error_handling import *
from core.debug_log import debug, trace_phase
from core.export_naming import stem_wav_path
from core.gpu_backend import resolve_inference_backend
from core.progress_ticks import InferenceProgress
from core.run_estimate import save_progress_local_step
from core.stems import StemBucket, StemLiteral, StemRoute, export_stem_key, filename_tag
from ml import spec_utils

from .orchestration import process_chain_model

if TYPE_CHECKING:
    from core.model_config import ModelConfig
    from core.process_data import ProcessData

cpu = torch.device('cpu')


class SeperateAttributes:
    def __init__(
        self,
        model_data: ModelConfig,
        process_data: ProcessData,
        main_model_primary_stem_4_stem: str | None = None,
        main_process_method: str | None = None,
        is_return_dual: bool = True,
        main_model_primary: str | None = None,
        vocal_stem_path: Sequence[Any] | None = None,
        master_inst_source: Any = None,
        master_vocal_source: Any = None,
    ) -> None:

        self.list_all_models: list
        self.process_data = process_data
        self.progress_value = 0
        self.progress_total = 0
        self._infer_progress = InferenceProgress()
        self._save_stem_total = 1
        self._save_stem_index = 0
        self.set_progress_bar = process_data.set_progress_bar
        self.write_to_console = process_data.write_to_console
        self.check_run_control = process_data.check_run_control
        self.audio_file_base_voc_split: Any = None
        if vocal_stem_path:
            self.audio_file, self.audio_file_base = vocal_stem_path

            def _voc_split_path(export_stem: str) -> str:
                base = self.audio_file_base
                for suffix in (
                    f" ({VOCAL_STEM})",
                    f"_({VOCAL_STEM})",
                    f" ({LEAD_VOCAL_STEM_LABEL})",
                    f" ({BV_VOCAL_STEM_LABEL})",
                ):
                    if base.endswith(suffix):
                        base = base[: -len(suffix)]
                        break
                return stem_wav_path(self.export_path, base, export_stem)

            self.audio_file_base_voc_split = _voc_split_path
        else:
            self.audio_file = process_data.audio_file
            self.audio_file_base = process_data.audio_file_base
        self.export_path = process_data.export_path
        self.cached_source_callback = process_data.cached_source_callback
        self.cached_model_source_holder = process_data.cached_model_source_holder
        self.is_4_stem_ensemble = process_data.is_4_stem_ensemble
        self.list_all_models = process_data.list_all_models
        self.process_iteration = process_data.process_iteration
        self.is_return_dual = is_return_dual
        self.settings = model_data.settings
        self.is_pitch_change = model_data.is_pitch_change
        self.semitone_shift = model_data.semitone_shift
        self.is_match_frequency_pitch = model_data.is_match_frequency_pitch
        self.overlap = model_data.overlap
        self.overlap_mdx = model_data.overlap_mdx
        self.overlap_mdx23 = model_data.overlap_mdx23
        self.is_mdx_combine_stems = model_data.is_mdx_combine_stems
        self.is_mdx_include_stem_complement = model_data.is_mdx_include_stem_complement
        self.is_mdx_c = model_data.is_mdx_c
        self.mdx_c_configs: Any = model_data.mdx_c_configs
        self.mdxnet_stem_select = model_data.mdxnet_stem_select
        self.mdxnet_stems_selected = getattr(model_data, "mdxnet_stems_selected", []) or []
        self.available_stem_routes = tuple(getattr(model_data, "available_stem_routes", ()) or ())
        self.selected_stem_routes = tuple(getattr(model_data, "selected_stem_routes", ()) or ())
        selection_provenance = getattr(model_data, "selected_stem_routes_explicit", None)
        self.selected_stem_routes_explicit: bool | None = (
            selection_provenance if isinstance(selection_provenance, bool) else None
        )
        self.mixer_path = model_data.mixer_path
        self.model_samplerate = model_data.model_samplerate
        self.model_capacity = model_data.model_capacity
        self.is_vr_51_model = model_data.is_vr_51_model
        self.is_pre_proc_model = model_data.is_pre_proc_model
        self.is_secondary_model_activated = (
            model_data.is_secondary_model_activated if not self.is_pre_proc_model else False
        )
        self.is_secondary_model = (
            model_data.is_secondary_model if not self.is_pre_proc_model else True
        )
        self.process_method = model_data.process_method
        self.model_path = model_data.model_path
        self.model_name = model_data.model_name
        self.backend_name = (
            getattr(model_data, "backend_name", None)
            or model_data.model_basename
            or model_data.model_name
            or ""
        )
        self.model_cache_key = self.backend_name or model_data.model_basename or ""
        self.model_basename = model_data.model_basename
        self.model_display_label = (
            getattr(model_data, "model_display_label", None)
            or model_data.model_name
            or model_data.model_basename
            or ""
        )
        self.wav_type_set = model_data.wav_type_set
        self.mp3_bit_set = model_data.mp3_bit_set
        self.flac_bit_set = model_data.flac_bit_set
        self.save_format = model_data.save_format
        self.is_gpu_conversion = model_data.is_gpu_conversion
        self.is_normalization = model_data.is_normalization
        self.is_match_mix_level = bool(getattr(model_data, "is_match_mix_level", False))
        self.is_prevent_export_clipping = bool(
            getattr(model_data, "is_prevent_export_clipping", False)
        )
        self.amplification_threshold = float(
            getattr(model_data, "amplification_threshold", 0.0) or 0.0
        )
        self.is_ensemble_mode = model_data.is_ensemble_mode
        self.is_save_all_outputs_ensemble = bool(process_data.is_save_all_outputs_ensemble)
        # Long-file chunking / ensemble scratch: keep stem arrays, skip disk write.
        self.capture_stems_only = bool(process_data.capture_stems_only)
        self._ensemble_stem_buffers = {}
        self._ensemble_stem_paths = {}
        self.secondary_model = model_data.secondary_model  #
        self.primary_model_primary_stem = model_data.primary_model_primary_stem
        self.primary_stem_native = model_data.primary_stem_native
        self.primary_stem: str = str(model_data.primary_stem or "")  #
        self.secondary_stem: str = str(model_data.secondary_stem or "")  #
        self.is_invert_spec = model_data.is_invert_spec  #
        self.is_deverb_vocals = model_data.is_deverb_vocals
        self.is_mixer_mode = model_data.is_mixer_mode  #
        self.secondary_model_scale = model_data.secondary_model_scale  #
        self.is_demucs_pre_proc_model_inst_mix = model_data.is_demucs_pre_proc_model_inst_mix  #
        self.primary_source_map = {}
        self.secondary_source_map = {}
        self.primary_source: Any = None
        self.secondary_source: Any = None
        self.secondary_source_primary: Any = None
        self.secondary_source_secondary: Any = None
        self.main_model_primary_stem_4_stem = main_model_primary_stem_4_stem
        self.main_model_primary = main_model_primary
        self.ensemble_primary_stem = model_data.ensemble_primary_stem
        self.is_multi_stem_ensemble = model_data.is_multi_stem_ensemble
        self.is_other_gpu = False
        self.is_deverb = True
        self.DENOISER_MODEL = model_data.DENOISER_MODEL
        self.DEVERBER_MODEL = model_data.DEVERBER_MODEL
        self.is_source_swap = False
        self.vocal_split_model = model_data.vocal_split_model
        self.is_vocal_split_model = model_data.is_vocal_split_model
        self.master_vocal_path: Any = None
        self.set_master_inst_source: Any = None
        self.master_inst_source: Any = master_inst_source
        self.master_vocal_source: Any = master_vocal_source
        self.is_save_inst_vocal_splitter = (
            isinstance(master_inst_source, np.ndarray) and model_data.is_save_inst_vocal_splitter
        )
        self.is_inst_only_voc_splitter = model_data.is_inst_only_voc_splitter
        self.is_karaoke = model_data.is_karaoke
        self.is_bv_model = model_data.is_bv_model
        self.is_bv_model_rebalenced = model_data.bv_model_rebalance and self.is_vocal_split_model
        self.is_sec_bv_rebalance = model_data.is_sec_bv_rebalance
        self.stem_path_init = self.stem_export_wav_path(self.secondary_stem)
        self.deverb_vocal_opt = model_data.deverb_vocal_opt
        self.is_save_vocal_only = model_data.is_save_vocal_only
        self.device = cpu
        self.run_type = ['CPUExecutionProvider']
        self.device_set = model_data.device_set
        self._backend_name = "cpu"
        backend = resolve_inference_backend(
            use_gpu=bool(self.is_gpu_conversion),
            device_set=self.device_set,
            is_use_directml=model_data.is_use_directml,
            is_macos=is_macos,
        )
        self.device = backend.torch_device
        self.run_type = backend.onnx_providers
        self.is_other_gpu = backend.is_other_gpu
        self._backend_name = backend.backend_name
        debug(
            "settings",
            f"inference backend={backend.backend_name} torch={backend.torch_device!r} "
            f"onnx={backend.onnx_providers}",
        )
        # Roformer (BS-Roformer / Mel-Band Roformer) support. These models are
        # MDX-C-style nets selected via the model's yaml config; ``is_roformer``
        # comes from the model-data JSON and the config itself drives which
        # roformer architecture is built in ``SeperateMDXC.demix``.
        self.is_roformer = model_data.is_roformer
        # ``is_target_instrument`` / ``is_vocal_main_target`` enable the new
        # roformer stem handling (single target_instrument treated as
        # vocals+instrumental). Gate them on ``is_roformer`` so classic
        # (non-roformer) MDX-C models keep their original single-stem behaviour.
        self.is_target_instrument = model_data.is_target_instrument and self.is_roformer
        self.roformer_config: Any = model_data.mdx_c_configs

        if main_model_primary and self.is_multi_stem_ensemble:
            self.primary_stem, self.secondary_stem = (
                main_model_primary,
                secondary_stem(main_model_primary),
            )

        if model_data.process_method == MDX_ARCH_TYPE:
            self.is_mdx_ckpt = model_data.is_mdx_ckpt
            self.primary_model_name, self.primary_sources = self.cached_source_callback(
                MDX_ARCH_TYPE, model_name=self.model_cache_key
            )
            self.is_denoise = model_data.is_denoise  #
            self.is_denoise_model = model_data.is_denoise_model  #
            self.is_mdx_c_seg_def = model_data.is_mdx_c_seg_def  #
            self.mdx_batch_size = model_data.mdx_batch_size
            self.compensate = model_data.compensate
            self.mdx_segment_size = model_data.mdx_segment_size
            # Needed by export_stem_key: without a stem count, a 4-stem
            # model's MUSDB ``other`` residual is read as the 2-stem
            # instrumental complement and exported as ``Instrumental``.
            self.mdx_stem_count = model_data.mdx_stem_count
            self.mdx_model_stems = model_data.mdx_model_stems

            if self.is_mdx_c:
                if not self.is_4_stem_ensemble:
                    if not self.is_target_instrument:
                        self.primary_stem = str(
                            (
                                model_data.ensemble_primary_stem
                                if process_data.is_ensemble_master
                                else model_data.primary_stem
                            )
                            or ""
                        )
                        self.secondary_stem = str(
                            (
                                model_data.ensemble_secondary_stem
                                if process_data.is_ensemble_master
                                else model_data.secondary_stem
                            )
                            or ""
                        )
            else:
                dim_f_set = model_data.mdx_dim_f_set
                dim_t_set = model_data.mdx_dim_t_set
                if dim_f_set is None:
                    dim_f_set = int(MDX_POP_DIMF[0])
                if dim_t_set is None:
                    dim_t_set = 8
                self.dim_f, self.dim_t = int(dim_f_set), 2 ** int(dim_t_set)

            self.n_fft: int = int(model_data.mdx_n_fft_scale_set or 0)
            self.chunks = model_data.chunks
            self.margin = model_data.margin
            self.adjust = 1
            self.dim_c = 4
            self.hop = 1024

        if model_data.process_method == DEMUCS_ARCH_TYPE:
            self.demucs_stems = (
                model_data.demucs_stems
                if main_process_method not in [MDX_ARCH_TYPE, VR_ARCH_TYPE]
                else None
            )
            self.secondary_model_4_stem = model_data.secondary_model_4_stem
            self.secondary_model_4_stem_scale = model_data.secondary_model_4_stem_scale
            self.segment = model_data.segment
            self.demucs_version = model_data.demucs_version
            self.demucs_source_list = model_data.demucs_source_list
            self.demucs_source_map = model_data.demucs_source_map
            self.is_demucs_combine_stems = model_data.is_demucs_combine_stems
            self.demucs_stem_count = model_data.demucs_stem_count
            self.pre_proc_model = model_data.pre_proc_model
            self.device = (
                cpu
                if self.is_other_gpu and self.demucs_version not in [DEMUCS_V3, DEMUCS_V4]
                else self.device
            )

            self.primary_stem = str(
                (
                    model_data.ensemble_primary_stem
                    if process_data.is_ensemble_master
                    else model_data.primary_stem
                )
                or ""
            )
            self.secondary_stem = str(
                (
                    model_data.ensemble_secondary_stem
                    if process_data.is_ensemble_master
                    else model_data.secondary_stem
                )
                or ""
            )

            if (
                self.is_multi_stem_ensemble or self.is_4_stem_ensemble
            ) and not self.is_secondary_model:
                self.is_return_dual = False

            if self.is_multi_stem_ensemble and main_model_primary:
                self.is_4_stem_ensemble = False
                if main_model_primary in self.demucs_source_map.keys():
                    self.primary_stem = main_model_primary
                    self.secondary_stem = secondary_stem(main_model_primary)
                elif secondary_stem(main_model_primary) in self.demucs_source_map.keys():
                    self.primary_stem = secondary_stem(main_model_primary)
                    self.secondary_stem = main_model_primary

            if self.is_secondary_model and not process_data.is_ensemble_master:
                if (
                    not self.demucs_stem_count == 2
                    and model_data.primary_model_primary_stem == INST_STEM
                ):
                    self.primary_stem = VOCAL_STEM
                    self.secondary_stem = INST_STEM
                else:
                    self.primary_stem = str(model_data.primary_model_primary_stem or "")
                    self.secondary_stem = secondary_stem(self.primary_stem)

            self.shifts = model_data.shifts
            self.is_split_mode = (
                model_data.is_split_mode if not self.demucs_version == DEMUCS_V4 else True
            )
            self.primary_model_name, self.primary_sources = self.cached_source_callback(
                DEMUCS_ARCH_TYPE, model_name=self.model_cache_key
            )

        if model_data.process_method == VR_ARCH_TYPE:
            self.primary_model_name, self.primary_sources = self.cached_source_callback(
                VR_ARCH_TYPE, model_name=self.model_cache_key
            )
            self.mp = model_data.vr_model_param
            self.high_end_process = model_data.is_high_end_process
            self.is_tta = model_data.is_tta
            self.is_post_process = model_data.is_post_process
            self.is_gpu_conversion = model_data.is_gpu_conversion
            self.batch_size = model_data.batch_size
            self.window_size = model_data.window_size
            self.input_high_end_h = None
            self.input_high_end = None
            self.post_process_threshold = model_data.post_process_threshold
            self.aggressiveness = {
                'value': model_data.aggression_setting,
                'split_bin': self.mp.param['band'][1]['crop_stop'],
                'aggr_correction': self.mp.param.get('aggr_correction'),
            }

    def start_inference_console_write(self) -> None:
        if self.is_secondary_model and not self.is_pre_proc_model and not self.is_vocal_split_model:
            self.write_to_console(
                INFERENCE_STEP_2_SEC(self.process_method, self.model_display_label)
            )

        if self.is_pre_proc_model:
            self.write_to_console(
                INFERENCE_STEP_2_PRE(self.process_method, self.model_display_label)
            )

        if self.is_vocal_split_model:
            self.write_to_console(
                INFERENCE_STEP_2_VOC_S(self.process_method, self.model_display_label)
            )

    def begin_save_phase(self, total: int) -> None:
        """Reset per-stem save progress (local step 0.90–0.95)."""
        self._save_stem_total = max(1, int(total))
        self._save_stem_index = 0

    def _report_save_progress(self) -> None:
        total = max(1, getattr(self, "_save_stem_total", 1))
        index = getattr(self, "_save_stem_index", 0) + 1
        self._save_stem_index = index
        local = save_progress_local_step(index, total)
        self.set_progress_bar(local)

    def running_inference_console_write(self, is_no_write: bool = False) -> None:
        self.write_to_console(DONE, base_text='') if not is_no_write else None
        self.set_progress_bar(0.05) if not is_no_write else None

        if self.is_secondary_model and not self.is_pre_proc_model and not self.is_vocal_split_model:
            self.write_to_console(INFERENCE_STEP_1_SEC)
        elif self.is_pre_proc_model:
            self.write_to_console(INFERENCE_STEP_1_PRE)
        elif self.is_vocal_split_model:
            self.write_to_console(INFERENCE_STEP_1_VOC_S)
        else:
            self.write_to_console(INFERENCE_STEP_1)

    def report_inference_unit(self) -> None:
        """Advance one hop unit (0.10–0.80)."""
        total = max(1, int(self.progress_total), self._infer_progress.total)
        frac = self._infer_progress.hop(total)
        self.progress_value = self._infer_progress.value
        self.progress_total = self._infer_progress.total
        self.set_progress_bar(0.1, frac - 0.1)

    def running_inference_progress_bar(self, length: float, is_match_mix: bool = False) -> None:
        units = max(1, int(length))
        if is_match_mix:
            frac = self._infer_progress.extra(units)
            self.set_progress_bar(0.1, frac - 0.1)
            return
        if self.progress_total <= 0:
            self.progress_total = units
        elif units > self.progress_total:
            self.progress_total = units
        self.report_inference_unit()

    def denoise_progress_callback(self) -> Any:
        """Continue through 0.80–0.89 across ``vr_denoiser`` patch batches."""

        def on_batch(_done: int, total: int) -> None:
            frac = self._infer_progress.extra(max(1, int(total)))
            self.set_progress_bar(0.1, frac - 0.1)

        return on_batch

    def deverb_progress_callback(self) -> Any:
        """Tick deverb batches inside the current save-stem slice (0.90–0.96)."""

        def on_batch(done: int, total: int) -> None:
            stem_total = max(1, int(getattr(self, "_save_stem_total", 1)))
            index = int(getattr(self, "_save_stem_index", 0))
            start = save_progress_local_step(index, stem_total)
            end = save_progress_local_step(index + 1, stem_total)
            span = max(0.0, end - start)
            self.set_progress_bar(start + span * (max(0, int(done)) / max(1, int(total))))

        return on_batch

    def load_cached_sources(self) -> None:

        if self.is_secondary_model and not self.is_pre_proc_model:
            self.write_to_console(
                INFERENCE_STEP_2_SEC_CACHED_MODOEL(self.process_method, self.model_display_label)
            )
        elif self.is_pre_proc_model:
            self.write_to_console(
                INFERENCE_STEP_2_PRE_CACHED_MODOEL(self.process_method, self.model_display_label)
            )
        else:
            self.write_to_console(INFERENCE_STEP_2_PRIMARY_CACHED, "")

    def cache_source(self, secondary_sources: Any) -> None:

        model_occurrences = self.list_all_models.count(self.model_cache_key)

        if not model_occurrences <= 1:
            if self.process_method == MDX_ARCH_TYPE:
                self.cached_model_source_holder(
                    MDX_ARCH_TYPE, secondary_sources, self.model_cache_key
                )

            if self.process_method == VR_ARCH_TYPE:
                self.cached_model_source_holder(
                    VR_ARCH_TYPE, secondary_sources, self.model_cache_key
                )

            if self.process_method == DEMUCS_ARCH_TYPE:
                self.cached_model_source_holder(
                    DEMUCS_ARCH_TYPE, secondary_sources, self.model_cache_key
                )

    def process_vocal_split_chain(self, sources: dict[str, Any]) -> Any:
        return self._process_vocal_split_chain(sources)

    def _process_vocal_split_chain(self, sources: dict[str, Any]) -> Any:

        def is_valid_vocal_split_condition(master_vocal_source: Any) -> bool:
            """Checks if conditions for vocal split processing are met."""
            conditions = [
                isinstance(master_vocal_source, np.ndarray),
                self.vocal_split_model,
                not self.is_ensemble_mode,
                not self.is_karaoke,
                not self.is_bv_model,
            ]
            return all(conditions)

        # Engine plans publish these canonical handoff keys only after exact
        # reviewed native-route resolution. Raw backend aliases must not gain
        # lead/instrumental meaning at this boundary.
        master_vocal_source = sources.get(VOCAL_STEM)
        master_inst_source = sources.get(INST_STEM)
        if not isinstance(master_vocal_source, np.ndarray):
            master_vocal_source = None
        if not isinstance(master_inst_source, np.ndarray):
            master_inst_source = None

        # Process the vocal split chain if conditions are met. The splitter model
        # is optional: a run with the chain disabled leaves it unset.
        if self.vocal_split_model is not None and is_valid_vocal_split_condition(
            master_vocal_source
        ):
            splitter = (
                getattr(self.vocal_split_model, "model_display_label", None)
                or getattr(self.vocal_split_model, "model_name", None)
                or getattr(self.vocal_split_model, "model_basename", None)
                or "vocal-split"
            )
            with trace_phase("separate", "vocal_split_chain", model=splitter):
                process_chain_model(
                    self.vocal_split_model,
                    self.process_data,
                    vocal_stem_path=self.master_vocal_path,
                    vocal_stem_base=(
                        getattr(self, "audio_file_base", None)
                        if not self.master_vocal_path
                        else None
                    ),
                    master_vocal_source=master_vocal_source,
                    master_inst_source=master_inst_source,
                )

    def process_secondary_stem(
        self,
        stem_source: Any,
        secondary_model_source: Any = None,
        model_scale: float | None = None,
    ) -> Any:
        if not self.is_secondary_model:
            if self.is_secondary_model_activated and isinstance(secondary_model_source, np.ndarray):
                scale = model_scale if model_scale is not None else self.secondary_model_scale
                if scale is None:
                    # A secondary source without a blend ratio means the model
                    # config is inconsistent. Guessing a ratio here would ship
                    # silently wrong audio, so surface it instead.
                    raise ValueError(
                        "secondary model source supplied without a blend scale "
                        f"(model={self.model_display_label!r})"
                    )
                stem_source = spec_utils.average_dual_sources(
                    stem_source, secondary_model_source, float(scale)
                )

        return stem_source

    def stem_export_wav_path(
        self,
        stem: str,
        *,
        route: StemRoute | None = None,
    ) -> str:
        """Return a route-aware output path without changing route identity."""
        for_ensemble = self.is_ensemble_mode and not self.is_vocal_split_model
        if route is not None:
            label = route.filename_tag if for_ensemble else route.label
        else:
            key = export_stem_key(self, stem, for_ensemble=for_ensemble)
            label = filename_tag(key) if isinstance(key, (StemBucket, StemLiteral)) else str(key)
        return stem_wav_path(self.export_path, self.audio_file_base, label)

    def apply_export_stem_levels(
        self,
        sources: dict[str, Any],
        mix: Any,
        *,
        stem_keys: Sequence[str] | None = None,
        allow_match_mix: bool = True,
    ) -> dict:
        """Optionally match multi-stem levels to ``mix`` and/or prevent PCM clipping."""
        from core.stem_levels import (
            apply_stem_level_options,
            export_format_can_clip,
            update_stem_mapping,
        )

        if not sources:
            return sources
        keys = [key for key in (stem_keys or list(sources.keys())) if key in sources]
        subset = {key: sources[key] for key in keys}
        match_mix = bool(self.is_match_mix_level) and allow_match_mix and len(subset) >= 2
        prevent = bool(self.is_prevent_export_clipping) and export_format_can_clip(
            self.save_format, self.wav_type_set
        )
        if not match_mix and not prevent:
            return sources
        adjusted, messages = apply_stem_level_options(
            subset,
            mix,
            match_mix_level=match_mix,
            prevent_export_clipping=prevent,
        )
        update_stem_mapping(sources, adjusted)
        for message in messages:
            self.write_to_console(f"{message}\n")
        return sources

    def write_audio(
        self,
        stem_path: str,
        stem_source: Any,
        samplerate: int,
        stem_name: str | None = None,
        *,
        route: StemRoute | None = None,
    ) -> None:
        from .stem_writer import write_audio as _write_audio

        _write_audio(
            self,
            stem_path,
            stem_source,
            samplerate,
            stem_name,
            route=route,
        )

    def pitch_fix(self, source: Any, sr_pitched: float, org_mix: Any) -> Any:
        semitone_shift = self.semitone_shift
        source = spec_utils.change_pitch_semitones(
            source, sr_pitched, semitone_shift=semitone_shift
        )[0]
        source = spec_utils.match_array_shapes(source, org_mix)
        return source

    def match_frequency_pitch(self, mix: Any) -> Any:
        source = mix
        if self.is_match_frequency_pitch and self.is_pitch_change:
            source, sr_pitched = spec_utils.change_pitch_semitones(
                mix, 44100, semitone_shift=-self.semitone_shift
            )
            source = self.pitch_fix(source, sr_pitched, mix)

        return source
