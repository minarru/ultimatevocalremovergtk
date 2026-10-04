"""Slider value labels and markup-safe About text."""

from __future__ import annotations

import os
import unittest
from unittest import mock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SliderValueLabelTests(unittest.TestCase):
    """Slider values read with a dot whatever the locale, as stored."""

    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")

    def _label(self, row: object) -> str:
        from ui.widget_state import fetch

        return fetch(row, "_uvr_value_label").get_label()

    def test_values_keep_their_dot_in_a_comma_locale(self) -> None:
        import locale

        from ui.widgets.rows import (
            make_discrete_scale_row,
            make_numeric_scale_row,
            set_scale_row_value,
        )

        comma = {**locale.localeconv(), "decimal_point": ",", "thousands_sep": ""}
        with mock.patch("locale.localeconv", return_value=comma):
            choice = make_discrete_scale_row("Threshold", ["0.1", "0.2", "0.3"])
            set_scale_row_value(choice, "0.2")
            self.assertEqual(self._label(choice), "0.2")
            numeric = make_numeric_scale_row("Weight", 0, 1, step=0.05, digits=2)
            set_scale_row_value(numeric, 0.25)
            self.assertEqual(self._label(numeric), "0.25")


class AboutTextTests(unittest.TestCase):
    def test_developer_name_is_safe_in_markup(self) -> None:
        # libadwaita drops developer_name into the "Other Apps by %s" markup unescaped.
        from gi.repository import GLib

        from ui.about import DEVELOPER_NAME

        self.assertEqual(GLib.markup_escape_text(DEVELOPER_NAME), DEVELOPER_NAME)


if __name__ == "__main__":
    unittest.main()
