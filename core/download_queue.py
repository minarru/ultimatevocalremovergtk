"""Background model download queue (runs independently of Download Center UI)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.debug_log import debug

# Cap queue UI refresh rate while a download reports per-chunk progress.
_PROGRESS_NOTIFY_INTERVAL_S = 0.1
from core.download_status import (
    ACTIVE_STATUSES,
    RESULT_STOPPED,
    STATUS_CANCELLED,
    STATUS_COMPLETE,
    STATUS_DOWNLOADING,
    STATUS_FAILED,
    STATUS_QUEUED,
    default_detail_for_status,
    map_download_result,
)


@dataclass
class DownloadQueueItem:
    item_id: str
    selection: str
    arch_type: str
    label: str
    jobs: list
    status: str = STATUS_QUEUED
    progress: float = 0.0
    detail: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)


class DownloadQueue:
    """Sequential download queue shared by the app (survives window close)."""

    def __init__(self, manager, on_changed: Optional[Callable[[], None]] = None, repo=None):
        self.manager = manager
        self.repo = repo
        self._on_changed = on_changed
        self._items: List[DownloadQueueItem] = []
        self._lock = threading.Lock()
        self._worker_active = False
        self._on_batch_complete: Optional[Callable[[], None]] = None

    def set_on_batch_complete(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_batch_complete = callback

    def set_on_changed(self, callback: Optional[Callable[[], None]]) -> None:
        self._on_changed = callback

    def items(self) -> List[DownloadQueueItem]:
        with self._lock:
            return list(self._items)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for item in self._items if item.status in ACTIVE_STATUSES)

    def enqueue(self, selection: str, arch_type: str) -> Optional[str]:
        jobs = self.manager.resolve(selection, arch_type)
        if not jobs:
            return None
        item = DownloadQueueItem(
            item_id=uuid.uuid4().hex,
            selection=selection,
            arch_type=arch_type,
            label=selection,
            jobs=jobs,
        )
        with self._lock:
            self._items.append(item)
        debug("download", f"queue enqueue id={item.item_id} selection={selection!r}")
        self._notify()
        self._ensure_worker()
        return item.item_id

    def enqueue_many(self, entries: List[tuple[str, str]]) -> List[str]:
        ids: List[str] = []
        for selection, arch_type in entries:
            item_id = self.enqueue(selection, arch_type)
            if item_id:
                ids.append(item_id)
        return ids

    def cancel(self, item_id: str) -> None:
        with self._lock:
            for item in self._items:
                if item.item_id == item_id and item.status in ACTIVE_STATUSES:
                    item.stop_event.set()
                    if item.status == STATUS_QUEUED:
                        item.status = STATUS_CANCELLED
                        item.detail = default_detail_for_status(STATUS_CANCELLED)
                    else:
                        item.detail = "Cancelling…"
                    break
        self._notify()

    def retry(self, item_id: str) -> bool:
        """Re-queue a failed item. Returns True when the item was requeued."""
        with self._lock:
            for item in self._items:
                if item.item_id != item_id or item.status != STATUS_FAILED:
                    continue
                item.status = STATUS_QUEUED
                item.progress = 0.0
                item.detail = ""
                item.stop_event = threading.Event()
                break
            else:
                return False
        self._notify()
        self._ensure_worker()
        return True

    def clear_finished(self) -> None:
        """Remove successful / cancelled items; keep failed rows for retry."""
        with self._lock:
            self._items = [
                item
                for item in self._items
                if item.status in ACTIVE_STATUSES or item.status == STATUS_FAILED
            ]
        self._notify()

    def _notify(self) -> None:
        if self._on_changed is not None:
            self._on_changed()

    def _has_queued(self) -> bool:
        with self._lock:
            return any(item.status == STATUS_QUEUED for item in self._items)

    def _next_queued(self) -> Optional[DownloadQueueItem]:
        with self._lock:
            for item in self._items:
                if item.status == STATUS_QUEUED:
                    item.status = STATUS_DOWNLOADING
                    item.detail = "Starting…"
                    item.progress = 0.0
                    return item
        return None

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker_active:
                return
            self._worker_active = True
        threading.Thread(target=self._worker_main, daemon=True).start()

    def _worker_main(self) -> None:
        processed_any = False
        try:
            while True:
                item = self._next_queued()
                if item is None:
                    break
                processed_any = True
                self._process_item(item)
        finally:
            with self._lock:
                self._worker_active = False
            self._notify()
            if processed_any and self._on_batch_complete is not None:
                self._on_batch_complete()
            if self._has_queued():
                self._ensure_worker()

    def _process_item(self, item: DownloadQueueItem) -> bool:
        if item.stop_event.is_set():
            item.status = STATUS_CANCELLED
            item.detail = default_detail_for_status(STATUS_CANCELLED)
            self._notify()
            return False

        last_progress_notify = 0.0

        def on_progress(fraction: float) -> None:
            item.progress = max(0.0, min(1.0, fraction))
            nonlocal last_progress_notify
            now = time.monotonic()
            if fraction >= 1.0 or now - last_progress_notify >= _PROGRESS_NOTIFY_INTERVAL_S:
                last_progress_notify = now
                self._notify()

        def on_info(text: str) -> None:
            if item.detail == text:
                return
            item.detail = text
            self._notify()

        try:
            result = self.manager.download(
                item.jobs,
                on_progress=on_progress,
                on_info=on_info,
                stop_event=item.stop_event,
                repo=self.repo,
            )
        except Exception as exc:  # noqa: BLE001
            if item.stop_event.is_set():
                debug("download", f"queue cancelled id={item.item_id}")
                item.status = STATUS_CANCELLED
                item.detail = default_detail_for_status(STATUS_CANCELLED)
                self._notify()
                return False
            debug("download", f"queue failed id={item.item_id} err={type(exc).__name__}: {exc}")
            item.status = STATUS_FAILED
            detail = str(exc).strip() or type(exc).__name__
            if type(exc).__name__ not in detail:
                detail = f"{type(exc).__name__}: {detail}"
            item.detail = detail
            try:
                from ui.errorlog import log_error

                log_error(
                    "Download",
                    exc,
                    context=f"selection={item.selection!r} arch={item.arch_type!r}",
                )
            except Exception:  # noqa: BLE001 - logging must not abort the queue
                pass
            self._notify()
            return False

        if item.stop_event.is_set() and result == RESULT_STOPPED:
            item.status = STATUS_CANCELLED
            item.detail = default_detail_for_status(STATUS_CANCELLED)
        else:
            item.status = map_download_result(result)
            if item.status == STATUS_COMPLETE:
                item.progress = 1.0
            default_detail = default_detail_for_status(item.status)
            if default_detail:
                item.detail = default_detail
        self._notify()
        return item.status == STATUS_COMPLETE
