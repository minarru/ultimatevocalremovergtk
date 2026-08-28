"""Typed Demucs-specific model options."""

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass
class DemucsOptions:
    shifts: int = 0
    is_split_mode: bool = False
    segment: Any = None
    demucs_stems: Optional[str] = None
    is_demucs_combine_stems: bool = False
    demucs_source_list: Tuple[str, ...] = ()
    demucs_source_map: Any = None
    demucs_stem_count: int = 0
    demucs_version: Optional[str] = None
