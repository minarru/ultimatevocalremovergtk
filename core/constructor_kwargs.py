"""Signature facts shared by model construction and offline probe reporting."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConstructorKwargs:
    accepted: dict[Any, Any]
    # Raw encounter order preserves runtime support for mixed-key mappings.
    # Consumers own presentation: the probe historically sorts raw keys.
    dropped: tuple[Any, ...]


def analyze_constructor_kwargs(model_cls: Any, cfg: Any) -> ConstructorKwargs:
    """Retain signature names without constructing, coercing or binding values.

    Positional-only names intentionally remain accepted, matching the runtime's
    compatibility filter. Only accepted values are read from strict mappings.
    """
    params = inspect.signature(model_cls.__init__).parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return ConstructorKwargs(dict(cfg), ())
    allowed = {name for name in params if name != "self"}
    accepted = {}
    dropped = []
    for key in cfg:
        if key in allowed:
            accepted[key] = cfg[key]
        else:
            dropped.append(key)
    return ConstructorKwargs(accepted, tuple(dropped))
