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

    def test_tab_switch_refreshes_the_row_from_settings(self):
        """A value set on one page must show up on the other after activation.

        Drives the real activation path (``content_stack.set_visible_child_name``
        -> ``_on_visible_child`` -> ``target.on_activated()`` ->
        ``_activate_separation`` / ``EnsemblePage.on_activated``) rather than
        calling ``apply_from_settings`` directly -- a test that bypassed
        activation would pass even if the recurring sync never touched
        ``vocal_split_row``.
        """
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)

        # Separation -> settings: flip the switch as a user would.
        window.vocal_split_row.split_switch.set_active(True)
        self.assertTrue(window.settings.get("is_set_vocal_splitter"))

        # Activate Ensemble for real; its row must pick up the new value.
        window.content_stack.set_visible_child_name("ensemble")
        ensemble_row = window._ensemble_page.vocal_split_row
        self.assertTrue(
            ensemble_row.split_switch.get_active(),
            "Ensemble's vocal-split row is stale after tab activation",
        )

        # And the reverse direction: Ensemble -> settings -> Separation.
        ensemble_row.deverb_switch.set_active(True)
        self.assertTrue(window.settings.get("is_deverb_vocals"))

        window.content_stack.set_visible_child_name("separation")
        self.assertTrue(
            window.vocal_split_row.deverb_switch.get_active(),
            "Separation's vocal-split row is stale after tab activation",
        )

    def test_stale_row_does_not_clobber_an_unrelated_toggle(self):
        """Reproduces the clobber: a stale row overwrites all five keys on edit.

        Set a value on Separation, switch to Ensemble (which must refresh the
        row from settings), then toggle an *unrelated* control in the now-
        active Ensemble row. ``VocalSplitRow._on_row_changed`` persists all
        five fields on every edit, so if the row were still stale the
        unrelated toggle would silently revert ``is_set_vocal_splitter`` back
        to ``False``.
        """
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)

        window.vocal_split_row.split_switch.set_active(True)
        self.assertTrue(window.settings.get("is_set_vocal_splitter"))

        window.content_stack.set_visible_child_name("ensemble")
        ensemble_row = window._ensemble_page.vocal_split_row

        # An edit to a different control on the (now correctly synced) row.
        ensemble_row.deverb_switch.set_active(True)

        self.assertTrue(
            window.settings.get("is_set_vocal_splitter"),
            "toggling an unrelated control clobbered is_set_vocal_splitter "
            "back to False -- the row was stale when the edit landed",
        )


if __name__ == "__main__":
    unittest.main()
