"""Tests for the Nautilus-style download queue indicator."""

import unittest

from core.download_queue import DownloadQueueItem
from ui.widgets.download_queue_icons import (
    ICON_CANCEL,
    ICON_CANCELLED,
    ICON_ROW_SUCCESS,
)
from ui.widgets.download_queue_indicator import (
    _row_button_state,
    chip_ring_state,
    should_schedule_remove_finished,
    summarize_queue,
)


def _item(
    item_id: str,
    *,
    status: str = "queued",
    progress: float = 0.0,
    label: str = "Model",
) -> DownloadQueueItem:
    return DownloadQueueItem(
        item_id=item_id,
        selection=label,
        arch_type="MDX-Net",
        label=label,
        jobs=[],
        status=status,
        progress=progress,
    )


class SummarizeQueueTests(unittest.TestCase):
    def test_empty_queue(self) -> None:
        summary = summarize_queue([])
        self.assertEqual(summary.total, 0)
        self.assertFalse(summary.has_active)
        self.assertTrue(summary.all_terminal)

    def test_single_active_downloading(self) -> None:
        items = [_item("a", status="downloading", progress=0.5)]
        summary = summarize_queue(items)
        self.assertEqual(summary.chip_label, "Downloading 1 model")
        self.assertTrue(summary.has_active)

    def test_mixed_progress(self) -> None:
        items = [
            _item("a", status="complete", progress=1.0),
            _item("b", status="downloading", progress=0.5),
            _item("c", status="queued"),
        ]
        summary = summarize_queue(items)
        self.assertEqual(summary.chip_label, "Downloading 2 models")
        self.assertTrue(summary.has_active)

    def test_all_complete(self) -> None:
        items = [
            _item("a", status="complete"),
            _item("b", status="exists"),
        ]
        summary = summarize_queue(items)
        self.assertEqual(summary.chip_label, "Downloaded 2 models")
        self.assertTrue(summary.all_terminal)
        self.assertFalse(summary.has_failed)

    def test_failures(self) -> None:
        items = [
            _item("a", status="failed"),
            _item("b", status="complete"),
        ]
        summary = summarize_queue(items)
        self.assertEqual(summary.chip_label, "1 failed, 1 downloaded")
        self.assertTrue(summary.has_failed)
        self.assertTrue(summary.all_terminal)

    def test_all_failed(self) -> None:
        items = [_item("a", status="failed"), _item("b", status="failed")]
        summary = summarize_queue(items)
        self.assertEqual(summary.chip_label, "2 downloads failed")


