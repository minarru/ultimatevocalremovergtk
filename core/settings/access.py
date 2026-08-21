"""Typed-settings access helpers (nested paths and the legacy flat bridge).

Framework-agnostic: lives in ``core`` so noninteractive tools can write settings
without importing the GTK layer. ``ui.settings_bind`` re-exports these.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import difflib
from enum import Enum
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


def _setting_paths(settings: Settings) -> list[str]:
    return [
        f"{section_name}.{field.name}"
        for section_name in _section_names(settings)
        for field in fields(getattr(settings, section_name))
    ]


def validate_setting_path(
    settings: Settings, path: str, *, allow_containers: bool = False
) -> tuple[str, str]:
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
        matches = difflib.get_close_matches(path, _setting_paths(settings), n=5)
        suggestion = f"; close matches: {', '.join(matches)}" if matches else ""
        raise ValueError(
            f"unknown setting {path!r}; section {section_name!r} has no field "
            f"{field_name!r}{suggestion}"
        )

    if not allow_containers and isinstance(getattr(section, field_name), (list, dict)):
        raise ValueError(
            f"setting {path!r} is a container and cannot be set from a single value"
        )

    return section_name, field_name


def _container_mismatch(current: Any, value: Any) -> bool:
    """Whether ``value`` is the wrong shape for a container field.

    The container guard exists to stop a scalar -- ``--set foo=bar`` always
    yields a string -- from silently landing in a list or dict. A value that is
    itself the right kind of container is exactly what the field wants, so
    rejecting it made list settings unreachable from any programmatic caller.
    """
    if isinstance(current, list):
        return not isinstance(value, (list, tuple))
    if isinstance(current, dict):
        return not isinstance(value, dict)
    return False


def validate_setting_value(settings: Settings, path: str, value: Any) -> None:
    """Reject scalar values that permissive GUI migration coercion would hide."""
    section_name, field_name = validate_setting_path(
        settings, path, allow_containers=True
    )
    current_field = getattr(getattr(settings, section_name), field_name)
    if isinstance(current_field, (list, dict)):
        if _container_mismatch(current_field, value):
            raise ValueError(
                f"setting {path!r} is a container and cannot be set from a single value"
            )
        return
    if path == "ensemble.type":
        from bundled.constants import ENSEMBLE_ALGORITHMS

        atoms = [part.strip() for part in str(value).split("/")]
        if not atoms or any(atom not in ENSEMBLE_ALGORITHMS for atom in atoms):
            raise ValueError(
                f"invalid value for {path}: {value!r}; expected one or two known algorithms"
            )
        return
    if path == "process.stem_focus":
        from core.stems import normalize_stem_focus

        # Permissive coercion turns a typo into "export everything"; --set must
        # reject it instead. Empty is a valid clear.
        normalize_stem_focus(value, strict=bool(str(value).strip()))
        return
    current = getattr(getattr(settings, section_name), field_name)
    if isinstance(current, bool):
        valid = isinstance(value, bool) or value in (0, 1)
        if isinstance(value, str):
            valid = value.strip().lower() in {
                "0", "1", "false", "true", "no", "yes", "off", "on", "",
            }
        if not valid:
            raise ValueError(f"invalid boolean for {path}: {value!r}")
        return
    if isinstance(current, Enum):
        try:
            type(current)(value)
        except (TypeError, ValueError) as exc:
            allowed = ", ".join(repr(item.value) for item in type(current))
            raise ValueError(f"invalid value for {path}: {value!r}; expected {allowed}") from exc
        return
    if isinstance(current, int) and not isinstance(value, bool):
        try:
            int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid integer for {path}: {value!r}") from exc
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f"invalid integer for {path}: {value!r}")
        return
    if isinstance(current, float) and not isinstance(value, bool):
        try:
            float(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid number for {path}: {value!r}") from exc
        return
    if current is None:
        from core.settings.coerce import coerce_field

        converted = coerce_field(section_name, field_name, value)
        sentinels = {"", "auto", "default", "none", "null"}
        if converted is None and str(value).strip().lower() not in sentinels:
            raise ValueError(f"invalid value for {path}: {value!r}")


def apply_settings_overrides(
    settings: Settings, overrides: Iterable[tuple[str, Any]]
) -> None:
    """Apply validated ``(path, value)`` pairs in order (does not persist).

    Every path is validated before the first write, so a typo aborts the run
    instead of silently dropping the override.
    """
    pairs = list(overrides)
    for path, value in pairs:
        # Containers are gated on the value's shape by validate_setting_value,
        # not refused outright: a caller supplying a real list is legitimate.
        validate_setting_path(settings, path, allow_containers=True)
        validate_setting_value(settings, path, value)
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
