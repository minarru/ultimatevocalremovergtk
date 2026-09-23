"""Settings fields command operations."""

from __future__ import annotations

import dataclasses

from core.settings import Settings


def setting_paths() -> list[str]:
    settings = Settings.defaults()
    result = []
    for section in ("process", "vr", "mdx", "demucs", "ensemble", "audio_tools", "ui"):
        result.extend(
            f"{section}.{field.name}" for field in dataclasses.fields(getattr(settings, section))
        )
    return sorted(result)
