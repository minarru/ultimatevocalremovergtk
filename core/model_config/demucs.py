"""Typed Demucs-specific model options."""

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .base import StemRouting


@dataclass
class DemucsOptions:
    shifts: int = 0
    is_split_mode: bool = False
    segment: Any = None
    demucs_stems: Optional[str] = None
    is_demucs_combine_stems: bool = False
    routing: StemRouting = field(default_factory=StemRouting, repr=False)
    demucs_source_map: Any = None
    demucs_stem_count: int = 0
    demucs_version: Optional[str] = None

    overlap: float = 0.0
    is_demucs_pre_proc_model_inst_mix: bool = False

    @property
    def demucs_source_list(self) -> tuple[str, ...]:
        return self.routing.demucs_source_list

    @demucs_source_list.setter
    def demucs_source_list(self, value: Sequence[str]) -> None:
        self.routing.demucs_source_list = value