class ChipRingStateTests(unittest.TestCase):
    def test_active_average_progress(self) -> None:
        items = [
            _item("a", status="downloading", progress=0.4),
            _item("b", status="downloading", progress=0.8),
            _item("c", status="queued"),
        ]
        summary = summarize_queue(items)
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "active")
        self.assertAlmostEqual(state.progress, (0.4 + 0.8) / 3)

    def test_active_queued_only_is_zero(self) -> None:
        items = [_item("a", status="queued"), _item("b", status="queued")]
        summary = summarize_queue(items)
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "active")
        self.assertEqual(state.progress, 0.0)

    def test_finished_items_stay_in_the_aggregate(self) -> None:
        """The ring is a batch aggregate, not a mean over active items.

        Averaging over ACTIVE_STATUSES alone dropped completed work out of
        both halves of the fraction, so the ring snapped back to 0% every time
        a model finished — reading 0% with four of five models on disk.
        """
        items = [
            _item("a", status="complete", progress=1.0),
            _item("b", status="complete", progress=1.0),
            _item("c", status="complete", progress=1.0),
            _item("d", status="complete", progress=1.0),
            _item("e", status="downloading", progress=0.0),
        ]
        state = chip_ring_state(items, summarize_queue(items))
        self.assertEqual(state.outcome, "active")
        self.assertAlmostEqual(state.progress, 0.8)

    def test_progress_never_decreases_as_items_finish(self) -> None:
        seen: list[float] = []
        total = 4
        for done in range(total):
            for fraction in (0.0, 0.5, 1.0):
                items = [
                    _item(f"done{i}", status="complete", progress=1.0)
                    for i in range(done)
                ]
                items.append(_item("cur", status="downloading", progress=fraction))
                items += [
                    _item(f"q{i}", status="queued") for i in range(done + 1, total)
                ]
                seen.append(chip_ring_state(items, summarize_queue(items)).progress)
        self.assertEqual(seen, sorted(seen))

    def test_terminal_failures_still_advance_the_ring(self) -> None:
        """A failed item will never progress; holding the ring back on it
        would stall the batch. Its outcome is carried by the ring's morph."""
        items = [
            _item("a", status="failed"),
            _item("b", status="downloading", progress=0.5),
        ]
        state = chip_ring_state(items, summarize_queue(items))
        self.assertAlmostEqual(state.progress, 0.75)

    def test_failed_outcome(self) -> None:
        items = [_item("a", status="failed"), _item("b", status="complete")]
        summary = summarize_queue(items)
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "partial")

    def test_all_failed_outcome(self) -> None:
        items = [_item("a", status="failed"), _item("b", status="failed")]
        summary = summarize_queue(items)
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "failed")

    def test_success_outcome(self) -> None:
        items = [_item("a", status="complete"), _item("b", status="exists")]
        summary = summarize_queue(items)
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "success")
        self.assertEqual(state.progress, 1.0)

    def test_cancelled_only_morphs_to_exclamation(self) -> None:
        items = [_item("a", status="cancelled")]
        summary = summarize_queue(items)
        self.assertEqual(summary.chip_label, "1 download cancelled")
        state = chip_ring_state(items, summary)
        self.assertEqual(state.outcome, "cancelled")
        self.assertEqual(state.progress, 1.0)


class RowButtonStateTests(unittest.TestCase):
    def test_active_is_cancel_and_sensitive(self) -> None:
        icon, sensitive = _row_button_state(_item("a", status="downloading"))
        self.assertEqual(icon, ICON_CANCEL)
        self.assertTrue(sensitive)

    def test_complete_morphs_to_finished_icon(self) -> None:
        icon, sensitive = _row_button_state(_item("a", status="complete"))
        self.assertEqual(icon, ICON_ROW_SUCCESS)
        self.assertFalse(sensitive)

    def test_cancelled_icon(self) -> None:
        icon, sensitive = _row_button_state(_item("a", status="cancelled"))
        self.assertEqual(icon, ICON_CANCELLED)
        self.assertFalse(sensitive)

    def test_failed_icon(self) -> None:
        from ui.widgets.download_queue_icons import ICON_RETRY

        icon, sensitive = _row_button_state(_item("a", status="failed"))
        self.assertEqual(icon, ICON_RETRY)
        self.assertTrue(sensitive)

    def test_skips_auto_clear_when_failed(self) -> None:
        summary = summarize_queue([_item("a", status="failed")])
        self.assertFalse(
            should_schedule_remove_finished(
                summary,
                popover_visible=False,
                defer_remove_on_close=False,
            )
        )


class AutoDismissSchedulingTests(unittest.TestCase):
    def test_schedules_when_all_terminal_and_popover_closed(self) -> None:
        summary = summarize_queue([_item("a", status="complete")])
        self.assertTrue(
            should_schedule_remove_finished(
                summary,
                popover_visible=False,
                defer_remove_on_close=False,
            )
        )

    def test_defers_while_popover_open(self) -> None:
        summary = summarize_queue([_item("a", status="complete")])
        self.assertFalse(
            should_schedule_remove_finished(
                summary,
                popover_visible=True,
                defer_remove_on_close=False,
            )
        )

    def test_defers_when_flagged_for_close(self) -> None:
        summary = summarize_queue([_item("a", status="complete")])
        self.assertFalse(
            should_schedule_remove_finished(
                summary,
                popover_visible=False,
                defer_remove_on_close=True,
            )
        )

    def test_skips_while_active(self) -> None:
        summary = summarize_queue([_item("a", status="downloading", progress=0.2)])
        self.assertFalse(
            should_schedule_remove_finished(
                summary,
                popover_visible=False,
                defer_remove_on_close=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
