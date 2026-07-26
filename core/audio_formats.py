"""Shared audio file extensions used by pickers, drops and sample listing."""

from __future__ import annotations

import os
from typing import List, Sequence, Tuple

#: Lowercase extensions accepted as audio inputs when "Accept any input" is off.
AUDIO_EXTENSIONS: Tuple[str, ...] = (
    ".wav",
    ".flac",
    ".aiff",
    ".aif",
    ".ogg",
    ".mp3",
    ".m4a",
    ".aac",
    ".wma",
    ".opus",
)


def is_audio_filename(name: str) -> bool:
    """Return True when ``name`` ends with a known audio extension."""
    lowered = (name or "").lower()
    return any(lowered.endswith(ext) for ext in AUDIO_EXTENSIONS)


def expand_audio_paths(
    paths: Sequence[str],
    *,
    accept_any: bool = False,
) -> List[str]:
    """Expand directories into audio files; keep files that match the filter."""
    expanded: List[str] = []
    for path in paths:
        if not path:
            continue
        if os.path.isfile(path):
            if accept_any or is_audio_filename(path):
                expanded.append(path)
            continue
        if not os.path.isdir(path):
            continue
        try:
            entries = sorted(os.listdir(path))
        except OSError:
            continue
        for name in entries:
            full = os.path.join(path, name)
            if not os.path.isfile(full):
                continue
            if accept_any or is_audio_filename(full):
                expanded.append(full)
    return expanded
