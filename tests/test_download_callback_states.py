"""Download attempts and popover timers keep their callback state separate."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from core.download_queue import DownloadQueue, DownloadQueueItem
from ui.download import DownloadQueueUiBinding
from ui.widgets.download_queue_indicator import DownloadQueueIndicator


class DownloadAttemptFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.queue = DownloadQueue(Mock())
        self.item = DownloadQueueItem("fixture", "fixture", "mdx", "Fixture", [])
        self.queue._items = [self.item]
        self.window: Any = Mock()
        self.context: Any = SimpleNamespace(download_queue=self.queue, settings=Mock())
        self.enterContext(patch("ui.download.latest_main_thread", side_effect=lambda fn: fn))
        self.enterContext(patch.object(self.queue, "_ensure_worker"))
        self.toast = self.enterContext(patch("ui.download.Adw.Toast.new", return_value=Mock()))
        self.notify = self.enterContext(patch("ui.download._send_download_notifications"))
        self.binding = DownloadQueueUiBinding(self.window, self.context)
        self.addCleanup(self.binding.dispose)

    def test_successful_retry_gets_its_own_feedback(self):
        self.item.status = "failed"
        self.binding.after_batch()
        self.assertEqual(self.toast.call_args.args[0], "1 download failed")
        self.assertTrue(self.queue.retry(self.item.item_id))
        self.item.status = "complete"
        self.binding.after_batch()
        self.assertEqual(self.toast.call_args.args[0], "1 model ready to use")
        self.assertEqual(self.notify.call_args.kwargs["items"], [self.item])

    def test_failed_retry_remains_actionable(self):
        for _ in range(2):
            self.item.status = "failed"
            self.binding.after_batch()
            self.assertEqual(self.toast.call_args.args[0], "1 download failed")
            self.assertEqual(self.notify.call_args.kwargs["items"], [self.item])
            self.assertTrue(self.queue.retry(self.item.item_id))
        self.assertEqual(self.window._download_queue_indicator.hold_finished.call_count, 2)

    def test_same_terminal_attempt_is_not_reported_twice(self):
        self.item.status = "complete"
        self.binding.after_batch()
        self.binding.refresh()
        self.binding.after_batch()
        self.toast.assert_called_once()
        self.notify.assert_called_once()


class FinishedPopoverTimerTests(unittest.TestCase):
    def test_close_rearms_finished_queue_without_a_refresh_while_open(self):
        for status, expected in (
            ("complete", 1),
            ("cancelled", 1),
            ("failed", 0),
            ("downloading", 0),
        ):
            with self.subTest(status=status):
                indicator: Any = DownloadQueueIndicator.__new__(DownloadQueueIndicator)
                indicator._queue = Mock()
                indicator._queue.items.return_value = [
                    DownloadQueueItem("fixture", "fixture", "mdx", "Fixture", [], status=status)
                ]
                indicator._popover_visible = False
                indicator._defer_remove_on_close = False
                indicator._unschedule_remove_finished = Mock()
                indicator._schedule_remove_finished = Mock()
                indicator.on_popover_visibility_changed(True)
                indicator.on_popover_visibility_changed(False)
                indicator._unschedule_remove_finished.assert_called_once()
                self.assertEqual(indicator._schedule_remove_finished.call_count, expected)
