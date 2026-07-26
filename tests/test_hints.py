import unittest

from ui.hints import set_icon_button_a11y, set_tooltip


class _TooltipWidget:
    def __init__(self):
        self.tooltip = "unset"

    def set_tooltip_text(self, text):
        self.tooltip = text


class _A11yWidget(_TooltipWidget):
    def __init__(self):
        super().__init__()
        self.props = {}

    def update_property(self, properties, values):
        for prop, value in zip(properties, values):
            self.props[prop] = value


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


class SetIconButtonA11yTests(unittest.TestCase):
    def test_sets_tooltip_and_accessible_label(self):
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        widget = _A11yWidget()
        set_icon_button_a11y(widget, "Open menu")
        self.assertEqual(widget.tooltip, "Open menu")
        self.assertEqual(widget.props.get(Gtk.AccessibleProperty.LABEL), "Open menu")


if __name__ == "__main__":
    unittest.main()
