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

__all__ = [
    "ModelConfig",
    "assemble_model",
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
