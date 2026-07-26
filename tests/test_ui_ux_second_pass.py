"""Focused non-visual tests for second-pass UI/UX state helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from bundled.constants import NO_CONNECTION, NO_NEW_MODELS
from core.download_status import (
    STATUS_CANCELLED,
    STATUS_COMPLETE,
    STATUS_EXISTS,
    STATUS_FAILED,
)
from ui.audio_tools.dual_batch import pair_count_state
from ui.download import download_batch_message
from ui.download_center import catalogue_matches
from ui.run_control import target_blocked_reason
from ui.widgets.download_queue_indicator import should_schedule_remove_finished, summarize_queue
from ui.widgets.file_chooser import merge_input_paths
from core.download_queue import DownloadQueueItem


class InputSafetyTests(unittest.TestCase):
    def test_merge_input_paths_is_additive_and_stable(self) -> None:
        self.assertEqual(
            merge_input_paths(
                ["/music/a.wav", "/music/b.wav"],
                ["/music/b.wav", "/music/c.wav", "/music/a.wav"],
            ),
            ["/music/a.wav", "/music/b.wav", "/music/c.wav"],
        )

    def test_pair_counts_must_match(self) -> None:
        self.assertEqual(pair_count_state(2, 2), (True, "2 pairs ready"))
        valid, message = pair_count_state(3, 1)
        self.assertFalse(valid)
        self.assertIn("2 unmatched files on the left", message)


class ReadinessTests(unittest.TestCase):
    def test_target_reason_is_returned(self) -> None:
        target = SimpleNamespace(start_blocked_reason=lambda: "Choose a model")
        self.assertEqual(target_blocked_reason(target), "Choose a model")

    def test_broken_readiness_check_does_not_break_ui(self) -> None:
        def fail():
            raise RuntimeError("bad readiness hook")

        self.assertIsNone(
            target_blocked_reason(SimpleNamespace(start_blocked_reason=fail))
        )


class DownloadFeedbackTests(unittest.TestCase):
    def test_catalogue_filter_omits_sentinels(self) -> None:
        names = ["UVR Model", NO_NEW_MODELS, NO_CONNECTION, "Demucs Model"]
        self.assertEqual(catalogue_matches(names, "model"), ["UVR Model", "Demucs Model"])
        self.assertEqual(catalogue_matches(names, "missing"), [])

    def test_partial_failure_toast_is_honest(self) -> None:
        items = [
            SimpleNamespace(status=STATUS_COMPLETE),
            SimpleNamespace(status=STATUS_EXISTS),
            SimpleNamespace(status=STATUS_FAILED),
            SimpleNamespace(status=STATUS_CANCELLED),
        ]
        message, needs_attention = download_batch_message(items)
        self.assertTrue(needs_attention)
        self.assertEqual(message, "1 download failed; 2 succeeded; 1 cancelled")

    def test_success_toast_reports_ready_count(self) -> None:
        items = [
            SimpleNamespace(status=STATUS_COMPLETE),
            SimpleNamespace(status=STATUS_EXISTS),
        ]
        self.assertEqual(
            download_batch_message(items),
            ("2 models ready to use", False),
        )

    def test_failed_downloads_excluded_from_auto_clear(self) -> None:
        items = [
            DownloadQueueItem(
                item_id="1",
                selection="m",
                arch_type="VR Arch",
                label="m",
                jobs=[],
                status=STATUS_FAILED,
            )
        ]
        summary = summarize_queue(items)
        self.assertTrue(summary.has_failed)
        self.assertFalse(
            should_schedule_remove_finished(
                summary,
                popover_visible=False,
                defer_remove_on_close=False,
            )
        )


class ProfileOverwriteDetectionTests(unittest.TestCase):
    def test_list_profiles_detects_existing_name(self) -> None:
        import os
        import tempfile

        from ui.preferences import ProfileStore

        with tempfile.TemporaryDirectory() as tmp:
            store = ProfileStore(directory=tmp)
            path = os.path.join(tmp, "My_Profile.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{}")
            self.assertIn("My_Profile", store.list_profiles())


class CollectInvalidKeepsDialogOpenTests(unittest.TestCase):
    def test_collect_invalid_is_distinct_from_none(self) -> None:
        from ui.dialogs.utils import CollectInvalid

        exc = CollectInvalid("Invalid Dim_f")
        self.assertEqual(exc.message, "Invalid Dim_f")
        self.assertIsNone(exc.widget)


if __name__ == "__main__":
    unittest.main()
