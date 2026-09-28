"""Comparison sets for in-app listening: which tracks belong to one input.

Pure data built from :meth:`core.job_callbacks.JobCallbacks.input_finished`
reports. No GTK and no GStreamer; the UI's playback engine consumes these.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Sequence

from .job_plan import PlannedOutput
from .stems import ui_label

REFERENCE_LABEL = "Original"

_TRAILING_TAG = re.compile(r"\(([^()]+)\)\s*$")


@dataclass(frozen=True)
class Track:
    label: str
    path: str
    role: str | None = None
    is_reference: bool = False


@dataclass(frozen=True)
class ComparisonSet:
    source: str
    tracks: tuple[Track, ...]

    @property
    def name(self) -> str:
        return os.path.basename(self.source)


def _role_text(role: Any) -> str | None:
    if role is None:
        return None
    for attr in ("value", "tag"):
        text = getattr(role, attr, None)
        if isinstance(text, str) and text:
            return text
    return str(role)


def _filename_label(source: str, path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    tag = _TRAILING_TAG.search(stem)
    if tag:
        return tag.group(1).strip()
    base = os.path.splitext(os.path.basename(source))[0]
    stripped = stem.replace(base, "", 1).strip(" _-") if base else stem
    return stripped or stem


def build_comparison_set(
    source: str,
    reference: str | None,
    outputs: Sequence[str],
    planned: Sequence[PlannedOutput] = (),
) -> ComparisonSet | None:
    """Reference first, then each output once, in report order; ``None`` if no outputs."""
    by_path = {os.path.abspath(item.path): item for item in planned}
    tracks: list[Track] = []
    seen: set[str] = set()
    for path in outputs:
        key = os.path.abspath(path)
        if key in seen:
            continue
        seen.add(key)
        item = by_path.get(key)
        if item is not None:
            tracks.append(Track(ui_label(item.stem), path, _role_text(item.role)))
        else:
            tracks.append(Track(_filename_label(source, path), path))
    if not tracks:
        return None
    ref = Track(REFERENCE_LABEL, reference or source, None, True)
    return ComparisonSet(source, (ref, *tracks))


__all__ = ["REFERENCE_LABEL", "ComparisonSet", "Track", "build_comparison_set"]
