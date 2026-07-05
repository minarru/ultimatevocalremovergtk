import unittest

from ui.hints import set_tooltip


class _TooltipWidget:
    def __init__(self):
        self.tooltip = "unset"

    def set_tooltip_text(self, text):
        self.tooltip = text


class SetTooltipTests(unittest.TestCase):
    def test_clears_empty_text(self):
        widget = _TooltipWidget()
        set_tooltip(widget, "")
        self.assertIsNone(widget.tooltip)

    def test_applies_text_unchanged(self):
        widget = _TooltipWidget()
        text = "Line one\n\n• Bullet"
        set_tooltip(widget, text)
        self.assertEqual(widget.tooltip, text)


if __name__ == "__main__":
    unittest.main()
