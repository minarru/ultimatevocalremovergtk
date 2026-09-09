"""Optional phase reporting for engine adapters and legacy process payloads."""

from __future__ import annotations

from typing import Any

from core.processing_phase import ProcessingPhase


def report_phase(separator: Any, phase: ProcessingPhase) -> None:
    process = getattr(separator, "process_data", None)
    callback = getattr(process, "report_phase", None)
    if callback is not None:
        callback(phase)
