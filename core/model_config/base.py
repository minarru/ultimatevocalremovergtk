"""Typed option groups shared by every assembled model configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Tuple


@dataclass
class ModelIdentity:
    model_name: str = ""
    process_method: str = ""
    model_path: Optional[str] = None
    model_basename: Optional[str] = None
    model_hash: Optional[str] = None
    model_status: bool = False
    model_and_process_tag: Optional[str] = None


@dataclass
class ExportOptions:
    wav_type_set: Any = None
    mp3_bit_set: str = ""
    flac_bit_set: str = "16-bit"
    save_format: str = ""
    is_normalization: bool = False
    is_match_mix_level: bool = False
    is_prevent_export_clipping: bool = False
    amplification_threshold: float = 0.0


@dataclass
class DeviceOptions:
    use_gpu: bool = False
    device_set: str = ""
    is_use_directml: bool = False


@dataclass
class EnsembleMemberFlags:
    is_ensemble_mode: bool = False
    is_4_stem_ensemble: bool = False
    is_multi_stem_ensemble: bool = False
    ensemble_primary_stem: Optional[str] = None
    ensemble_secondary_stem: Optional[str] = None


@dataclass
class StemRouting:
    """Native yaml/hash stem keys and exclusive-export flags.

    ``primary_stem`` / ``secondary_stem`` / ``primary_stem_native`` keep the
    checkpoint spelling. They are never rewritten to ``lead_only`` or UVR
    Title Case. Filenames and exclusive picks use :func:`stem_concept`.
    """

    primary_stem: Optional[str] = None
    secondary_stem: Optional[str] = None
    primary_stem_native: Optional[str] = None
    primary_model_primary_stem: Optional[str] = None
    is_primary_stem_only: bool = False
    is_secondary_stem_only: bool = False
    mdx_model_stems: Tuple[str, ...] = ()
    demucs_source_list: Tuple[str, ...] = ()


@dataclass
class SecondaryChain:
    """Resolved auxiliary models in their execution/construction order."""

    secondary_model: Any = None
    secondary_model_scale: Optional[float] = None
    secondary_model_4_stem: Tuple[Any, ...] = field(default_factory=tuple)
    secondary_model_4_stem_scale: Tuple[Optional[float], ...] = field(
        default_factory=tuple
    )
    pre_proc_model: Any = None
    vocal_split_model: Any = None
    is_secondary_model_activated: bool = False
    pre_proc_model_activated: bool = False
    is_vocal_split_model_activated: bool = False
