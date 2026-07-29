"""Trusted checkpoint loading compatible with PyTorch 2.6+."""

from __future__ import annotations
import typing

import importlib
import sys
import types
from typing import Any, Mapping

import torch

_DEMUCS_ALIASES_INSTALLED = False
_OPTIONAL_STUBS_INSTALLED = False


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

# Training checkpoints (e.g. Huge SCNet) may pickle optimizer classes from
# optional packages that are never needed for inference. Stub them so
# ``torch.load`` can recover ``model_state_dict`` without installing those deps.
_OPTIONAL_STUB_MODULES = (
    "bitsandbytes",
    "bitsandbytes.optim",
    "bitsandbytes.optim.adamw",
)


class _UnpickleStub:
    """Minimal stand-in for training-only classes referenced in checkpoints."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def __setstate__(self, state: Any) -> None:
        if isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self.state = state


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


def ensure_optional_checkpoint_stubs() -> None:
    """Install lightweight stubs for optional packages pickled in some ckpts."""
    global _OPTIONAL_STUBS_INSTALLED
    if _OPTIONAL_STUBS_INSTALLED:
        return

    try:
        importlib.import_module("bitsandbytes.optim.adamw")
    except ImportError:
        for name in _OPTIONAL_STUB_MODULES:
            if name in sys.modules:
                continue
            module = types.ModuleType(name)
            sys.modules[name] = module
        adamw: Any = sys.modules["bitsandbytes.optim.adamw"]
        if not hasattr(adamw, "AdamW8bit"):
            adamw.AdamW8bit = type("AdamW8bit", (_UnpickleStub,), {})
        optim: Any = sys.modules["bitsandbytes.optim"]
        if not hasattr(optim, "adamw"):
            optim.adamw = adamw
        root: Any = sys.modules["bitsandbytes"]
        if not hasattr(root, "optim"):
            root.optim = optim

    _OPTIONAL_STUBS_INSTALLED = True


def _looks_like_state_dict(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    for sample in value.values():
        return hasattr(sample, "shape") and hasattr(sample, "dtype")
    return False


def as_model_state_dict(obj: Any) -> Any:
    """Unwrap common training-checkpoint envelopes to a weight state dict.

    Returns ``obj`` unchanged when it is already a state dict (or not a
    recognised training package). Callers that need the full envelope (Apollo,
    Demucs packages) should keep using :func:`load_torch_checkpoint` alone.
    """
    if not isinstance(obj, Mapping):
        return obj
    for key in ("model_state_dict", "state_dict", "model"):
        nested = obj.get(key)
        if _looks_like_state_dict(nested):
            return nested
    return obj


def load_torch_checkpoint(path: typing.Any, map_location: Any = "cpu", **kwargs: typing.Any):
    """Load a trusted UVR/Demucs/VR checkpoint.

    PyTorch 2.6+ defaults ``weights_only=True``, which rejects pickled model
    classes (e.g. ``demucs.hdemucs.HDemucs``). UVR checkpoints are user-supplied
    trusted weights, so we always request full unpickling when supported.
    """
    ensure_demucs_import_aliases()
    ensure_optional_checkpoint_stubs()
    load_kwargs = dict(kwargs)
    load_kwargs.setdefault("map_location", map_location)
    try:
        load_kwargs["weights_only"] = False
        return torch.load(path, **load_kwargs)
    except TypeError:
        load_kwargs.pop("weights_only", None)
        return torch.load(path, **load_kwargs)
