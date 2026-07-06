import unittest
from unittest.mock import MagicMock

from ui.widgets.log_panel import (
    OVERLAY_MARGIN_BOTTOM,
    LogPanel,
    _LOG_BODY_HEIGHT,
    _LOG_BODY_WRAP_RESERVE,
    _LOG_META_ROW_RESERVE,
    _PROGRESS_SECTION_RESERVE,
)


def _panel_with_revealers(*, progress: bool = False, log: bool = False) -> LogPanel:
    panel = LogPanel.__new__(LogPanel)
    panel._progress_revealer = MagicMock()
    panel._progress_revealer.get_reveal_child.return_value = progress
    panel._log_revealer = MagicMock()
    panel._log_revealer.get_reveal_child.return_value = log
    return panel


class LogPanelClearanceTests(unittest.TestCase):
    def test_idle_clearance_matches_default_bottom_inset(self):
        panel = _panel_with_revealers()
        self.assertEqual(
            panel.options_overlay_clearance(),
            LogPanel.default_bottom_inset(),
        )

    def test_progress_reveal_adds_progress_reserve(self):
        panel = _panel_with_revealers()
        idle = panel.options_overlay_clearance()
        panel._progress_revealer.get_reveal_child.return_value = True
        self.assertEqual(
            panel.options_overlay_clearance(),
            idle + _PROGRESS_SECTION_RESERVE,
        )

    def test_log_reveal_adds_meta_body_and_wrap_reserve(self):
        panel = _panel_with_revealers()
        idle = panel.options_overlay_clearance()
        panel._log_revealer.get_reveal_child.return_value = True
        self.assertEqual(
            panel.options_overlay_clearance(),
            idle + _LOG_META_ROW_RESERVE + _LOG_BODY_HEIGHT + _LOG_BODY_WRAP_RESERVE,
        )

    def test_both_revealers_sum_all_reserves(self):
        panel = _panel_with_revealers(progress=True, log=True)
        base = LogPanel._collapsed_body_height(include_progress=False)
        expected = (
            base
            + _PROGRESS_SECTION_RESERVE
            + _LOG_META_ROW_RESERVE
            + _LOG_BODY_HEIGHT
            + _LOG_BODY_WRAP_RESERVE
            + OVERLAY_MARGIN_BOTTOM
        )
        self.assertEqual(panel.options_overlay_clearance(), expected)

    def test_collapsed_overlay_height_alias(self):
        panel = _panel_with_revealers(log=True)
        self.assertEqual(
            panel.collapsed_overlay_height(),
            panel.options_overlay_clearance(),
        )


if __name__ == "__main__":
    unittest.main()
