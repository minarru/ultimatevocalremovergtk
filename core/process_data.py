"""Run payload passed into separation engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ProcessData:
    export_path: str
    audio_file_base: str
    audio_file: Any  # str | ndarray
    set_progress_bar: Callable
    write_to_console: Callable
    process_iteration: Callable
    check_run_control: Callable
    cached_source_callback: Callable
    cached_model_source_holder: dict
    list_all_models: list
    is_ensemble_master: bool = False
    is_4_stem_ensemble: bool = False
    capture_stems_only: bool = False
    is_save_all_outputs_ensemble: bool = False
