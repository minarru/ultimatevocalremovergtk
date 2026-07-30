"""Run payload passed into separation engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Protocol

if TYPE_CHECKING:
    import numpy as np

    type AudioFile = str | np.ndarray[Any, Any]
else:
    type AudioFile = Any


class ProgressCallback(Protocol):
    def __call__(
        self, step: float, inference_iterations: float = 0.0
    ) -> Any: ...


class ConsoleCallback(Protocol):
    def __call__(self, text: str, base_text: str = "") -> Any: ...


class CachedSourceCallback(Protocol):
    def __call__(
        self, process_method: str, model_name: str | None = None
    ) -> tuple[str | None, Any | None]: ...


class CachedModelSourceHolder(Protocol):
    def __call__(
        self, process_method: str, sources: Any, model_name: str | None = None
    ) -> None: ...


@dataclass
class ProcessData:
    """Typed per-run callbacks and routing flags for engines.

    ``audio_file`` is a filesystem path (``str``) or a pre-decoded mix
    (``np.ndarray``) when long-file chunking is active.
    """

    export_path: str
    audio_file_base: str
    audio_file: AudioFile
    set_progress_bar: ProgressCallback
    write_to_console: ConsoleCallback
    process_iteration: Callable[[], None]
    check_run_control: Callable[[], None]
    cached_source_callback: CachedSourceCallback
    cached_model_source_holder: CachedModelSourceHolder
    list_all_models: list[str]
    is_ensemble_master: bool = False
    is_4_stem_ensemble: bool = False
    capture_stems_only: bool = False
    is_save_all_outputs_ensemble: bool = False
