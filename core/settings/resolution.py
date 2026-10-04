"""Environment setting overrides and processing configuration validation."""

from __future__ import annotations

import os

from .model import Settings


def apply_environment_overrides(settings: Settings) -> set[str]:
    changed: set[str] = set()
    if "UVR_AUTOCAST" in os.environ:
        value = os.environ["UVR_AUTOCAST"].strip().casefold()
        if value not in {"0", "1", "false", "true", "no", "yes", "off", "on"}:
            raise ValueError(
                "invalid UVR_AUTOCAST value; expected 0/1, false/true, no/yes, or off/on"
            )
        settings.process.autocast = value in {"1", "true", "yes", "on"}
        changed.add("process.autocast")
    return changed


def validate_processing_settings(settings: Settings) -> None:
    process = settings.process
    if process.sample_mode_duration <= 0:
        raise ValueError("sample duration must be greater than zero")
    if process.long_file_chunk_seconds < 0:
        raise ValueError("long-file chunk duration cannot be negative")
    if process.long_file_chunk_overlap_seconds < 0:
        raise ValueError("long-file chunk overlap cannot be negative")
    if (
        process.long_file_chunk_seconds > 0
        and process.long_file_chunk_overlap_seconds >= process.long_file_chunk_seconds
    ):
        raise ValueError("long-file chunk overlap must be smaller than the chunk duration")
    if settings.mdx.segment_size <= 0:
        raise ValueError("MDX segment size must be greater than zero")
