"""Tests for the background download queue."""
import typing

import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

from core.download_queue import DownloadQueue


class DownloadQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = MagicMock()
        self.manager.resolve.return_value = [
            ("https://example.com/a.onnx", os.path.join(tempfile.gettempdir(), "a.onnx")),
        ]
        self.manager.download.return_value = "complete"
        self.updates = 0
        self.queue = DownloadQueue(
            self.manager,
            on_changed=lambda: setattr(self, "updates", self.updates + 1),
        )

    def test_enqueue_starts_worker(self) -> None:
        item_id = self.queue.enqueue("Test Model", "MDX-Net")
        self.assertIsNotNone(item_id)
        deadline = threading.Event()

        def wait_done():
            for _ in range(100):
                if self.queue.active_count() == 0:
                    deadline.set()
                    return
                threading.Event().wait(0.05)
            deadline.set()

        threading.Thread(target=wait_done, daemon=True).start()
        deadline.wait(timeout=5)
        items = self.queue.items()
        self.assertEqual(len(items), 1)
        self.assertIn(items[0].status, ("complete", "failed", "cancelled", "exists"))

    def test_enqueue_many(self) -> None:
        ids = self.queue.enqueue_many([("A", "VR Arch"), ("B", "MDX-Net")])
        self.assertEqual(len(ids), 2)

    def test_cancel_queued_item_keeps_terminal_detail(self) -> None:
        from core.download_status import STATUS_CANCELLED, default_detail_for_status

        started = threading.Event()
        release = threading.Event()

        def blocking_download(jobs: typing.Any, **kwargs: typing.Any):
            started.set()
            release.wait(timeout=5)
            return "complete"

        self.manager.download.side_effect = blocking_download
        self.queue.enqueue("First", "MDX-Net")
        started.wait(timeout=5)
        second_id = self.queue.enqueue("Second", "MDX-Net")
        assert second_id is not None

        # Second item is still STATUS_QUEUED (worker is busy on the first).
        self.queue.cancel(second_id)
        items = {item.item_id: item for item in self.queue.items()}
        self.assertEqual(items[second_id].status, STATUS_CANCELLED)
        self.assertEqual(
            items[second_id].detail, default_detail_for_status(STATUS_CANCELLED)
        )

        release.set()

    def test_cancel_all_cancels_queued_and_signals_current_download(self) -> None:
        from core.download_status import STATUS_CANCELLED, STATUS_DOWNLOADING

        started = threading.Event()
        release = threading.Event()

        def blocking_download(jobs: typing.Any, **kwargs: typing.Any):
            started.set()
            release.wait(timeout=5)
            return "stopped"

        self.manager.download.side_effect = blocking_download
        first_id = self.queue.enqueue("First", "MDX-Net")
        self.assertTrue(started.wait(timeout=5))
        second_id = self.queue.enqueue("Second", "MDX-Net")

        self.assertEqual(self.queue.cancel_all(), 2)
        items = {item.item_id: item for item in self.queue.items()}
        assert first_id is not None and second_id is not None
        self.assertEqual(items[first_id].status, STATUS_DOWNLOADING)
        self.assertTrue(items[first_id].stop_event.is_set())
        self.assertEqual(items[first_id].detail, "Cancelling…")
        self.assertEqual(items[second_id].status, STATUS_CANCELLED)
        self.assertEqual(self.queue.active_count(), 1)

        release.set()
        for _ in range(100):
            if self.queue.active_count() == 0:
                break
            threading.Event().wait(0.01)
        self.assertEqual(self.queue.active_count(), 0)

    def test_ensure_worker_never_double_starts(self) -> None:
        spawn_count = {"n": 0}
        barrier = threading.Barrier(20)

        def fake_worker_main() -> None:
            spawn_count["n"] += 1
            threading.Event().wait(0.05)
            with self.queue._lock:
                self.queue._worker_active = False

        self.queue._worker_main = fake_worker_main  # type: ignore[method-assign]

        def call_ensure() -> None:
            barrier.wait()
            self.queue._ensure_worker()

        threads = [threading.Thread(target=call_ensure) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        threading.Event().wait(0.2)
        self.assertEqual(spawn_count["n"], 1)


if __name__ == "__main__":
    unittest.main()
