"""Trusted checkpoint loading compatible with PyTorch 2.6+."""

from __future__ import annotations

from typing import Any

import torch


def load_torch_checkpoint(path, map_location: Any = "cpu", **kwargs):
    """Load a trusted UVR/Demucs/VR checkpoint.

    PyTorch 2.6+ defaults ``weights_only=True``, which rejects pickled model
    classes (e.g. ``demucs.hdemucs.HDemucs``). UVR checkpoints are user-supplied
    trusted weights, so we always request full unpickling when supported.
    """
    load_kwargs = dict(kwargs)
    load_kwargs.setdefault("map_location", map_location)
    try:
        load_kwargs["weights_only"] = False
        return torch.load(path, **load_kwargs)
    except TypeError:
        load_kwargs.pop("weights_only", None)
        return torch.load(path, **load_kwargs)
