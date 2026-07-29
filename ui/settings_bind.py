"""Small typed-settings access helpers for dynamic UI bindings."""

from __future__ import annotations

from typing import Any

from core.settings import Settings
from core.settings.coerce import coerce_field
from core.settings.flat_map import FLAT_TO_PATH

_MISSING = object()


def get_path(settings: Settings, path: str, default: Any = _MISSING) -> Any:
    """Read a ``section.field`` path from nested :class:`Settings`."""
    try:
        section_name, field_name = path.split(".", 1)
        return getattr(getattr(settings, section_name), field_name)
    except (AttributeError, ValueError):
        if default is _MISSING:
            raise
        return default


def set_path(settings: Settings, path: str, value: Any) -> None:
    """Write a ``section.field`` path on nested :class:`Settings`."""
    section_name, field_name = path.split(".", 1)
    setattr(
        getattr(settings, section_name),
        field_name,
        coerce_field(section_name, field_name, value),
    )


def get_flat(settings: Settings, key: str, default: Any = None) -> Any:
    """Read a legacy flat key through :data:`FLAT_TO_PATH`."""
    path = FLAT_TO_PATH.get(key)
    if path is None:
        return default
    return get_path(settings, ".".join(path), default)


def set_flat(settings: Settings, key: str, value: Any) -> None:
    """Write a legacy flat key through :data:`FLAT_TO_PATH`."""
    path = FLAT_TO_PATH.get(key)
    if path is not None:
        set_path(settings, ".".join(path), value)
