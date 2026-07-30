"""Typed Demucs-specific model options."""

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass
class DemucsOptions:
    margin_demucs: int = 0
    chunks_demucs: int = 0
    shifts: int = 0
    is_split_mode: bool = False
    segment: Any = None
    is_chunk_demucs: bool = False
    demucs_stems: Optional[str] = None
    is_demucs_combine_stems: bool = False
    demucs_source_list: Tuple[str, ...] = ()
    demucs_source_map: Any = None
    demucs_stem_count: int = 0
    demucs_version: Optional[str] = None
