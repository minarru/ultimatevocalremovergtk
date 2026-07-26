"""Cross-tab file, output and format options synced from :class:`~core.SettingsModel`.

Input paths, the export folder, output format, GPU conversion and sample mode
are shared across the Separation, Ensemble and Audio Tools surfaces. Call
:func:`apply_shared_file_options` when a tab becomes active so widgets reflect
the latest in-memory settings without writing spurious changes back.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import AbstractSet, Iterable, Optional, Protocol, Sequence

from bundled.constants import WAV

from .widgets.rows import set_combo_value

INPUT_FILES_WARN = 100
INPUT_FILES_MAX = 500

#: Stable title for the sample-mode switch row (the duration lives in the
#: subtitle so the title stays constant for scanability and screen readers).
SAMPLE_MODE_TITLE = "Sample mode"


def sample_mode_subtitle(duration: int) -> str:
    """Subtitle describing how much audio sample mode processes."""
    return f"Process only the first {int(duration)} s"


def apply_sample_mode_label(sample_row, duration: int) -> None:
    """Set the stable title + duration subtitle on a sample-mode switch row."""
    sample_row.set_title(SAMPLE_MODE_TITLE)
    if hasattr(sample_row, "set_subtitle"):
        sample_row.set_subtitle(sample_mode_subtitle(duration))

_REASON_OUTPUT_MISSING = "Choose an output folder"
_REASON_OUTPUT_STALE = "Output folder no longer exists — select a new folder"
_REASON_OUTPUT_READONLY = "Output folder is not writable — choose another folder"
_REASON_INPUT_MISSING = "Select an input audio file"
_REASON_UNREADABLE_INPUTS = "Remove unreadable inputs"


@dataclass(frozen=True)
class InputSanitizeResult:
    removed_missing: int = 0
    truncated_count: int = 0
    large_batch: bool = False


def export_path_blocked_reason(path: str) -> Optional[str]:
    """Return a start-blocking message for ``path``, or ``None`` when export is ready."""
    path = (path or "").strip()
    if not path:
        return _REASON_OUTPUT_MISSING
    if not os.path.isdir(path):
        return _REASON_OUTPUT_STALE
    if not os.access(path, os.W_OK):
        return _REASON_OUTPUT_READONLY
    return None


def export_path_is_valid(path: str) -> bool:
    return export_path_blocked_reason(path) is None


def partition_input_paths(paths: Sequence[str]) -> tuple[list[str], list[str]]:
    """Return ``(existing_files, missing_paths)`` in original order, deduped."""
    existing: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = (raw or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            existing.append(path)
        else:
            missing.append(path)
    return existing, missing


def sanitize_input_paths(
    paths: Sequence[str],
    *,
    max_files: int = INPUT_FILES_MAX,
) -> tuple[list[str], InputSanitizeResult]:
    """Dedupe, drop missing files, and enforce the selection cap."""
    existing, missing = partition_input_paths(paths)
    removed_missing = len(missing)
    truncated_count = 0
    if len(existing) > max_files:
        truncated_count = len(existing) - max_files
        existing = existing[:max_files]
    large_batch = len(existing) >= INPUT_FILES_WARN
    return existing, InputSanitizeResult(
        removed_missing=removed_missing,
        truncated_count=truncated_count,
        large_batch=large_batch,
    )


def prune_unreadable_paths(
    unreadable: AbstractSet[str],
    current_paths: Sequence[str],
) -> set[str]:
    """Keep only unreadable paths that are still in the current selection."""
    current = {p for p in current_paths if p}
    return {p for p in unreadable if p in current}


def remove_unreadable_from_paths(
    paths: Sequence[str],
    unreadable: AbstractSet[str],
) -> list[str]:
    """Drop paths that are marked unreadable, preserving order."""
    if not unreadable:
        return list(paths)
    return [p for p in paths if p and p not in unreadable]


def input_paths_blocked_reason(
    paths: Sequence[str],
    *,
    unreadable_paths: Optional[AbstractSet[str]] = None,
) -> Optional[str]:
    """Return a start-blocking message, or ``None`` when inputs are ready.

    Never-verified selections only require at least one existing file. After
    Verify Inputs marks failures, Start stays blocked while any failed path
    remains in the selection.
    """
    if not paths:
        return _REASON_INPUT_MISSING
    existing = False
    for path in paths:
        if not path:
            continue
        if unreadable_paths and path in unreadable_paths:
            return _REASON_UNREADABLE_INPUTS
        if os.path.isfile(path):
            existing = True
    if not existing:
        return _REASON_INPUT_MISSING
    return None


def format_input_sanitize_toasts(
    result: InputSanitizeResult,
    *,
    include_missing: bool = False,
    include_large_batch: bool = True,
) -> list[str]:
    """Build user-facing toast messages from a sanitize result."""
    messages: list[str] = []
    if include_missing and result.removed_missing:
        count = result.removed_missing
        noun = "file" if count == 1 else "files"
        messages.append(f"Removed {count} saved input {noun} that no longer exist")
    if result.truncated_count:
        messages.append(f"Only the first {INPUT_FILES_MAX} files were added")
    if include_large_batch and result.large_batch:
        messages.append("100+ input files selected — processing may take a long time")
    return messages


class _InputPathsRow(Protocol):
    def set_paths(self, paths: Sequence[str], notify: bool = ...) -> None: ...


class _OutputPathRow(Protocol):
    def set_path(self, path: str, notify: bool = ...) -> None: ...


class _SwitchRow(Protocol):
    def set_active(self, active: bool) -> None: ...


class _SampleModeRow(Protocol):
    def set_title(self, title: str) -> None: ...

    def set_subtitle(self, subtitle: str) -> None: ...

    def set_active(self, active: bool) -> None: ...


@dataclass(frozen=True)
class SharedFileOptions:
    input_paths: list[str]
    export_path: str
    save_format: str
    is_gpu_conversion: bool
    is_autocast: bool
    sample_duration: int
    model_sample_mode: bool


def read_shared_file_options(settings) -> SharedFileOptions:
    """Read the keys every mode page shares from ``settings``."""
    return SharedFileOptions(
        input_paths=list(settings.get("input_paths") or []),
        export_path=settings.get("export_path") or "",
        save_format=settings.get("save_format", WAV),
        is_gpu_conversion=bool(settings.get("is_gpu_conversion")),
        is_autocast=bool(settings.get("is_autocast")),
        sample_duration=int(settings.get("model_sample_mode_duration", 30) or 30),
        model_sample_mode=bool(settings.get("model_sample_mode")),
    )


def apply_shared_file_options(
    settings,
    *,
    input_row: Optional[_InputPathsRow] = None,
    input_rows: Optional[Iterable[_InputPathsRow]] = None,
    output_row: Optional[_OutputPathRow] = None,
    format_row=None,
    gpu_row: Optional[_SwitchRow] = None,
    autocast_row: Optional[_SwitchRow] = None,
    sample_row: Optional[_SampleModeRow] = None,
) -> SharedFileOptions:
    """Push shared settings values into the supplied option rows."""
    options = read_shared_file_options(settings)
    cleaned, _result = sanitize_input_paths(options.input_paths)
    if cleaned != options.input_paths:
        settings.set("input_paths", cleaned)
        options = replace(options, input_paths=cleaned)

    rows: list[_InputPathsRow] = []
    if input_row is not None:
        rows.append(input_row)
    if input_rows is not None:
        rows.extend(input_rows)

    for row in rows:
        row.set_paths(options.input_paths, notify=False)

    if output_row is not None:
        output_row.set_path(options.export_path, notify=False)
    if format_row is not None:
        set_combo_value(format_row, options.save_format)
    if gpu_row is not None:
        gpu_row.set_active(options.is_gpu_conversion)
    if autocast_row is not None:
        autocast_row.set_active(options.is_autocast)
    if sample_row is not None:
        apply_sample_mode_label(sample_row, options.sample_duration)
        sample_row.set_active(options.model_sample_mode)

    return options
