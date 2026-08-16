"""Central output filename formatting for separation, ensemble, and tools.

Pattern (built from settings toggles):

    [timestamp ][{index}-{track}|{track}][ {model}][ {ensemble}] ({stem})

Multi-file index uses a hyphen (``1-song``); other segments use spaces.
Stem labels stay human-readable inside parentheses.
"""

from __future__ import annotations

import dataclasses
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

from bundled.constants import WAV
from .settings import Settings

# Characters unsafe in a single path component on common platforms.
_UNSAFE = re.compile(r'[/\\:\0<>"|?*]')
_MULTI_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class OutputNamingContext:
    """All stable inputs used to construct one track's output basename."""

    input_path: str
    track: str
    track_base: str
    export_directory: str
    extension: str
    file_index: int | None = None
    file_total: int = 1
    model_label: str | None = None
    ensemble_label: str | None = None
    timestamp: str | None = None


def build_output_naming_context(
    settings: Settings,
    input_path: str,
    *,
    export_path: str,
    file_index: int | None = None,
    file_total: int = 1,
    model_label: str | None = None,
    ensemble_label: str | None = None,
    force_model_label: bool = False,
    force_ensemble_label: bool = False,
) -> OutputNamingContext:
    track = track_basename_from_path(input_path)
    timestamp = testing_timestamp_prefix(settings)
    track_base = format_track_base(
        track=track,
        model=model_label if settings.process.add_model_name or force_model_label else None,
        ensemble=(
            ensemble_label
            if settings.process.add_model_name or force_ensemble_label
            else None
        ),
        file_index=file_index,
        file_total=file_total,
        timestamp=timestamp,
    )
    directory = export_path
    if settings.process.create_model_folder and model_label:
        directory = os.path.join(
            export_path, sanitize_filename_component(model_label), track
        )
    extension = str(getattr(settings.process.save_format, "value", "wav") or "wav").lower()
    return OutputNamingContext(
        input_path=input_path,
        track=track,
        track_base=track_base,
        export_directory=directory,
        extension=extension,
        file_index=file_index,
        file_total=file_total,
        model_label=model_label,
        ensemble_label=ensemble_label,
        timestamp=timestamp,
    )


def rebase_output_naming(
    naming: OutputNamingContext,
    export_path: str,
    planned_output_root: str,
) -> OutputNamingContext:
    """Keep track_base / labels; rewrite export_directory under export_path."""
    root = os.path.abspath(planned_output_root)
    current = os.path.abspath(naming.export_directory)
    rel = os.path.relpath(current, root)
    if rel.startswith(".."):
        raise ValueError(
            f"planned export {naming.export_directory!r} is not under {planned_output_root!r}"
        )
    directory = os.path.abspath(export_path) if rel == "." else os.path.join(export_path, rel)
    return dataclasses.replace(naming, export_directory=directory)


def sanitize_filename_component(text: str | None) -> str:
    """Sanitize one filename segment while keeping spaces and stem punctuation.

    ``None`` is accepted and returns ``""`` — call sites feed it untyped stem
    and model labels, and rely on the ``... or "audio"`` fallback downstream.
    """
    if text is None:
        return ""
    cleaned = _UNSAFE.sub(" ", str(text))
    cleaned = cleaned.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    cleaned = _MULTI_SPACE.sub(" ", cleaned).strip(" .")
    return cleaned


def ensemble_name_for_export(chosen: str | None) -> str:
    """Map ``chosen_ensemble`` to the export label used by planning and Ensembler.

    The GUI sentinel ``CHOOSE_ENSEMBLE_OPTION`` ('Choose Option') becomes
    ``"Ensembled"``, matching ad-hoc ensembles that never pick a saved name.
    """
    from bundled.constants import CHOOSE_ENSEMBLE_OPTION

    if chosen and chosen != CHOOSE_ENSEMBLE_OPTION:
        return sanitize_filename_component(chosen) or "Ensembled"
    return "Ensembled"


def format_track_base(
    *,
    track: str,
    model: Optional[str] = None,
    file_index: Optional[int] = None,
    file_total: int = 1,
    timestamp: Optional[str] = None,
    ensemble: Optional[str] = None,
) -> str:
    """Build the basename before `` ({stem})``."""
    track_part = sanitize_filename_component(track) or "audio"
    if file_total > 1 and file_index is not None:
        head = f"{int(file_index)}-{track_part}"
    else:
        head = track_part

    parts: list[str] = []
    if timestamp:
        parts.append(sanitize_filename_component(str(timestamp)))
    parts.append(head)
    if model:
        model_part = sanitize_filename_component(model)
        if model_part:
            parts.append(model_part)
    if ensemble:
        ens_part = sanitize_filename_component(ensemble)
        if ens_part:
            parts.append(ens_part)
    return " ".join(p for p in parts if p)


def format_stem_basename(track_base: str, stem: str) -> str:
    """``{track_base} ({stem})`` with a sanitized human-readable stem label."""
    base = (track_base or "").rstrip()
    stem_part = sanitize_filename_component(stem) or "Stem"
    if not base:
        return f"({stem_part})"
    return f"{base} ({stem_part})"


def stem_wav_path(export_path: str, track_base: str, stem: str) -> str:
    """Absolute ``.wav`` path for a stem under ``export_path``."""
    return os.path.join(export_path, f"{format_stem_basename(track_base, stem)}.wav")


def testing_timestamp_prefix(settings: Settings) -> Optional[str]:
    """Return a timestamp string when Settings test mode is on, else ``None``."""
    if not settings.process.testing_audio:
        return None
    return str(round(time.time()))


def track_basename_from_path(audio_file: str) -> str:
    """Input path → sanitized track title (no extension)."""
    return sanitize_filename_component(os.path.splitext(os.path.basename(audio_file))[0]) or "audio"


def preview_output_name(settings: Settings, *, multi_file: bool = False) -> str:
    """Example filename for Preferences, reflecting current naming toggles."""
    track = "song"
    stem = "Vocals"
    model = None
    if settings.process.add_model_name:
        model = "UVR-MDX-Net"
    timestamp = "1710000000" if settings.process.testing_audio else None
    file_total = 2 if multi_file else 1
    file_index = 1 if multi_file else None
    base = format_track_base(
        track=track,
        model=model,
        file_index=file_index,
        file_total=file_total,
        timestamp=timestamp,
    )
    ext = (settings.process.save_format.value or WAV).lower()
    if ext == "wav":
        suffix = ".wav"
    elif ext == "flac":
        suffix = ".flac"
    elif ext == "mp3":
        suffix = ".mp3"
    else:
        suffix = f".{ext}" if ext else ".wav"
    return f"{format_stem_basename(base, stem)}{suffix}"
