"""Download queue item statuses and presentation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Literal, Optional

from core.debug_log import debug

# Item statuses stored on DownloadQueueItem.status
STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_COMPLETE = "complete"
STATUS_EXISTS = "exists"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# Return values from DownloadManager.download (before queue mapping)
RESULT_COMPLETE = "complete"
RESULT_EXISTS = "exists"
RESULT_STOPPED = "stopped"

ACTIVE_STATUSES: FrozenSet[str] = frozenset({STATUS_QUEUED, STATUS_DOWNLOADING})
TERMINAL_STATUSES: FrozenSet[str] = frozenset({
    STATUS_COMPLETE,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_CANCELLED,
})
SUCCESS_STATUSES: FrozenSet[str] = frozenset({STATUS_COMPLETE, STATUS_EXISTS})
ALL_STATUSES: FrozenSet[str] = ACTIVE_STATUSES | TERMINAL_STATUSES

ProgressMode = Literal["pulse", "fraction", "full", "empty"]


@dataclass(frozen=True)
class RowProgress:
    """How a popover row progress bar should render for a status."""

    mode: ProgressMode
    visible: bool = True


# Popover Gtk.ProgressBar presentation per status.
ROW_PROGRESS: dict[str, RowProgress] = {
    STATUS_QUEUED: RowProgress("pulse"),
    STATUS_DOWNLOADING: RowProgress("fraction"),
    STATUS_COMPLETE: RowProgress("full"),
    STATUS_EXISTS: RowProgress("full"),
    STATUS_FAILED: RowProgress("empty", visible=False),
    STATUS_CANCELLED: RowProgress("empty", visible=False),
}

DEFAULT_ROW_PROGRESS = RowProgress("empty", visible=False)


def normalize_item_status(status: str) -> str:
    """Return a known queue status, logging and coercing unknown values."""
    if status in ALL_STATUSES:
        return status
    debug("download", f"unknown download queue status {status!r}; treating as failed")
    return STATUS_FAILED


def map_download_result(result: str) -> str:
    """Map DownloadManager.download() result to a queue item status."""
    if result == RESULT_STOPPED:
        return STATUS_CANCELLED
    if result in {RESULT_COMPLETE, RESULT_EXISTS}:
        return result
    debug("download", f"unknown download result {result!r}; treating as failed")
    return STATUS_FAILED


def default_detail_for_status(status: str) -> str:
    return {
        STATUS_COMPLETE: "Complete",
        STATUS_EXISTS: "Already on disk",
        STATUS_FAILED: "",
        STATUS_CANCELLED: "Cancelled",
        STATUS_QUEUED: "",
        STATUS_DOWNLOADING: "",
    }.get(status, "")


def row_progress_for(status: str) -> RowProgress:
    return ROW_PROGRESS.get(normalize_item_status(status), DEFAULT_ROW_PROGRESS)


def is_active(status: str) -> bool:
    return status in ACTIVE_STATUSES


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def is_success(status: str) -> bool:
    return status in SUCCESS_STATUSES


def is_failed(status: str) -> bool:
    return status == STATUS_FAILED


def is_cancelled(status: str) -> bool:
    return status == STATUS_CANCELLED


def row_action_tooltip_for(status: str) -> Optional[str]:
    """Tooltip for the circular action button on a popover queue row."""
    status = normalize_item_status(status)
    if status in ACTIVE_STATUSES:
        return "Cancel download"
    if status == STATUS_COMPLETE:
        return "Download complete"
    if status == STATUS_EXISTS:
        return "Already on disk"
    if status == STATUS_CANCELLED:
        return "Cancelled"
    if status == STATUS_FAILED:
        return "Retry download"
    return None
