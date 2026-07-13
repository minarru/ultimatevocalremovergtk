"""Trusted checkpoint loading compatible with PyTorch 2.6+."""

from __future__ import annotations

import importlib
import sys
from typing import Any

import torch

_DEMUCS_ALIASES_INSTALLED = False


_DEMUCS_ALIAS_SUBMODULES = (
    "apply",
    "demucs",
    "filtering",
    "hdemucs",
    "htdemucs",
    "model",
    "model_v2",
    "pretrained",
    "repo",
    "spec",
    "states",
    "tasnet",
    "tasnet_v2",
    "transformer",
    "utils",
)


def ensure_demucs_import_aliases() -> None:
    """Map ``demucs.*`` imports to the vendored ``vendor.demucs`` package.

    Official Demucs checkpoints pickle class paths like ``demucs.hdemucs.HDemucs``.
    This app vendors Demucs under ``vendor.demucs``, so unpickling needs those
    legacy module names to resolve before ``torch.load`` runs.
    """
    global _DEMUCS_ALIASES_INSTALLED
    if _DEMUCS_ALIASES_INSTALLED:
        return

    root = importlib.import_module("vendor.demucs")
    sys.modules.setdefault("demucs", root)
    for sub in _DEMUCS_ALIAS_SUBMODULES:
        full_name = f"vendor.demucs.{sub}"
        alias = f"demucs.{sub}"
        if alias in sys.modules:
            continue
        try:
            sys.modules[alias] = importlib.import_module(full_name)
        except ImportError:
            continue

    _DEMUCS_ALIASES_INSTALLED = True


def load_torch_checkpoint(path, map_location: Any = "cpu", **kwargs):
    """Load a trusted UVR/Demucs/VR checkpoint.

    PyTorch 2.6+ defaults ``weights_only=True``, which rejects pickled model
    classes (e.g. ``demucs.hdemucs.HDemucs``). UVR checkpoints are user-supplied
    trusted weights, so we always request full unpickling when supported.
    """
    ensure_demucs_import_aliases()
    load_kwargs = dict(kwargs)
    load_kwargs.setdefault("map_location", map_location)
    try:
        load_kwargs["weights_only"] = False
        return torch.load(path, **load_kwargs)
    except TypeError:
        load_kwargs.pop("weights_only", None)
        return torch.load(path, **load_kwargs)
