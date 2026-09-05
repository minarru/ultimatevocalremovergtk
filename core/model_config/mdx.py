"""Typed MDX / MDX-C-specific model options."""

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Tuple

from .base import StemRouting


@dataclass(init=False)
class MDXOptions:
    margin: int = 0
    chunks: int = 0
    mdx_segment_size: int = 0
    mdx_batch_size: int = 1
    mdxnet_stem_select: Optional[str] = None
    _mdxnet_stems_selected: list[str] = field(default_factory=list, repr=False)
    overlap_mdx: float = 0.25
    overlap_mdx23: int = 0
    is_mdx_ckpt: bool = False
    is_mdx_c: bool = False
    is_roformer: bool = False
    is_target_instrument: bool = False
    model_type: str = ""
    mdx_c_configs: Any = None
    routing: StemRouting = field(default_factory=StemRouting, repr=False)
    mdx_stem_count: int = 1
    compensate: Optional[float] = None
    mdx_dim_f_set: Optional[int] = None
    mdx_dim_t_set: Optional[int] = None
    mdx_n_fft_scale_set: Optional[int] = None

    is_mdx_c_seg_def: bool = False
    is_denoise: bool = False
    is_denoise_model: bool = False
    is_match_frequency_pitch: bool = False
    is_mdx_combine_stems: bool = False
    is_mdx_include_stem_complement: bool = False
    is_invert_spec: bool = False
    is_mixer_mode: bool = False
    mixer_path: str = ""
    mdx_config_yaml: str = ""
    mdx_config_sha256: str = ""
    mdx_hash_record_source: str = ""
    mdx_runtime_reconciliation: Any = None

    @property
    def mdx_model_stems(self) -> tuple[str, ...]:
        return self.routing.mdx_model_stems

    @mdx_model_stems.setter
    def mdx_model_stems(self, value: Sequence[str]) -> None:
        self.routing.mdx_model_stems = value

    def __init__(
        self,
        margin: int = 0,
        chunks: int = 0,
        mdx_segment_size: int = 0,
        mdx_batch_size: int = 1,
        mdxnet_stem_select: Optional[str] = None,
        mdxnet_stems_selected: Tuple[str, ...] = (),
        overlap_mdx: float = 0.25,
        overlap_mdx23: int = 0,
        is_mdx_ckpt: bool = False,
        is_mdx_c: bool = False,
        is_roformer: bool = False,
        is_target_instrument: bool = False,
        model_type: str = '',
        mdx_c_configs: Any = None,
        mdx_model_stems: Sequence[str] | None = None,
        mdx_stem_count: int = 1,
        compensate: Optional[float] = None,
        mdx_dim_f_set: Optional[int] = None,
        mdx_dim_t_set: Optional[int] = None,
        mdx_n_fft_scale_set: Optional[int] = None,
        is_mdx_c_seg_def: bool = False,
        is_denoise: bool = False,
        is_denoise_model: bool = False,
        is_match_frequency_pitch: bool = False,
        is_mdx_combine_stems: bool = False,
        is_mdx_include_stem_complement: bool = False,
        is_invert_spec: bool = False,
        is_mixer_mode: bool = False,
        mixer_path: str = '',
        mdx_config_yaml: str = '',
        mdx_config_sha256: str = '',
        mdx_hash_record_source: str = '',
        mdx_runtime_reconciliation: Any = None,
        *,
        routing: StemRouting | None = None,
    ) -> None:
        self.margin = margin
        self.chunks = chunks
        self.mdx_segment_size = mdx_segment_size
        self.mdx_batch_size = mdx_batch_size
        self.mdxnet_stem_select = mdxnet_stem_select
        self.mdxnet_stems_selected = mdxnet_stems_selected
        self.overlap_mdx = overlap_mdx
        self.overlap_mdx23 = overlap_mdx23
        self.is_mdx_ckpt = is_mdx_ckpt
        self.is_mdx_c = is_mdx_c
        self.is_roformer = is_roformer
        self.is_target_instrument = is_target_instrument
        self.model_type = model_type
        self.mdx_c_configs = mdx_c_configs
        self.routing = routing if routing is not None else StemRouting()
        if mdx_model_stems is not None:
            self.mdx_model_stems = mdx_model_stems
        self.mdx_stem_count = mdx_stem_count
        self.compensate = compensate
        self.mdx_dim_f_set = mdx_dim_f_set
        self.mdx_dim_t_set = mdx_dim_t_set
        self.mdx_n_fft_scale_set = mdx_n_fft_scale_set
        self.is_mdx_c_seg_def = is_mdx_c_seg_def
        self.is_denoise = is_denoise
        self.is_denoise_model = is_denoise_model
        self.is_match_frequency_pitch = is_match_frequency_pitch
        self.is_mdx_combine_stems = is_mdx_combine_stems
        self.is_mdx_include_stem_complement = is_mdx_include_stem_complement
        self.is_invert_spec = is_invert_spec
        self.is_mixer_mode = is_mixer_mode
        self.mixer_path = mixer_path
        self.mdx_config_yaml = mdx_config_yaml
        self.mdx_config_sha256 = mdx_config_sha256
        self.mdx_hash_record_source = mdx_hash_record_source
        self.mdx_runtime_reconciliation = mdx_runtime_reconciliation

    @property
    def mdxnet_stems_selected(self) -> Tuple[str, ...]:
        return tuple(self._mdxnet_stems_selected)

    @mdxnet_stems_selected.setter
    def mdxnet_stems_selected(self, value: Sequence[str]) -> None:
        self._mdxnet_stems_selected = list(value)
