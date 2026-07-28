"""The vocal-split section lives on the run pages, not per-architecture."""

from __future__ import annotations

import os
import unittest


class MethodViewNoLongerOwnsItTests(unittest.TestCase):
    """Headless: the attribute is gone from the view class entirely."""

    def test_method_view_has_no_vocal_split_expander(self):
        from ui.views.base import MethodView

        self.assertFalse(hasattr(MethodView, "voc_split_expander"))

    def test_base_module_no_longer_builds_the_section(self):
        import inspect

        from ui.views import base

        source = inspect.getsource(base)
        self.assertNotIn("voc_split_expander", source)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ProcessingGroupPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.vocal-split-place")
        cls._app.register()

    def test_main_window_processing_group_hosts_the_row(self):
        from ui.widgets.vocal_split_row import VocalSplitRow
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        self.assertIsInstance(window.vocal_split_row, VocalSplitRow)

    def test_ensemble_page_processing_group_hosts_the_row(self):
        from ui.ensemble.window import EnsemblePage
        from ui.widgets.vocal_split_row import VocalSplitRow
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        ensemble = window._ensemble_page
        self.assertIsInstance(ensemble, EnsemblePage)
        self.assertIsInstance(ensemble.vocal_split_row, VocalSplitRow)

    def test_the_two_pages_share_one_set_of_values(self):
        """They are global keys: editing one page must be visible on the other."""
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        window.vocal_split_row.deverb_switch.set_active(True)
        window.vocal_split_row.persist_to_settings(window.settings)
        ensemble_row = window._ensemble_page.vocal_split_row
        ensemble_row.apply_from_settings(window.settings)
        self.assertTrue(ensemble_row.deverb_switch.get_active())

    def test_audio_tools_does_not_get_the_row(self):
        """Audio Tools runs no separations, so the globals do not belong there."""
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        audio_tools = window._audio_tools_page
        self.assertFalse(hasattr(audio_tools, "vocal_split_row"))


if __name__ == "__main__":
    unittest.main()
