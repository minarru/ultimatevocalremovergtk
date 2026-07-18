"""Tests for slider default tick marks."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ScaleDefaultMarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.scale-marks")
        cls._app.register()

    def test_numeric_mark_uses_default_value(self) -> None:
        from ui.widgets.rows import make_numeric_scale_row, set_scale_default_mark

        row = make_numeric_scale_row("Segment size", 32, 4000, step=32)
        set_scale_default_mark(row, 256)
        self.assertEqual(row._uvr_default, 256)

    def test_discrete_mark_matches_choice_index(self) -> None:
        from ui.widgets.rows import (
            make_discrete_scale_row,
            reconfigure_discrete_scale,
            set_scale_default_mark,
        )

        row = make_discrete_scale_row("Overlap", ["Default", "0.25", "0.50"])
        set_scale_default_mark(row, "Default")
        self.assertEqual(row._uvr_default, "Default")
        reconfigure_discrete_scale(row, ["Default", "0.25", "0.50", "0.75"])
        self.assertEqual(row._uvr_default, "Default")

    def test_reconfigure_numeric_keeps_default_mark(self) -> None:
        from ui.widgets.rows import (
            make_numeric_scale_row,
            reconfigure_numeric_scale,
            set_scale_default_mark,
        )

        row = make_numeric_scale_row("Overlap", 2, 50, step=1)
        set_scale_default_mark(row, "8")
        reconfigure_numeric_scale(row, 2, 50, step=1, digits=0)
        self.assertEqual(row._uvr_default, "8")


class MdxSegmentDefaultWiringTests(unittest.TestCase):
    def test_mdx_c_segment_choices_start_with_default(self) -> None:
        from bundled.constants import DEF_OPT
        from ui.views.mdx import _MDX_C_SEGMENT_VALUES

        self.assertEqual(_MDX_C_SEGMENT_VALUES[0], DEF_OPT)
        self.assertIn("256", _MDX_C_SEGMENT_VALUES)
        self.assertIn("32", _MDX_C_SEGMENT_VALUES)


if __name__ == "__main__":
    unittest.main()
