"""Sliders pick from a preset ladder; free numbers use spin rows.

MDX's segment size and overlap switch between a ladder and a free number with
the model, so they stay sliders; they are separate attributes, not
``_scale_rows`` entries.
"""

from __future__ import annotations

import os
import unittest
from typing import Any


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SeparationControlTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.control-types")
        cls._app.register()

    def _window(self) -> Any:
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window

    def test_every_option_slider_is_a_ladder(self) -> None:
        from ui.widget_state import fetch

        window = self._window()
        for view in window._views:
            for key, row in view._scale_rows.items():
                with self.subTest(method=view.method_key, key=key):
                    self.assertTrue(fetch(row, "_uvr_values", None), key)

    def test_every_option_slider_marks_its_default(self) -> None:
        """The tick sits on the default's ladder value, including None-as-Default."""
        from core.settings import Settings
        from ui.settings_bind import setting_for_combo
        from ui.widget_state import fetch

        defaults = Settings.defaults()
        window = self._window()
        for view in window._views:
            for key, row in view._scale_rows.items():
                with self.subTest(method=view.method_key, key=key):
                    expected = str(setting_for_combo(key, defaults.get(key)))
                    self.assertIn(expected, fetch(row, "_uvr_values"))
                    self.assertEqual(str(fetch(row, "_uvr_default", None)), expected)

    def test_model_parameter_sliders_mark_their_defaults(self) -> None:
        from types import SimpleNamespace

        from bundled.constants import VR_ARCH_TYPE
        from ui.dialogs.model_params import _ParamDialog
        from ui.widget_state import fetch

        model_data = SimpleNamespace(
            process_method=VR_ARCH_TYPE,
            model_path="model.pth",
            model_name="model",
            model_display_label="Model",
            repo=None,
        )
        dialog = _ParamDialog(None, None, model_data)
        for row, expected in (
            (dialog.balance_row, "0"),
            (dialog.nout_row, "32"),
            (dialog.nout_lstm_row, "128"),
        ):
            with self.subTest(row=row.get_title()):
                self.assertEqual(str(fetch(row, "_uvr_default", None)), expected)

    def test_free_numbers_are_spin_rows(self) -> None:
        from gi.repository import Adw

        window = self._window()
        expected = {
            "vr": ["aggression_setting"],
            "demucs": ["shifts"],
        }
        for view in window._views:
            prefix = view.secondary_prefix
            keys = list(expected.get(prefix or "", []))
            if prefix:
                keys += [
                    f"{prefix}_{slot}_secondary_model_scale"
                    for slot in ("voc_inst", "other", "bass", "drums")
                ]
            for key in keys:
                with self.subTest(method=view.method_key, key=key):
                    self.assertIsInstance(view._spin_rows.get(key), Adw.SpinRow)
                    self.assertNotIn(key, view._scale_rows)

    def test_spin_edits_persist_with_the_setting_type(self) -> None:
        window = self._window()
        views = {view.secondary_prefix: view for view in window._views}
        cases = (
            ("vr", "aggression_setting", 17, int),
            ("demucs", "shifts", 4, int),
            ("mdx", "mdx_voc_inst_secondary_model_scale", 0.42, float),
        )
        for prefix, key, value, kind in cases:
            with self.subTest(key=key):
                view = views[prefix]
                view._spin_rows[key].set_value(value)
                stored = window.settings.get(key)
                self.assertIsInstance(stored, kind)
                self.assertEqual(stored, value)

    def test_load_shows_the_stored_value(self) -> None:
        window = self._window()
        view = next(v for v in window._views if v.secondary_prefix == "vr")
        window.settings.set("aggression_setting", 23)
        window.settings.set("vr_other_secondary_model_scale", 0.35)
        view.load()
        self.assertEqual(view._spin_rows["aggression_setting"].get_value(), 23)
        self.assertAlmostEqual(view._spin_rows["vr_other_secondary_model_scale"].get_value(), 0.35)


if __name__ == "__main__":
    unittest.main()
