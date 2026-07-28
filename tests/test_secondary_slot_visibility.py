"""Secondary stem slots that cannot affect the run are hidden, not dimmed."""

from __future__ import annotations

import os
import unittest

from bundled.constants import ALL_STEMS, ENSEMBLE_MODE, FOUR_STEM_ENSEMBLE


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SecondarySlotVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.secondary-slots")
        cls._app.register()

    def _window(self):
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window

    def _view(self, window, stack_name):
        return window._views_by_stack[stack_name]

    def test_mdx_hides_other_bass_drums_by_default(self):
        window = self._window()
        view = self._view(window, "mdx")
        view._sync_secondary_slot_visibility()
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertFalse(row.get_visible(), f"{slot} should be hidden")

    def test_the_vocals_instrumental_slot_is_always_visible(self):
        window = self._window()
        view = self._view(window, "mdx")
        view._sync_secondary_slot_visibility()
        for row in view._secondary_slot_rows["voc_inst"]:
            self.assertTrue(row.get_visible())

    def test_demucs_with_all_stems_shows_every_slot(self):
        window = self._window()
        window.settings.set("demucs_stems", ALL_STEMS)
        view = self._view(window, "demucs")
        view._sync_secondary_slot_visibility()
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertTrue(row.get_visible(), f"{slot} should be visible")

    def test_a_four_stem_ensemble_shows_every_slot_on_every_architecture(self):
        window = self._window()
        window.settings.set("chosen_process_method", ENSEMBLE_MODE)
        window.settings.set("ensemble_main_stem", FOUR_STEM_ENSEMBLE)
        for stack_name in ("vr", "mdx", "demucs"):
            view = self._view(window, stack_name)
            view._sync_secondary_slot_visibility()
            for slot in ("other", "bass", "drums"):
                for row in view._secondary_slot_rows[slot]:
                    self.assertTrue(row.get_visible(), f"{stack_name}/{slot}")

    def test_hidden_slots_keep_their_stored_values(self):
        window = self._window()
        window.settings.set("mdx_bass_secondary_model", "VR Arc: 1_HP-UVR")
        view = self._view(window, "mdx")
        view._sync_secondary_slot_visibility()
        self.assertEqual(
            window.settings.get("mdx_bass_secondary_model"), "VR Arc: 1_HP-UVR"
        )


if __name__ == "__main__":
    unittest.main()
