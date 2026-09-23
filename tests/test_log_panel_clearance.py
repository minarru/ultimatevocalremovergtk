import unittest
from unittest.mock import MagicMock

from ui.widgets.log_panel import LogPanel


class LogPanelAccessibilityTests(unittest.TestCase):
    def test_expand_button_tooltip_describes_next_action(self):
        panel = LogPanel.__new__(LogPanel)
        panel.expand_button = MagicMock()

        panel._sync_expand_button_a11y(False)
        panel.expand_button.set_tooltip_text.assert_called_with("Show processing log")

        panel._sync_expand_button_a11y(True)
        panel.expand_button.set_tooltip_text.assert_called_with("Hide processing log")


class LogPanelRevealTests(unittest.TestCase):
    def test_hidden_console_is_not_scrolled_when_empty_page_opens(self):
        panel = LogPanel.__new__(LogPanel)
        panel.console = MagicMock()
        panel._log_stack = MagicMock()
        panel._log_stack.get_visible_child_name.return_value = "empty"
        revealer = MagicMock()
        revealer.get_child_revealed.return_value = True
        panel._on_log_revealed(revealer, None)
        panel.console.resume_scroll.assert_not_called()
        panel.console.scroll_to_end_stable.assert_not_called()

    def test_console_page_resumes_scrolling_only_after_reveal(self):
        panel = LogPanel.__new__(LogPanel)
        panel.console = MagicMock()
        panel._log_stack = MagicMock()
        panel._log_stack.get_visible_child_name.return_value = "console"
        revealer = MagicMock()
        revealer.get_child_revealed.return_value = False
        panel._on_log_revealed(revealer, None)
        panel.console.resume_scroll.assert_not_called()
        revealer.get_child_revealed.return_value = True
        panel._on_log_revealed(revealer, None)
        panel.console.resume_scroll.assert_called_once_with()
        panel.console.scroll_to_end_stable.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
