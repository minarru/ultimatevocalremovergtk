"""Typed-settings access helpers (nested paths and the legacy flat bridge).

Framework-agnostic: lives in ``core`` so headless tools can write settings
without importing the GTK layer. ``ui.settings_bind`` re-exports these.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Iterable

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


def _section_names(settings: Settings) -> list[str]:
    return sorted(
        f.name
        for f in fields(settings)
        if is_dataclass(getattr(settings, f.name, None))
    )


def validate_setting_path(settings: Settings, path: str) -> tuple[str, str]:
    """Split ``section.field`` and reject anything :class:`Settings` lacks.

    :func:`set_path` cannot do this itself: the settings sections are plain
    dataclasses without ``slots``, so ``setattr`` happily invents an unknown
    attribute instead of raising. Every caller that accepts a user-supplied
    path must come through here first.
    """
    section_name, sep, field_name = path.partition(".")
    if not sep or not section_name or not field_name:
        raise ValueError(f"invalid setting path {path!r}; expected 'section.field'")

    section = getattr(settings, section_name, None)
    if section is None or not is_dataclass(section):
        known = ", ".join(_section_names(settings))
        raise ValueError(
            f"unknown settings section {section_name!r}; known sections: {known}"
        )

    if field_name not in {f.name for f in fields(section)}:
        raise ValueError(
            f"unknown setting {path!r}; section {section_name!r} has no field "
            f"{field_name!r}"
        )

    if isinstance(getattr(section, field_name), (list, dict)):
        raise ValueError(
            f"setting {path!r} is a container and cannot be set from a single value"
        )

    return section_name, field_name


def apply_settings_overrides(
    settings: Settings, overrides: Iterable[tuple[str, Any]]
) -> None:
    """Apply validated ``(path, value)`` pairs in order (does not persist).

    Every path is validated before the first write, so a typo aborts the run
    instead of silently dropping the override.
    """
    pairs = list(overrides)
    for path, _value in pairs:
        validate_setting_path(settings, path)
    for path, value in pairs:
        set_path(settings, path, value)


def parse_setting_assignment(text: str) -> tuple[str, str]:
    """Parse one ``section.field=value`` token into a ``(path, value)`` pair."""
    path, sep, value = str(text).partition("=")
    path = path.strip()
    if not sep or not path:
        raise ValueError(
            f"invalid setting override {text!r}; expected section.field=value"
        )
    return path, value
