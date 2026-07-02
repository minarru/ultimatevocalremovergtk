"""Cross-tab file, output and format options synced from :class:`~uvr_core.SettingsModel`.

Input paths, the export folder, output format, GPU conversion and sample mode
are shared across the Separation, Ensemble and Audio Tools surfaces. Call
:func:`apply_shared_file_options` when a tab becomes active so widgets reflect
the latest in-memory settings without writing spurious changes back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Protocol, Sequence

from data.constants import SAMPLE_MODE_CHECKBOX, WAV

from .widgets.rows import set_combo_value


class _InputPathsRow(Protocol):
    def set_paths(self, paths: Sequence[str], notify: bool = ...) -> None: ...


class _OutputPathRow(Protocol):
    def set_path(self, path: str, notify: bool = ...) -> None: ...


class _SwitchRow(Protocol):
    def set_active(self, active: bool) -> None: ...


class _SampleModeRow(Protocol):
    def set_title(self, title: str) -> None: ...

    def set_active(self, active: bool) -> None: ...


@dataclass(frozen=True)
class SharedFileOptions:
    input_paths: list[str]
    export_path: str
    save_format: str
    is_gpu_conversion: bool
    sample_duration: int
    model_sample_mode: bool


def read_shared_file_options(settings) -> SharedFileOptions:
    """Read the keys every mode page shares from ``settings``."""
    return SharedFileOptions(
        input_paths=list(settings.get("input_paths") or []),
        export_path=settings.get("export_path") or "",
        save_format=settings.get("save_format", WAV),
        is_gpu_conversion=bool(settings.get("is_gpu_conversion")),
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
    sample_row: Optional[_SampleModeRow] = None,
) -> SharedFileOptions:
    """Push shared settings values into the supplied option rows."""
    options = read_shared_file_options(settings)

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
    if sample_row is not None:
        sample_row.set_title(SAMPLE_MODE_CHECKBOX(options.sample_duration))
        sample_row.set_active(options.model_sample_mode)

    return options
