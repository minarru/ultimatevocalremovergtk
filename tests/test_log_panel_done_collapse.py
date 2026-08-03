"""The finished progress bar collapses on a timer, not only on Clear log."""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch

from ui.widgets.log_panel import LogPanel


def _panel() -> LogPanel:
    """A LogPanel with just the attributes the collapse path touches.

    ``_sync_progress_section_visible`` reads back the fraction and the label's
    visibility, so those two mocks have to actually round-trip their setters —
    otherwise a bare MagicMock reads as truthy and the revealer never closes.
    """
    panel = LogPanel.__new__(LogPanel)
    panel._done_collapse_id = None
    panel._pulse_source_id = None
    panel._progress_status = ""

    panel._progressbar = MagicMock()
    panel._progressbar.get_fraction.return_value = 1.0
    panel._progressbar.set_fraction.side_effect = lambda value: setattr(
        panel._progressbar.get_fraction, "return_value", value
    )

    panel._progress_label = MagicMock()
    panel._progress_label.get_visible.return_value = True
    panel._progress_label.set_visible.side_effect = lambda value: setattr(
        panel._progress_label.get_visible, "return_value", value
    )

    panel._progress_revealer = MagicMock()
    panel.console = MagicMock()
    panel._log_stack = MagicMock()
    panel._log_revealer = MagicMock()
    return panel


class DoneCollapseTests(unittest.TestCase):
    def test_mark_run_complete_schedules_a_timeout(self):
        panel = _panel()
        with patch(
            "ui.widgets.log_panel.GLib.timeout_add", return_value=77
        ) as timeout_add:
            panel.mark_run_complete()
        timeout_add.assert_called_once()
        self.assertEqual(timeout_add.call_args[0][0], LogPanel.DONE_COLLAPSE_MS)
        self.assertEqual(panel._done_collapse_id, 77)

    def test_second_completion_replaces_the_pending_timeout(self):
        panel = _panel()
        with patch("ui.widgets.log_panel.GLib.timeout_add", return_value=77):
            panel.mark_run_complete()
        with patch(
            "ui.widgets.log_panel.GLib.timeout_add", return_value=88
        ), patch("ui.widgets.log_panel.GLib.source_remove") as source_remove:
            panel.mark_run_complete()
        source_remove.assert_called_once_with(77)
        self.assertEqual(panel._done_collapse_id, 88)

    def test_firing_the_timeout_clears_progress(self):
        panel = _panel()
        panel._done_collapse_id = 77
        panel._on_done_collapse()
        self.assertIsNone(panel._done_collapse_id)
        cast(Any, panel._progressbar).set_fraction.assert_called_with(0.0)
        cast(Any, panel._progress_revealer).set_reveal_child.assert_called_with(False)

    def test_starting_a_new_run_cancels_the_pending_collapse(self):
        panel = _panel()
        panel._done_collapse_id = 77
        with patch("ui.widgets.log_panel.GLib.source_remove") as source_remove:
            panel.prepare_for_run()
        source_remove.assert_called_once_with(77)
        self.assertIsNone(panel._done_collapse_id)


if __name__ == "__main__":
    unittest.main()
