"""Typed MDX / MDX-C-specific model options."""

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass
class MDXOptions:
    margin: int = 0
    chunks: int = 0
    mdx_segment_size: int = 0
    mdx_batch_size: int = 1
    mdxnet_stem_select: Optional[str] = None
    mdxnet_stems_selected: Tuple[str, ...] = ()
    overlap_mdx: float = 0.25
    overlap_mdx23: int = 0
    is_mdx_ckpt: bool = False
    is_mdx_c: bool = False
    is_roformer: bool = False
    is_target_instrument: bool = False
    model_type: str = ""
    mdx_c_configs: Any = None
    mdx_model_stems: Tuple[str, ...] = ()
    mdx_stem_count: int = 1
    compensate: Optional[float] = None
    mdx_dim_f_set: Optional[int] = None
    mdx_dim_t_set: Optional[int] = None
    mdx_n_fft_scale_set: Optional[int] = None
