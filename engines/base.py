from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

import numpy as np
import torch

from bundled.constants import *
from bundled.error_handling import *
from core.debug_log import debug, trace_phase
from core.export_naming import stem_wav_path
from core.gpu_backend import resolve_inference_backend
from core.run_estimate import save_progress_local_step
from core.stems import StemBucket, StemLiteral, StemRoute, export_stem_key, filename_tag
from ml import spec_utils

from .orchestration import process_chain_model
from .runtime import EngineInvocation, EngineRunContext, EngineState
from .runtime_compat import EngineLegacyOptions

if TYPE_CHECKING:
    from core.model_config import ModelConfig
    from core.process_data import ProcessData

cpu = torch.device('cpu')


class SeperateAttributes(EngineLegacyOptions):
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

        self.context = EngineRunContext(
            model_data, process_data,
            EngineInvocation(main_model_primary_stem_4_stem, main_process_method,
                             is_return_dual, main_model_primary, vocal_stem_path,
                             master_inst_source, master_vocal_source),
        )
        self.state = EngineState()
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
        self.is_return_dual = is_return_dual
        self.mdxnet_stems_selected = getattr(model_data, "mdxnet_stems_selected", []) or []
        self.available_stem_routes = tuple(getattr(model_data, "available_stem_routes", ()) or ())
        self.selected_stem_routes = tuple(getattr(model_data, "selected_stem_routes", ()) or ())
        selection_provenance = getattr(model_data, "selected_stem_routes_explicit", None)
        self.selected_stem_routes_explicit: bool | None = (
            selection_provenance if isinstance(selection_provenance, bool) else None
        )
        self.is_secondary_model_activated = (
            self.context.secondary.is_secondary_model_activated if not self.is_pre_proc_model else False
        )
        self.is_secondary_model = (
            self.context.common.is_secondary_model if not self.is_pre_proc_model else True
        )
        self.backend_name = (
            getattr(model_data, "backend_name", None)
            or model_data.model_basename
            or model_data.model_name
            or ""
        )
        self.model_cache_key = self.backend_name or model_data.model_basename or ""
        self.model_display_label = (
            getattr(model_data, "model_display_label", None)
            or model_data.model_name
            or model_data.model_basename
            or ""
        )
        self.is_save_all_outputs_ensemble = bool(process_data.is_save_all_outputs_ensemble)
        # Long-file chunking / ensemble scratch: keep stem arrays, skip disk write.
        self.capture_stems_only = bool(process_data.capture_stems_only)
        self.primary_stem: str = str(self.context.routing.primary_stem or "")  #
        self.secondary_stem: str = str(self.context.routing.secondary_stem or "")  #
        self.main_model_primary_stem_4_stem = main_model_primary_stem_4_stem
        self.main_model_primary = main_model_primary
        self.is_other_gpu = False
        self.is_deverb = True
        self.is_source_swap = False
        self.master_vocal_path: Any = None
        self.set_master_inst_source: Any = None
        self.master_inst_source: Any = master_inst_source
        self.master_vocal_source: Any = master_vocal_source
        self.is_save_inst_vocal_splitter = (
            isinstance(master_inst_source, np.ndarray) and self.context.common.is_save_inst_vocal_splitter
        )
        self.is_bv_model_rebalenced = self.context.common.bv_model_rebalance and self.is_vocal_split_model
        self.stem_path_init = self.stem_export_wav_path(self.secondary_stem)
        self.device = cpu
        self.run_type = ['CPUExecutionProvider']
        self._backend_name = "cpu"
        backend = resolve_inference_backend(
            use_gpu=bool(self.is_gpu_conversion),
            device_set=self.device_set,
            is_use_directml=self.context.device.is_use_directml,
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
        # ``is_target_instrument`` / ``is_vocal_main_target`` enable the new
        # roformer stem handling (single target_instrument treated as
        # vocals+instrumental). Gate them on ``is_roformer`` so classic
        # (non-roformer) MDX-C models keep their original single-stem behaviour.
        self.is_target_instrument = self.context.mdx.is_target_instrument and self.is_roformer

        if main_model_primary and self.is_multi_stem_ensemble:
            self.primary_stem, self.secondary_stem = (
                main_model_primary,
                secondary_stem(main_model_primary),
            )

        if self.context.identity.process_method == MDX_ARCH_TYPE:
            self.primary_model_name, self.primary_sources = self.cached_source_callback(
                MDX_ARCH_TYPE, model_name=self.model_cache_key
            )
            # Needed by export_stem_key: without a stem count, a 4-stem
            # model's MUSDB ``other`` residual is read as the 2-stem
            # instrumental complement and exported as ``Instrumental``.

            if self.is_mdx_c:
                if not self.is_4_stem_ensemble:
                    if not self.is_target_instrument:
                        self.primary_stem = str(
                            (
                                self.context.ensemble.ensemble_primary_stem
                                if process_data.is_ensemble_master
                                else self.context.routing.primary_stem
                            )
                            or ""
                        )
                        self.secondary_stem = str(
                            (
                                self.context.ensemble.ensemble_secondary_stem
                                if process_data.is_ensemble_master
                                else self.context.routing.secondary_stem
                            )
                            or ""
                        )
            else:
                dim_f_set = self.context.mdx.mdx_dim_f_set
                dim_t_set = self.context.mdx.mdx_dim_t_set
                if dim_f_set is None:
                    dim_f_set = int(MDX_POP_DIMF[0])
                if dim_t_set is None:
                    dim_t_set = 8
                self.dim_f, self.dim_t = int(dim_f_set), 2 ** int(dim_t_set)

            self.n_fft: int = int(self.context.mdx.mdx_n_fft_scale_set or 0)
            self.adjust = 1
            self.dim_c = 4
            self.hop = 1024

        if self.context.identity.process_method == DEMUCS_ARCH_TYPE:
            self.demucs_stems = (
                self.context.demucs.demucs_stems
                if main_process_method not in [MDX_ARCH_TYPE, VR_ARCH_TYPE]
                else None
            )
            self.device = (
                cpu
                if self.is_other_gpu and self.demucs_version not in [DEMUCS_V3, DEMUCS_V4]
                else self.device
            )

            self.primary_stem = str(
                (
                    self.context.ensemble.ensemble_primary_stem
                    if process_data.is_ensemble_master
                    else self.context.routing.primary_stem
                )
                or ""
            )
            self.secondary_stem = str(
                (
                    self.context.ensemble.ensemble_secondary_stem
                    if process_data.is_ensemble_master
                    else self.context.routing.secondary_stem
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
                    and self.context.routing.primary_model_primary_stem == INST_STEM
                ):
                    self.primary_stem = VOCAL_STEM
                    self.secondary_stem = INST_STEM
                else:
                    self.primary_stem = str(self.context.routing.primary_model_primary_stem or "")
                    self.secondary_stem = secondary_stem(self.primary_stem)

            self.is_split_mode = (
                self.context.demucs.is_split_mode if not self.demucs_version == DEMUCS_V4 else True
            )
            self.primary_model_name, self.primary_sources = self.cached_source_callback(
                DEMUCS_ARCH_TYPE, model_name=self.model_cache_key
            )

        if self.context.identity.process_method == VR_ARCH_TYPE:
            self.primary_model_name, self.primary_sources = self.cached_source_callback(
                VR_ARCH_TYPE, model_name=self.model_cache_key
            )
            self.input_high_end_h = None
            self.input_high_end = None
            self.aggressiveness = {
                'value': self.context.vr.aggression_setting,
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
