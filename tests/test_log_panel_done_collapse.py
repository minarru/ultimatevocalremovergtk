"""The finished progress bar collapses on a timer, not only on Clear log."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ui.widgets.log_panel import LogPanel


def _panel() -> LogPanel:
    panel = LogPanel()
    panel.set_progress_fraction(1)
    panel.set_progress_text("Done")
    return panel


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "GTK needs a display"
)
class DoneCollapseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        Adw.init()

    def test_mark_run_complete_schedules_a_timeout(self):
        panel = _panel()
        with patch("ui.widgets.log_panel.GLib.timeout_add", return_value=77) as timeout_add:
            panel.mark_run_complete()
        timeout_add.assert_called_once()
        self.assertEqual(timeout_add.call_args[0][0], LogPanel.DONE_COLLAPSE_MS)
        self.assertEqual(panel._done_collapse_id, 77)

    def test_second_completion_replaces_the_pending_timeout(self):
        panel = _panel()
        with patch("ui.widgets.log_panel.GLib.timeout_add", return_value=77):
            panel.mark_run_complete()
        with (
            patch("ui.widgets.log_panel.GLib.timeout_add", return_value=88),
            patch("ui.widgets.log_panel.GLib.source_remove") as source_remove,
        ):
            panel.mark_run_complete()
        source_remove.assert_called_once_with(77)
        self.assertEqual(panel._done_collapse_id, 88)

    def test_firing_the_timeout_clears_progress(self):
        panel = _panel()
        panel._done_collapse_id = 77
        panel._on_done_collapse()
        self.assertIsNone(panel._done_collapse_id)
        self.assertEqual(panel.progressbar.get_fraction(), 0.0)
        self.assertFalse(panel._progress_revealer.get_reveal_child())
        self.assertIn("complete", panel._progress_label.get_text())

    def test_starting_a_new_run_cancels_the_pending_collapse(self):
        panel = _panel()
        panel._done_collapse_id = 77
        with patch("ui.widgets.log_panel.GLib.source_remove") as source_remove:
            panel.prepare_for_run()
        source_remove.assert_called_once_with(77)
        self.assertIsNone(panel._done_collapse_id)


if __name__ == "__main__":
    unittest.main()
