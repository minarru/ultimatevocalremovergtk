"""Typed model configuration hierarchy and assembly API."""

from .base import (
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
from .config import ModelConfig
from .assemble import assemble_model
from .determine import (
    process_determine_demucs_pre_proc_model,
    process_determine_secondary_model,
    process_determine_vocal_split_model,
)

__all__ = [
    "ModelConfig",
    "assemble_model",
    "process_determine_demucs_pre_proc_model",
    "process_determine_secondary_model",
    "process_determine_vocal_split_model",
    "DeviceOptions",
    "EnsembleMemberFlags",
    "ExportOptions",
    "ModelIdentity",
    "SecondaryChain",
    "StemRouting",
    "DemucsOptions",
    "MDXOptions",
    "VROptions",
]
