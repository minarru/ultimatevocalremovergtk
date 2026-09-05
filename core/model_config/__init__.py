"""Typed model configuration hierarchy and assembly API."""

from .assemble import assemble_model
from .base import (
    DeviceOptions,
    EnsembleMemberFlags,
    ExportOptions,
    ModelIdentity,
    SecondaryChain,
    StemRouting,
)
from .config import ModelConfig
from .demucs import DemucsOptions
from .determine import (
    process_determine_demucs_pre_proc_model,
    process_determine_secondary_model,
    process_determine_vocal_split_model,
)
from .mdx import MDXOptions
from .vr import VROptions

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
