"""Locale-aware slider labels and markup-safe About text."""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from unittest import mock


def _comma_locale(real: Mapping[str, object]) -> dict[str, object]:
    return {**real, "decimal_point": ",", "thousands_sep": ""}


class SliderValueFormatTests(unittest.TestCase):
    def test_decimals_follow_the_locale_like_spin_buttons(self) -> None:
        import locale

        from ui.widgets.rows import format_slider_value

        real = locale.localeconv()
        with mock.patch("locale.localeconv", return_value=_comma_locale(real)):
            self.assertEqual(format_slider_value(0.2, 1), "0,2")
            self.assertEqual(format_slider_value(1.0, 2), "1,00")

    def test_whole_numbers_have_no_separator(self) -> None:
        from ui.widgets.rows import format_slider_value

        self.assertEqual(format_slider_value(1088.4, 0), "1088")
        self.assertEqual(format_slider_value(9.6, 0), "10")


class DiscreteChoiceLabelTests(unittest.TestCase):
    def test_decimal_choices_display_in_the_locale(self) -> None:
        import locale

        from ui.widgets.rows import format_choice_label

        real = locale.localeconv()
        with mock.patch("locale.localeconv", return_value=_comma_locale(real)):
            self.assertEqual(format_choice_label("0.2"), "0,2")
            self.assertEqual(format_choice_label("1.035"), "1,035")

    def test_other_choices_are_shown_as_stored(self) -> None:
        import locale

        from ui.widgets.rows import format_choice_label

        real = locale.localeconv()
        with mock.patch("locale.localeconv", return_value=_comma_locale(real)):
            for value in ("Auto", "Default", "256", "1e-3", "v1.2.3", ""):
                self.assertEqual(format_choice_label(value), value)


class AboutTextTests(unittest.TestCase):
    def test_developer_name_is_safe_in_markup(self) -> None:
        # libadwaita drops developer_name into the "Other Apps by %s" markup unescaped.
        from gi.repository import GLib

        from ui.about import DEVELOPER_NAME

        self.assertEqual(GLib.markup_escape_text(DEVELOPER_NAME), DEVELOPER_NAME)


if __name__ == "__main__":
    unittest.main()
