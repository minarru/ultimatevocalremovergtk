"""Tests for download queue status helpers."""

import unittest

from core.download_status import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    RESULT_STOPPED,
    ROW_PROGRESS,
    STATUS_CANCELLED,
    STATUS_COMPLETE,
    STATUS_DOWNLOADING,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_QUEUED,
    SUCCESS_STATUSES,
    TERMINAL_STATUSES,
    default_detail_for_status,
    map_download_result,
    normalize_item_status,
    row_action_tooltip_for,
    row_progress_for,
)
from core.download_queue import DownloadQueueItem
from ui.widgets.download_queue_indicator import _row_button_state, chip_ring_state, summarize_queue
from ui.widgets.download_queue_icons import (
    ICON_CANCEL,
    ICON_CANCELLED,
    ICON_RETRY,
    ICON_ROW_SUCCESS,
)


def _item(status: str, **kwargs) -> DownloadQueueItem:
    return DownloadQueueItem(
        item_id="a",
        selection="Model",
        arch_type="MDX-Net",
        label="Model",
        jobs=[],
        status=status,
        **kwargs,
    )


class DownloadStatusRegistryTests(unittest.TestCase):
    def test_all_statuses_partitioned(self) -> None:
        self.assertEqual(ACTIVE_STATUSES | TERMINAL_STATUSES, ALL_STATUSES)
        self.assertFalse(ACTIVE_STATUSES & TERMINAL_STATUSES)

    def test_every_status_has_row_progress(self) -> None:
        for status in ALL_STATUSES:
            self.assertIn(status, ROW_PROGRESS)

    def test_map_download_result(self) -> None:
        self.assertEqual(map_download_result(RESULT_STOPPED), STATUS_CANCELLED)
        self.assertEqual(map_download_result(STATUS_COMPLETE), STATUS_COMPLETE)
        self.assertEqual(map_download_result("bogus"), STATUS_FAILED)

    def test_normalize_unknown_status(self) -> None:
        self.assertEqual(normalize_item_status(STATUS_FAILED), STATUS_FAILED)
        self.assertEqual(normalize_item_status("mystery"), STATUS_FAILED)


class PerStatusPresentationTests(unittest.TestCase):
    def test_row_button_state_covers_all_terminal_and_active(self) -> None:
        expectations = {
            STATUS_QUEUED: (ICON_CANCEL, True),
            STATUS_DOWNLOADING: (ICON_CANCEL, True),
            STATUS_COMPLETE: (ICON_ROW_SUCCESS, False),
            STATUS_EXISTS: (ICON_ROW_SUCCESS, False),
            STATUS_CANCELLED: (ICON_CANCELLED, False),
            STATUS_FAILED: (ICON_RETRY, True),
        }
        for status, expected in expectations.items():
            with self.subTest(status=status):
                self.assertEqual(_row_button_state(_item(status)), expected)

    def test_row_progress_modes(self) -> None:
        self.assertEqual(row_progress_for(STATUS_QUEUED).mode, "pulse")
        self.assertEqual(row_progress_for(STATUS_DOWNLOADING).mode, "fraction")
        self.assertEqual(row_progress_for(STATUS_COMPLETE).mode, "full")
        self.assertEqual(row_progress_for(STATUS_EXISTS).mode, "full")
        self.assertFalse(row_progress_for(STATUS_FAILED).visible)
        self.assertFalse(row_progress_for(STATUS_CANCELLED).visible)

    def test_row_action_tooltips(self) -> None:
        expectations = {
            STATUS_QUEUED: "Cancel download",
            STATUS_DOWNLOADING: "Cancel download",
            STATUS_COMPLETE: "Download complete",
            STATUS_EXISTS: "Already on disk",
            STATUS_CANCELLED: "Cancelled",
            STATUS_FAILED: "Retry download",
        }
        for status, expected in expectations.items():
            with self.subTest(status=status):
                self.assertEqual(row_action_tooltip_for(status), expected)

    def test_default_details(self) -> None:
        self.assertEqual(default_detail_for_status(STATUS_COMPLETE), "Complete")
        self.assertEqual(default_detail_for_status(STATUS_EXISTS), "Already on disk")
        self.assertEqual(default_detail_for_status(STATUS_CANCELLED), "Cancelled")

    def test_chip_summary_priority(self) -> None:
        active = summarize_queue([_item(STATUS_DOWNLOADING), _item(STATUS_COMPLETE)])
        self.assertTrue(active.has_active)

        failed = summarize_queue([_item(STATUS_FAILED), _item(STATUS_COMPLETE)])
        self.assertTrue(failed.has_failed)

        success = summarize_queue([_item(STATUS_COMPLETE), _item(STATUS_EXISTS)])
        self.assertFalse(success.has_failed)
        state = chip_ring_state([_item(STATUS_COMPLETE), _item(STATUS_EXISTS)], success)
        self.assertEqual(state.outcome, "success")

    def test_chip_treats_cancelled_batch_as_success_when_mixed_with_complete(self) -> None:
        items = [_item(STATUS_CANCELLED), _item(STATUS_COMPLETE)]
        summary = summarize_queue(items)
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "success")

    def test_chip_cancelled_only_morphs_to_exclamation(self) -> None:
        items = [_item(STATUS_CANCELLED)]
        summary = summarize_queue(items)
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "cancelled")

    def test_chip_partial_when_failed_and_succeeded(self) -> None:
        items = [_item(STATUS_FAILED), _item(STATUS_COMPLETE)]
        summary = summarize_queue(items)
        self.assertEqual(summary.chip_label, "1 failed, 1 downloaded")
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "partial")


if __name__ == "__main__":
    unittest.main()
