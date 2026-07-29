"""Typed VR-specific model options."""

from dataclasses import dataclass
from typing import Any, Tuple


@dataclass
class VROptions:
    aggression_setting: float = 0.0
    is_tta: bool = False
    is_post_process: bool = False
    window_size: int = 0
    batch_size: int = 1
    crop_size: int = 0
    is_high_end_process: str = "None"
    post_process_threshold: float = 0.0
    model_capacity: Tuple[int, int] = (32, 128)
    model_samplerate: int = 44100
    vr_model_param: Any = None
    is_vr_51_model: bool = False
