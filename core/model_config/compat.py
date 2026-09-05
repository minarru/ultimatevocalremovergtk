"""Explicit live adapters for the stable flat ModelConfig API.

Option groups own the values. Legacy sequence getters expose the backing object
so appends and reference replacement retain their original Python semantics.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

from ..model_identity import ModelArtifacts
from ..stem_roles import ModelStemSemantics
from ..stems import StemRoute
from .base import (
    CommonRunOptions,
    DeviceOptions,
    EnsembleMemberFlags,
    ExportOptions,
    ModelIdentity,
    SecondaryChain,
    StemRouting,
)
from .demucs import DemucsOptions
from .mdx import MDXOptions
from .vr import VROptions


class ModelIdentityLegacyOptions:
    identity: ModelIdentity

    @property
    def model_name(self) -> str:
        return self.identity.model_name

    @model_name.setter
    def model_name(self, value: str) -> None:
        self.identity.model_name = value

    @property
    def canonical_id(self) -> str:
        return self.identity.canonical_id

    @canonical_id.setter
    def canonical_id(self, value: str) -> None:
        self.identity.canonical_id = value

    @property
    def model_display_label(self) -> str:
        return self.identity.model_display_label

    @model_display_label.setter
    def model_display_label(self, value: str) -> None:
        self.identity.model_display_label = value

    @property
    def backend_name(self) -> str:
        return self.identity.backend_name

    @backend_name.setter
    def backend_name(self, value: str) -> None:
        self.identity.backend_name = value

    @property
    def model_artifacts(self) -> Optional[ModelArtifacts]:
        return self.identity.model_artifacts

    @model_artifacts.setter
    def model_artifacts(self, value: Optional[ModelArtifacts]) -> None:
        self.identity.model_artifacts = value

    @property
    def process_method(self) -> str:
        return self.identity.process_method

    @process_method.setter
    def process_method(self, value: str) -> None:
        self.identity.process_method = value

    @property
    def model_path(self) -> Any:
        return self.identity.model_path

    @model_path.setter
    def model_path(self, value: Optional[str]) -> None:
        self.identity.model_path = value

    @property
    def model_basename(self) -> Any:
        return self.identity.model_basename

    @model_basename.setter
    def model_basename(self, value: Optional[str]) -> None:
        self.identity.model_basename = value

    @property
    def model_hash(self) -> Optional[str]:
        return self.identity.model_hash

    @model_hash.setter
    def model_hash(self, value: Optional[str]) -> None:
        self.identity.model_hash = value

    @property
    def model_status(self) -> bool:
        return self.identity.model_status

    @model_status.setter
    def model_status(self, value: bool) -> None:
        self.identity.model_status = value

    @property
    def model_and_process_tag(self) -> Any:
        return self.identity.model_and_process_tag

    @model_and_process_tag.setter
    def model_and_process_tag(self, value: Optional[str]) -> None:
        self.identity.model_and_process_tag = value


class ExportOptionsLegacyOptions:
    export_options: ExportOptions

    @property
    def wav_type_set(self) -> Any:
        return self.export_options.wav_type_set

    @wav_type_set.setter
    def wav_type_set(self, value: Any) -> None:
        self.export_options.wav_type_set = value

    @property
    def mp3_bit_set(self) -> str:
        return self.export_options.mp3_bit_set

    @mp3_bit_set.setter
    def mp3_bit_set(self, value: str) -> None:
        self.export_options.mp3_bit_set = value

    @property
    def flac_bit_set(self) -> str:
        return self.export_options.flac_bit_set

    @flac_bit_set.setter
    def flac_bit_set(self, value: str) -> None:
        self.export_options.flac_bit_set = value

    @property
    def opus_bit_set(self) -> str:
        return self.export_options.opus_bit_set

    @opus_bit_set.setter
    def opus_bit_set(self, value: str) -> None:
        self.export_options.opus_bit_set = value

    @property
    def save_format(self) -> str:
        return self.export_options.save_format

    @save_format.setter
    def save_format(self, value: str) -> None:
        self.export_options.save_format = value

    @property
    def is_normalization(self) -> bool:
        return self.export_options.is_normalization

    @is_normalization.setter
    def is_normalization(self, value: bool) -> None:
        self.export_options.is_normalization = value

    @property
    def is_match_mix_level(self) -> bool:
        return self.export_options.is_match_mix_level

    @is_match_mix_level.setter
    def is_match_mix_level(self, value: bool) -> None:
        self.export_options.is_match_mix_level = value

    @property
    def is_prevent_export_clipping(self) -> bool:
        return self.export_options.is_prevent_export_clipping

    @is_prevent_export_clipping.setter
    def is_prevent_export_clipping(self, value: bool) -> None:
        self.export_options.is_prevent_export_clipping = value

    @property
    def amplification_threshold(self) -> float:
        return self.export_options.amplification_threshold

    @amplification_threshold.setter
    def amplification_threshold(self, value: float) -> None:
        self.export_options.amplification_threshold = value


class DeviceOptionsLegacyOptions:
    device_options: DeviceOptions

    @property
    def device_set(self) -> str:
        return self.device_options.device_set

    @device_set.setter
    def device_set(self, value: str) -> None:
        self.device_options.device_set = value

    @property
    def is_use_directml(self) -> bool:
        return self.device_options.is_use_directml

    @is_use_directml.setter
    def is_use_directml(self, value: bool) -> None:
        self.device_options.is_use_directml = value

    @property
    def is_gpu_conversion(self) -> bool:
        return self.device_options.use_gpu

    @is_gpu_conversion.setter
    def is_gpu_conversion(self, value: bool) -> None:
        self.device_options.use_gpu = value

    @property
    def use_gpu(self) -> bool:
        return self.device_options.use_gpu

    @use_gpu.setter
    def use_gpu(self, value: bool) -> None:
        self.device_options.use_gpu = value


class EnsembleMemberFlagsLegacyOptions:
    ensemble_flags: EnsembleMemberFlags

    @property
    def is_ensemble_mode(self) -> bool:
        return self.ensemble_flags.is_ensemble_mode

    @is_ensemble_mode.setter
    def is_ensemble_mode(self, value: bool) -> None:
        self.ensemble_flags.is_ensemble_mode = value

    @property
    def is_4_stem_ensemble(self) -> bool:
        return self.ensemble_flags.is_4_stem_ensemble

    @is_4_stem_ensemble.setter
    def is_4_stem_ensemble(self, value: bool) -> None:
        self.ensemble_flags.is_4_stem_ensemble = value

    @property
    def is_multi_stem_ensemble(self) -> bool:
        return self.ensemble_flags.is_multi_stem_ensemble

    @is_multi_stem_ensemble.setter
    def is_multi_stem_ensemble(self, value: bool) -> None:
        self.ensemble_flags.is_multi_stem_ensemble = value

    @property
    def ensemble_primary_stem(self) -> Optional[str]:
        return self.ensemble_flags.ensemble_primary_stem

    @ensemble_primary_stem.setter
    def ensemble_primary_stem(self, value: Optional[str]) -> None:
        self.ensemble_flags.ensemble_primary_stem = value

    @property
    def ensemble_secondary_stem(self) -> Optional[str]:
        return self.ensemble_flags.ensemble_secondary_stem

    @ensemble_secondary_stem.setter
    def ensemble_secondary_stem(self, value: Optional[str]) -> None:
        self.ensemble_flags.ensemble_secondary_stem = value


class StemRoutingLegacyOptions:
    stem_routing: StemRouting

    @property
    def primary_stem(self) -> Optional[str]:
        return self.stem_routing.primary_stem

    @primary_stem.setter
    def primary_stem(self, value: Optional[str]) -> None:
        self.stem_routing.primary_stem = value

    @property
    def secondary_stem(self) -> Optional[str]:
        return self.stem_routing.secondary_stem

    @secondary_stem.setter
    def secondary_stem(self, value: Optional[str]) -> None:
        self.stem_routing.secondary_stem = value

    @property
    def primary_stem_native(self) -> Optional[str]:
        return self.stem_routing.primary_stem_native

    @primary_stem_native.setter
    def primary_stem_native(self, value: Optional[str]) -> None:
        self.stem_routing.primary_stem_native = value

    @property
    def primary_model_primary_stem(self) -> Optional[str]:
        return self.stem_routing.primary_model_primary_stem

    @primary_model_primary_stem.setter
    def primary_model_primary_stem(self, value: Optional[str]) -> None:
        self.stem_routing.primary_model_primary_stem = value

    @property
    def mdx_model_stems(self) -> list[str]:
        return self.stem_routing._mdx_model_stems

    @mdx_model_stems.setter
    def mdx_model_stems(self, value: list[str]) -> None:
        self.stem_routing._mdx_model_stems = value

    @property
    def demucs_source_list(self) -> Sequence[str]:
        return self.stem_routing._demucs_source_list

    @demucs_source_list.setter
    def demucs_source_list(self, value: Sequence[str]) -> None:
        self.stem_routing._demucs_source_list = value

    @property
    def available_stem_routes(self) -> Tuple[StemRoute, ...]:
        return self.stem_routing.available_routes

    @available_stem_routes.setter
    def available_stem_routes(self, value: Tuple[StemRoute, ...]) -> None:
        self.stem_routing.available_routes = value

    @property
    def selected_stem_routes(self) -> Tuple[StemRoute, ...]:
        return self.stem_routing.selected_routes

    @selected_stem_routes.setter
    def selected_stem_routes(self, value: Tuple[StemRoute, ...]) -> None:
        self.stem_routing.selected_routes = value

    @property
    def selected_stem_routes_explicit(self) -> bool:
        return self.stem_routing.selected_routes_explicit

    @selected_stem_routes_explicit.setter
    def selected_stem_routes_explicit(self, value: bool) -> None:
        self.stem_routing.selected_routes_explicit = value

    @property
    def stem_semantics(self) -> ModelStemSemantics | None:
        return self.stem_routing.semantics

    @stem_semantics.setter
    def stem_semantics(self, value: ModelStemSemantics | None) -> None:
        self.stem_routing.semantics = value


class SecondaryChainLegacyOptions:
    secondary_chain: SecondaryChain

    @property
    def secondary_model(self) -> Any:
        return self.secondary_chain.secondary_model

    @secondary_model.setter
    def secondary_model(self, value: Any) -> None:
        self.secondary_chain.secondary_model = value

    @property
    def secondary_model_scale(self) -> Optional[float]:
        return self.secondary_chain.secondary_model_scale

    @secondary_model_scale.setter
    def secondary_model_scale(self, value: Optional[float]) -> None:
        self.secondary_chain.secondary_model_scale = value

    @property
    def secondary_model_4_stem(self) -> list[Any]:
        return self.secondary_chain._secondary_model_4_stem

    @secondary_model_4_stem.setter
    def secondary_model_4_stem(self, value: list[Any]) -> None:
        self.secondary_chain._secondary_model_4_stem = value

    @property
    def secondary_model_4_stem_scale(self) -> list[Any]:
        return self.secondary_chain._secondary_model_4_stem_scale

    @secondary_model_4_stem_scale.setter
    def secondary_model_4_stem_scale(self, value: list[Any]) -> None:
        self.secondary_chain._secondary_model_4_stem_scale = value

    @property
    def secondary_model_4_stem_names(self) -> list[str]:
        return self.secondary_chain._secondary_model_4_stem_names

    @secondary_model_4_stem_names.setter
    def secondary_model_4_stem_names(self, value: list[str]) -> None:
        self.secondary_chain._secondary_model_4_stem_names = value

    @property
    def secondary_model_4_stem_model_names_list(self) -> list[Any]:
        return self.secondary_chain._secondary_model_4_stem_model_names_list

    @secondary_model_4_stem_model_names_list.setter
    def secondary_model_4_stem_model_names_list(self, value: list[Any]) -> None:
        self.secondary_chain._secondary_model_4_stem_model_names_list = value

    @property
    def demucs_4_stem_added_count(self) -> int:
        return self.secondary_chain.demucs_4_stem_added_count

    @demucs_4_stem_added_count.setter
    def demucs_4_stem_added_count(self, value: int) -> None:
        self.secondary_chain.demucs_4_stem_added_count = value

    @property
    def is_demucs_4_stem_secondaries(self) -> bool:
        return self.secondary_chain.is_demucs_4_stem_secondaries

    @is_demucs_4_stem_secondaries.setter
    def is_demucs_4_stem_secondaries(self, value: bool) -> None:
        self.secondary_chain.is_demucs_4_stem_secondaries = value

    @property
    def pre_proc_model(self) -> Any:
        return self.secondary_chain.pre_proc_model

    @pre_proc_model.setter
    def pre_proc_model(self, value: Any) -> None:
        self.secondary_chain.pre_proc_model = value

    @property
    def vocal_split_model(self) -> Any:
        return self.secondary_chain.vocal_split_model

    @vocal_split_model.setter
    def vocal_split_model(self, value: Any) -> None:
        self.secondary_chain.vocal_split_model = value

    @property
    def is_secondary_model_activated(self) -> bool:
        return self.secondary_chain.is_secondary_model_activated

    @is_secondary_model_activated.setter
    def is_secondary_model_activated(self, value: bool) -> None:
        self.secondary_chain.is_secondary_model_activated = value

    @property
    def pre_proc_model_activated(self) -> bool:
        return self.secondary_chain.pre_proc_model_activated

    @pre_proc_model_activated.setter
    def pre_proc_model_activated(self, value: bool) -> None:
        self.secondary_chain.pre_proc_model_activated = value

    @property
    def is_vocal_split_model_activated(self) -> bool:
        return self.secondary_chain.is_vocal_split_model_activated

    @is_vocal_split_model_activated.setter
    def is_vocal_split_model_activated(self, value: bool) -> None:
        self.secondary_chain.is_vocal_split_model_activated = value


class VROptionsLegacyOptions:
    _vr_options: VROptions

    @property
    def aggression_setting(self) -> float:
        return self._vr_options.aggression_setting

    @aggression_setting.setter
    def aggression_setting(self, value: float) -> None:
        self._vr_options.aggression_setting = value

    @property
    def is_tta(self) -> bool:
        return self._vr_options.is_tta

    @is_tta.setter
    def is_tta(self, value: bool) -> None:
        self._vr_options.is_tta = value

    @property
    def is_post_process(self) -> bool:
        return self._vr_options.is_post_process

    @is_post_process.setter
    def is_post_process(self, value: bool) -> None:
        self._vr_options.is_post_process = value

    @property
    def window_size(self) -> int:
        return self._vr_options.window_size

    @window_size.setter
    def window_size(self, value: int) -> None:
        self._vr_options.window_size = value

    @property
    def batch_size(self) -> int:
        return self._vr_options.batch_size

    @batch_size.setter
    def batch_size(self, value: int) -> None:
        self._vr_options.batch_size = value

    @property
    def crop_size(self) -> int:
        return self._vr_options.crop_size

    @crop_size.setter
    def crop_size(self, value: int) -> None:
        self._vr_options.crop_size = value

    @property
    def is_high_end_process(self) -> str:
        return self._vr_options.is_high_end_process

    @is_high_end_process.setter
    def is_high_end_process(self, value: str) -> None:
        self._vr_options.is_high_end_process = value

    @property
    def post_process_threshold(self) -> float:
        return self._vr_options.post_process_threshold

    @post_process_threshold.setter
    def post_process_threshold(self, value: float) -> None:
        self._vr_options.post_process_threshold = value

    @property
    def model_capacity(self) -> Tuple[int, int]:
        return self._vr_options.model_capacity

    @model_capacity.setter
    def model_capacity(self, value: Tuple[int, int]) -> None:
        self._vr_options.model_capacity = value

    @property
    def model_samplerate(self) -> int:
        return self._vr_options.model_samplerate

    @model_samplerate.setter
    def model_samplerate(self, value: int) -> None:
        self._vr_options.model_samplerate = value

    @property
    def vr_model_param(self) -> Any:
        return self._vr_options.vr_model_param

    @vr_model_param.setter
    def vr_model_param(self, value: Any) -> None:
        self._vr_options.vr_model_param = value

    @property
    def is_vr_51_model(self) -> bool:
        return self._vr_options.is_vr_51_model

    @is_vr_51_model.setter
    def is_vr_51_model(self, value: bool) -> None:
        self._vr_options.is_vr_51_model = value


class MDXOptionsLegacyOptions:
    _mdx_options: MDXOptions

    @property
    def margin(self) -> int:
        return self._mdx_options.margin

    @margin.setter
    def margin(self, value: int) -> None:
        self._mdx_options.margin = value

    @property
    def chunks(self) -> int:
        return self._mdx_options.chunks

    @chunks.setter
    def chunks(self, value: int) -> None:
        self._mdx_options.chunks = value

    @property
    def mdx_segment_size(self) -> int:
        return self._mdx_options.mdx_segment_size

    @mdx_segment_size.setter
    def mdx_segment_size(self, value: int) -> None:
        self._mdx_options.mdx_segment_size = value

    @property
    def mdx_batch_size(self) -> int:
        return self._mdx_options.mdx_batch_size

    @mdx_batch_size.setter
    def mdx_batch_size(self, value: int) -> None:
        self._mdx_options.mdx_batch_size = value

    @property
    def mdxnet_stem_select(self) -> Optional[str]:
        return self._mdx_options.mdxnet_stem_select

    @mdxnet_stem_select.setter
    def mdxnet_stem_select(self, value: Optional[str]) -> None:
        self._mdx_options.mdxnet_stem_select = value

    @property
    def mdxnet_stems_selected(self) -> list[str]:
        return self._mdx_options._mdxnet_stems_selected

    @mdxnet_stems_selected.setter
    def mdxnet_stems_selected(self, value: list[str]) -> None:
        self._mdx_options._mdxnet_stems_selected = value

    @property
    def overlap_mdx(self) -> float:
        return self._mdx_options.overlap_mdx

    @overlap_mdx.setter
    def overlap_mdx(self, value: float) -> None:
        self._mdx_options.overlap_mdx = value

    @property
    def overlap_mdx23(self) -> int:
        return self._mdx_options.overlap_mdx23

    @overlap_mdx23.setter
    def overlap_mdx23(self, value: int) -> None:
        self._mdx_options.overlap_mdx23 = value

    @property
    def is_mdx_ckpt(self) -> bool:
        return self._mdx_options.is_mdx_ckpt

    @is_mdx_ckpt.setter
    def is_mdx_ckpt(self, value: bool) -> None:
        self._mdx_options.is_mdx_ckpt = value

    @property
    def is_mdx_c(self) -> bool:
        return self._mdx_options.is_mdx_c

    @is_mdx_c.setter
    def is_mdx_c(self, value: bool) -> None:
        self._mdx_options.is_mdx_c = value

    @property
    def is_roformer(self) -> bool:
        return self._mdx_options.is_roformer

    @is_roformer.setter
    def is_roformer(self, value: bool) -> None:
        self._mdx_options.is_roformer = value

    @property
    def is_target_instrument(self) -> bool:
        return self._mdx_options.is_target_instrument

    @is_target_instrument.setter
    def is_target_instrument(self, value: bool) -> None:
        self._mdx_options.is_target_instrument = value

    @property
    def model_type(self) -> str:
        return self._mdx_options.model_type

    @model_type.setter
    def model_type(self, value: str) -> None:
        self._mdx_options.model_type = value

    @property
    def mdx_c_configs(self) -> Any:
        return self._mdx_options.mdx_c_configs

    @mdx_c_configs.setter
    def mdx_c_configs(self, value: Any) -> None:
        self._mdx_options.mdx_c_configs = value

    @property
    def mdx_stem_count(self) -> int:
        return self._mdx_options.mdx_stem_count

    @mdx_stem_count.setter
    def mdx_stem_count(self, value: int) -> None:
        self._mdx_options.mdx_stem_count = value

    @property
    def compensate(self) -> Optional[float]:
        return self._mdx_options.compensate

    @compensate.setter
    def compensate(self, value: Optional[float]) -> None:
        self._mdx_options.compensate = value

    @property
    def mdx_dim_f_set(self) -> Optional[int]:
        return self._mdx_options.mdx_dim_f_set

    @mdx_dim_f_set.setter
    def mdx_dim_f_set(self, value: Optional[int]) -> None:
        self._mdx_options.mdx_dim_f_set = value

    @property
    def mdx_dim_t_set(self) -> Optional[int]:
        return self._mdx_options.mdx_dim_t_set

    @mdx_dim_t_set.setter
    def mdx_dim_t_set(self, value: Optional[int]) -> None:
        self._mdx_options.mdx_dim_t_set = value

    @property
    def mdx_n_fft_scale_set(self) -> Optional[int]:
        return self._mdx_options.mdx_n_fft_scale_set

    @mdx_n_fft_scale_set.setter
    def mdx_n_fft_scale_set(self, value: Optional[int]) -> None:
        self._mdx_options.mdx_n_fft_scale_set = value

    @property
    def is_mdx_c_seg_def(self) -> bool:
        return self._mdx_options.is_mdx_c_seg_def

    @is_mdx_c_seg_def.setter
    def is_mdx_c_seg_def(self, value: bool) -> None:
        self._mdx_options.is_mdx_c_seg_def = value

    @property
    def is_denoise(self) -> bool:
        return self._mdx_options.is_denoise

    @is_denoise.setter
    def is_denoise(self, value: bool) -> None:
        self._mdx_options.is_denoise = value

    @property
    def is_denoise_model(self) -> bool:
        return self._mdx_options.is_denoise_model

    @is_denoise_model.setter
    def is_denoise_model(self, value: bool) -> None:
        self._mdx_options.is_denoise_model = value

    @property
    def is_match_frequency_pitch(self) -> bool:
        return self._mdx_options.is_match_frequency_pitch

    @is_match_frequency_pitch.setter
    def is_match_frequency_pitch(self, value: bool) -> None:
        self._mdx_options.is_match_frequency_pitch = value

    @property
    def is_mdx_combine_stems(self) -> bool:
        return self._mdx_options.is_mdx_combine_stems

    @is_mdx_combine_stems.setter
    def is_mdx_combine_stems(self, value: bool) -> None:
        self._mdx_options.is_mdx_combine_stems = value

    @property
    def is_mdx_include_stem_complement(self) -> bool:
        return self._mdx_options.is_mdx_include_stem_complement

    @is_mdx_include_stem_complement.setter
    def is_mdx_include_stem_complement(self, value: bool) -> None:
        self._mdx_options.is_mdx_include_stem_complement = value

    @property
    def is_invert_spec(self) -> bool:
        return self._mdx_options.is_invert_spec

    @is_invert_spec.setter
    def is_invert_spec(self, value: bool) -> None:
        self._mdx_options.is_invert_spec = value

    @property
    def is_mixer_mode(self) -> bool:
        return self._mdx_options.is_mixer_mode

    @is_mixer_mode.setter
    def is_mixer_mode(self, value: bool) -> None:
        self._mdx_options.is_mixer_mode = value

    @property
    def mixer_path(self) -> str:
        return self._mdx_options.mixer_path

    @mixer_path.setter
    def mixer_path(self, value: str) -> None:
        self._mdx_options.mixer_path = value

    @property
    def mdx_config_yaml(self) -> str:
        return self._mdx_options.mdx_config_yaml

    @mdx_config_yaml.setter
    def mdx_config_yaml(self, value: str) -> None:
        self._mdx_options.mdx_config_yaml = value

    @property
    def mdx_config_sha256(self) -> str:
        return self._mdx_options.mdx_config_sha256

    @mdx_config_sha256.setter
    def mdx_config_sha256(self, value: str) -> None:
        self._mdx_options.mdx_config_sha256 = value

    @property
    def mdx_hash_record_source(self) -> str:
        return self._mdx_options.mdx_hash_record_source

    @mdx_hash_record_source.setter
    def mdx_hash_record_source(self, value: str) -> None:
        self._mdx_options.mdx_hash_record_source = value

    @property
    def mdx_runtime_reconciliation(self) -> Any:
        return self._mdx_options.mdx_runtime_reconciliation

    @mdx_runtime_reconciliation.setter
    def mdx_runtime_reconciliation(self, value: Any) -> None:
        self._mdx_options.mdx_runtime_reconciliation = value


class DemucsOptionsLegacyOptions:
    _demucs_options: DemucsOptions

    @property
    def shifts(self) -> int:
        return self._demucs_options.shifts

    @shifts.setter
    def shifts(self, value: int) -> None:
        self._demucs_options.shifts = value

    @property
    def is_split_mode(self) -> bool:
        return self._demucs_options.is_split_mode

    @is_split_mode.setter
    def is_split_mode(self, value: bool) -> None:
        self._demucs_options.is_split_mode = value

    @property
    def segment(self) -> Any:
        return self._demucs_options.segment

    @segment.setter
    def segment(self, value: Any) -> None:
        self._demucs_options.segment = value

    @property
    def demucs_stems(self) -> Optional[str]:
        return self._demucs_options.demucs_stems

    @demucs_stems.setter
    def demucs_stems(self, value: Optional[str]) -> None:
        self._demucs_options.demucs_stems = value

    @property
    def is_demucs_combine_stems(self) -> bool:
        return self._demucs_options.is_demucs_combine_stems

    @is_demucs_combine_stems.setter
    def is_demucs_combine_stems(self, value: bool) -> None:
        self._demucs_options.is_demucs_combine_stems = value

    @property
    def demucs_source_map(self) -> Any:
        return self._demucs_options.demucs_source_map

    @demucs_source_map.setter
    def demucs_source_map(self, value: Any) -> None:
        self._demucs_options.demucs_source_map = value

    @property
    def demucs_stem_count(self) -> int:
        return self._demucs_options.demucs_stem_count

    @demucs_stem_count.setter
    def demucs_stem_count(self, value: int) -> None:
        self._demucs_options.demucs_stem_count = value

    @property
    def demucs_version(self) -> Any:
        return self._demucs_options.demucs_version

    @demucs_version.setter
    def demucs_version(self, value: Optional[str]) -> None:
        self._demucs_options.demucs_version = value

    @property
    def overlap(self) -> float:
        return self._demucs_options.overlap

    @overlap.setter
    def overlap(self, value: float) -> None:
        self._demucs_options.overlap = value

    @property
    def is_demucs_pre_proc_model_inst_mix(self) -> bool:
        return self._demucs_options.is_demucs_pre_proc_model_inst_mix

    @is_demucs_pre_proc_model_inst_mix.setter
    def is_demucs_pre_proc_model_inst_mix(self, value: bool) -> None:
        self._demucs_options.is_demucs_pre_proc_model_inst_mix = value


class CommonRunOptionsLegacyOptions:
    common_options: CommonRunOptions

    @property
    def DENOISER_MODEL(self) -> str:
        return self.common_options.DENOISER_MODEL

    @DENOISER_MODEL.setter
    def DENOISER_MODEL(self, value: str) -> None:
        self.common_options.DENOISER_MODEL = value

    @property
    def DEVERBER_MODEL(self) -> str:
        return self.common_options.DEVERBER_MODEL

    @DEVERBER_MODEL.setter
    def DEVERBER_MODEL(self, value: str) -> None:
        self.common_options.DEVERBER_MODEL = value

    @property
    def all_models(self) -> Any:
        return self.common_options.all_models

    @all_models.setter
    def all_models(self, value: Any) -> None:
        self.common_options.all_models = value

    @property
    def bv_model_rebalance(self) -> float | None:
        return self.common_options.bv_model_rebalance

    @bv_model_rebalance.setter
    def bv_model_rebalance(self, value: float | None) -> None:
        self.common_options.bv_model_rebalance = value

    @property
    def deverb_vocal_opt(self) -> Any:
        return self.common_options.deverb_vocal_opt

    @deverb_vocal_opt.setter
    def deverb_vocal_opt(self, value: Any) -> None:
        self.common_options.deverb_vocal_opt = value

    @property
    def ensemble_pair_roles(self) -> tuple[object, ...]:
        return self.common_options.ensemble_pair_roles

    @ensemble_pair_roles.setter
    def ensemble_pair_roles(self, value: tuple[object, ...]) -> None:
        self.common_options.ensemble_pair_roles = value

    @property
    def is_bv_model(self) -> bool:
        return self.common_options.is_bv_model

    @is_bv_model.setter
    def is_bv_model(self, value: bool) -> None:
        self.common_options.is_bv_model = value

    @property
    def is_change_def(self) -> bool:
        return self.common_options.is_change_def

    @is_change_def.setter
    def is_change_def(self, value: bool) -> None:
        self.common_options.is_change_def = value

    @property
    def is_deverb_vocals(self) -> bool:
        return self.common_options.is_deverb_vocals

    @is_deverb_vocals.setter
    def is_deverb_vocals(self, value: bool) -> None:
        self.common_options.is_deverb_vocals = value

    @property
    def is_dry_check(self) -> bool:
        return self.common_options.is_dry_check

    @is_dry_check.setter
    def is_dry_check(self, value: bool) -> None:
        self.common_options.is_dry_check = value

    @property
    def is_get_hash_dir_only(self) -> bool:
        return self.common_options.is_get_hash_dir_only

    @is_get_hash_dir_only.setter
    def is_get_hash_dir_only(self, value: bool) -> None:
        self.common_options.is_get_hash_dir_only = value

    @property
    def is_inst_only_voc_splitter(self) -> bool:
        return self.common_options.is_inst_only_voc_splitter

    @is_inst_only_voc_splitter.setter
    def is_inst_only_voc_splitter(self, value: bool) -> None:
        self.common_options.is_inst_only_voc_splitter = value

    @property
    def is_karaoke(self) -> bool:
        return self.common_options.is_karaoke

    @is_karaoke.setter
    def is_karaoke(self, value: bool) -> None:
        self.common_options.is_karaoke = value

    @property
    def is_karaoke_curated(self) -> bool:
        return self.common_options.is_karaoke_curated

    @is_karaoke_curated.setter
    def is_karaoke_curated(self, value: bool) -> None:
        self.common_options.is_karaoke_curated = value

    @property
    def is_pitch_change(self) -> bool:
        return self.common_options.is_pitch_change

    @is_pitch_change.setter
    def is_pitch_change(self, value: bool) -> None:
        self.common_options.is_pitch_change = value

    @property
    def is_pre_proc_model(self) -> bool:
        return self.common_options.is_pre_proc_model

    @is_pre_proc_model.setter
    def is_pre_proc_model(self, value: bool) -> None:
        self.common_options.is_pre_proc_model = value

    @property
    def is_save_inst_vocal_splitter(self) -> bool:
        return self.common_options.is_save_inst_vocal_splitter

    @is_save_inst_vocal_splitter.setter
    def is_save_inst_vocal_splitter(self, value: bool) -> None:
        self.common_options.is_save_inst_vocal_splitter = value

    @property
    def is_save_vocal_only(self) -> bool:
        return self.common_options.is_save_vocal_only

    @is_save_vocal_only.setter
    def is_save_vocal_only(self, value: bool) -> None:
        self.common_options.is_save_vocal_only = value

    @property
    def is_sec_bv_rebalance(self) -> bool:
        return self.common_options.is_sec_bv_rebalance

    @is_sec_bv_rebalance.setter
    def is_sec_bv_rebalance(self, value: bool) -> None:
        self.common_options.is_sec_bv_rebalance = value

    @property
    def is_secondary_model(self) -> bool:
        return self.common_options.is_secondary_model

    @is_secondary_model.setter
    def is_secondary_model(self, value: bool) -> None:
        self.common_options.is_secondary_model = value

    @property
    def is_vocal_split_model(self) -> bool:
        return self.common_options.is_vocal_split_model

    @is_vocal_split_model.setter
    def is_vocal_split_model(self, value: bool) -> None:
        self.common_options.is_vocal_split_model = value

    @property
    def model_hash_dir(self) -> str | None:
        return self.common_options.model_hash_dir

    @model_hash_dir.setter
    def model_hash_dir(self, value: str | None) -> None:
        self.common_options.model_hash_dir = value

    @property
    def secondary_model_bass(self) -> Any:
        return self.common_options.secondary_model_bass

    @secondary_model_bass.setter
    def secondary_model_bass(self, value: Any) -> None:
        self.common_options.secondary_model_bass = value

    @property
    def secondary_model_drums(self) -> Any:
        return self.common_options.secondary_model_drums

    @secondary_model_drums.setter
    def secondary_model_drums(self, value: Any) -> None:
        self.common_options.secondary_model_drums = value

    @property
    def secondary_model_other(self) -> Any:
        return self.common_options.secondary_model_other

    @secondary_model_other.setter
    def secondary_model_other(self, value: Any) -> None:
        self.common_options.secondary_model_other = value

    @property
    def secondary_model_scale_bass(self) -> float | None:
        return self.common_options.secondary_model_scale_bass

    @secondary_model_scale_bass.setter
    def secondary_model_scale_bass(self, value: float | None) -> None:
        self.common_options.secondary_model_scale_bass = value

    @property
    def secondary_model_scale_drums(self) -> float | None:
        return self.common_options.secondary_model_scale_drums

    @secondary_model_scale_drums.setter
    def secondary_model_scale_drums(self, value: float | None) -> None:
        self.common_options.secondary_model_scale_drums = value

    @property
    def secondary_model_scale_other(self) -> float | None:
        return self.common_options.secondary_model_scale_other

    @secondary_model_scale_other.setter
    def secondary_model_scale_other(self, value: float | None) -> None:
        self.common_options.secondary_model_scale_other = value

    @property
    def semitone_shift(self) -> float:
        return self.common_options.semitone_shift

    @semitone_shift.setter
    def semitone_shift(self, value: float) -> None:
        self.common_options.semitone_shift = value
