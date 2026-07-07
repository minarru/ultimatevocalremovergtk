"""Background model download queue (runs independently of Download Center UI)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from core.debug_log import debug


@dataclass
class DownloadQueueItem:
    item_id: str
    selection: str
    arch_type: str
    label: str
    jobs: list
    status: str = "queued"
    progress: float = 0.0
    detail: str = ""
    stop_event: threading.Event = field(default_factory=threading.Event)


class DownloadQueue:
    """Sequential download queue shared by the app (survives window close)."""

    def __init__(self, manager, on_changed: Optional[Callable[[], None]] = None):
        self.manager = manager
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
            return sum(1 for item in self._items if item.status in ("queued", "downloading"))

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
                if item.item_id == item_id and item.status in ("queued", "downloading"):
                    item.stop_event.set()
                    if item.status == "queued":
                        item.status = "cancelled"
                    item.detail = "Cancelling…"
                    break
        self._notify()

    def clear_finished(self) -> None:
        with self._lock:
            self._items = [
                item
                for item in self._items
                if item.status in ("queued", "downloading")
            ]
        self._notify()

    def _notify(self) -> None:
        if self._on_changed is not None:
            self._on_changed()

    def _has_queued(self) -> bool:
        with self._lock:
            return any(item.status == "queued" for item in self._items)

    def _next_queued(self) -> Optional[DownloadQueueItem]:
        with self._lock:
            for item in self._items:
                if item.status == "queued":
                    item.status = "downloading"
                    item.detail = "Starting…"
                    item.progress = 0.0
                    return item
        return None

    def _ensure_worker(self) -> None:
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
            self._worker_active = False
            self._notify()
            if processed_any and self._on_batch_complete is not None:
                self._on_batch_complete()
            if self._has_queued():
                self._ensure_worker()

    def _process_item(self, item: DownloadQueueItem) -> bool:
        if item.stop_event.is_set():
            item.status = "cancelled"
            item.detail = "Cancelled"
            self._notify()
            return False

        def on_progress(fraction: float) -> None:
            item.progress = max(0.0, min(1.0, fraction))
            self._notify()

        def on_info(text: str) -> None:
            item.detail = text
            self._notify()

        try:
            result = self.manager.download(
                item.jobs,
                on_progress=on_progress,
                on_info=on_info,
                stop_event=item.stop_event,
            )
        except Exception as exc:  # noqa: BLE001
            debug("download", f"queue failed id={item.item_id} err={type(exc).__name__}: {exc}")
            item.status = "failed"
            item.detail = type(exc).__name__
            self._notify()
            return False

        if item.stop_event.is_set() and result == "stopped":
            item.status = "cancelled"
            item.detail = "Cancelled"
        else:
            item.status = result
            if result == "complete":
                item.progress = 1.0
                item.detail = "Complete"
            elif result == "exists":
                item.detail = "Already on disk"
            elif result == "stopped":
                item.status = "cancelled"
                item.detail = "Cancelled"
        self._notify()
        return item.status == "complete"
