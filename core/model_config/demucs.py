"""Typed Demucs-specific model options."""

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .base import StemRouting


@dataclass(init=False)
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

    def __init__(
        self,
        shifts: int = 0,
        is_split_mode: bool = False,
        segment: Any = None,
        demucs_stems: Optional[str] = None,
        is_demucs_combine_stems: bool = False,
        demucs_source_list: Sequence[str] | None = None,
        demucs_source_map: Any = None,
        demucs_stem_count: int = 0,
        demucs_version: Optional[str] = None,
        overlap: float = 0.0,
        is_demucs_pre_proc_model_inst_mix: bool = False,
        *,
        routing: StemRouting | None = None,
    ) -> None:
        self.shifts = shifts
        self.is_split_mode = is_split_mode
        self.segment = segment
        self.demucs_stems = demucs_stems
        self.is_demucs_combine_stems = is_demucs_combine_stems
        self.routing = routing if routing is not None else StemRouting()
        if demucs_source_list is not None:
            self.demucs_source_list = demucs_source_list
        self.demucs_source_map = demucs_source_map
        self.demucs_stem_count = demucs_stem_count
        self.demucs_version = demucs_version
        self.overlap = overlap
        self.is_demucs_pre_proc_model_inst_mix = is_demucs_pre_proc_model_inst_mix

    @property
    def demucs_source_list(self) -> tuple[str, ...]:
        return self.routing.demucs_source_list

    @demucs_source_list.setter
    def demucs_source_list(self, value: Sequence[str]) -> None:
        self.routing.demucs_source_list = value
