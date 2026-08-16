"""Typed setting metadata shared by validation, help, and frontends."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .model import Settings


@dataclass(frozen=True)
class SettingDescriptor:
    path: str
    type_name: str
    default: Any
    allowed_values: tuple[Any, ...] | None
    supports_auto: bool
    model_behavior: str | None = None


_MODEL_BEHAVIOR = {
    "mdx.compensate": "auto uses checkpoint metadata compensation",
    "mdx.segment_size": "numeric override; model-default mode uses the YAML segment",
    "mdx.is_mdx_c_seg_def": "true selects the MDX-C YAML-native segment size",
    "demucs.segment": "auto uses the Demucs model's native segment",
}


def describe_setting(path: str) -> SettingDescriptor:
    defaults = Settings.defaults()
    section_name, field_name = path.split(".", 1)
    section = getattr(defaults, section_name)
    dataclass_field = next(
        item for item in dataclasses.fields(section) if item.name == field_name
    )
    value = getattr(section, field_name)
    value_type = type(value)
    allowed: tuple[Any, ...] | None = None
    if isinstance(value, Enum):
        allowed = tuple(item.value for item in value_type.__members__.values())
    elif value_type is bool:
        allowed = (True, False)
    return SettingDescriptor(
        path,
        str(dataclass_field.type),
        value.value if isinstance(value, Enum) else value,
        allowed,
        value is None,
        _MODEL_BEHAVIOR.get(path),
    )


def setting_descriptors() -> tuple[SettingDescriptor, ...]:
    settings = Settings.defaults()
    paths = (
        f"{section_name}.{item.name}"
        for section_name in ("process", "vr", "mdx", "demucs", "ensemble", "audio_tools", "ui")
        for item in dataclasses.fields(getattr(settings, section_name))
    )
    return tuple(describe_setting(path) for path in paths)
