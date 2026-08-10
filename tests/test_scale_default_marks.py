"""Tests for slider default tick marks."""

from __future__ import annotations

import os
import unittest
from ui.widget_state import fetch


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
        self.assertEqual(fetch(row, "_uvr_default"), 256)

    def test_discrete_mark_matches_choice_index(self) -> None:
        from ui.widgets.rows import (
            make_discrete_scale_row,
            reconfigure_discrete_scale,
            set_scale_default_mark,
        )

        row = make_discrete_scale_row("Overlap", ["Default", "0.25", "0.50"])
        set_scale_default_mark(row, "Default")
        self.assertEqual(fetch(row, "_uvr_default"), "Default")
        reconfigure_discrete_scale(row, ["Default", "0.25", "0.50", "0.75"])
        self.assertEqual(fetch(row, "_uvr_default"), "Default")

    def test_reconfigure_numeric_keeps_default_mark(self) -> None:
        from ui.widgets.rows import (
            make_numeric_scale_row,
            reconfigure_numeric_scale,
            set_scale_default_mark,
        )

        row = make_numeric_scale_row("Overlap", 2, 50, step=1)
        set_scale_default_mark(row, "8")
        reconfigure_numeric_scale(row, 2, 50, step=1, digits=0)
        self.assertEqual(fetch(row, "_uvr_default"), "8")

class MdxSegmentDefaultWiringTests(unittest.TestCase):
    def test_mdx_c_segment_choices_start_with_default(self) -> None:
        from bundled.constants import DEF_OPT
        from ui.views.mdx import _MDX_C_SEGMENT_VALUES

        self.assertEqual(_MDX_C_SEGMENT_VALUES[0], DEF_OPT)
        self.assertIn("256", _MDX_C_SEGMENT_VALUES)
        self.assertIn("32", _MDX_C_SEGMENT_VALUES)

    def test_mdx_c_default_segment_size_from_yaml(self) -> None:
        from types import SimpleNamespace

        from ui.views.mdx import mdx_c_default_segment_size

        model = SimpleNamespace(
            is_mdx_c=True,
            mdx_c_configs=SimpleNamespace(inference=SimpleNamespace(dim_t=512)),
        )
        self.assertEqual(mdx_c_default_segment_size(model), 512)
        self.assertIsNone(mdx_c_default_segment_size(SimpleNamespace(is_mdx_c=False)))
        self.assertIsNone(
            mdx_c_default_segment_size(
                SimpleNamespace(is_mdx_c=True, mdx_c_configs=None)
            )
        )

    def test_nearest_mdx_segment_size_snaps(self) -> None:
        from ui.views.mdx import nearest_mdx_segment_size

        self.assertEqual(nearest_mdx_segment_size(256), 256)
        self.assertEqual(nearest_mdx_segment_size(250), 256)
        self.assertEqual(nearest_mdx_segment_size(240), 224)
        self.assertEqual(nearest_mdx_segment_size(1), 32)
        self.assertEqual(nearest_mdx_segment_size(9999), 4000)


class MdxStemSelectionStaleTests(unittest.TestCase):
    """A persisted ``mdx.stems`` value is only "stale" (no longer valid for
    the selected model) when it names none of the model's stems -- but the
    model's stems carry a checkpoint's own yaml casing (often lowercase),
    while the save-stems widget persists canonical UVR labels (``Vocals``).
    A case-sensitive check flags a merely differently-cased match as stale
    and silently resets the user's stem selection to "All Stems"."""

    def test_a_differently_cased_match_is_not_stale(self) -> None:
        from ui.views.mdx import mdx_stem_selection_is_stale

        self.assertFalse(
            mdx_stem_selection_is_stale(["drums", "bass", "other", "vocals"], "Vocals")
        )

    def test_a_name_the_model_does_not_have_is_stale(self) -> None:
        from ui.views.mdx import mdx_stem_selection_is_stale

        self.assertTrue(
            mdx_stem_selection_is_stale(["drums", "bass", "other", "vocals"], "Piano")
        )

    def test_all_stems_is_never_stale(self) -> None:
        from bundled.constants import ALL_STEMS
        from ui.views.mdx import mdx_stem_selection_is_stale

        self.assertFalse(
            mdx_stem_selection_is_stale(["drums", "bass", "other", "vocals"], ALL_STEMS)
        )


if __name__ == "__main__":
    unittest.main()
