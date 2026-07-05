"""Tests for the background download queue."""

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


if __name__ == "__main__":
    unittest.main()
