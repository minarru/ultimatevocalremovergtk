"""Secondary stem slots that cannot affect the run are hidden, not dimmed."""

from __future__ import annotations
import typing

import os
import unittest

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    FOUR_STEM_ENSEMBLE,
    MDX_ARCH_TYPE,
)


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

    def _view(self, window: typing.Any, stack_name: typing.Any):
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
        # ``four_stem_secondaries_apply`` special-cases Ensemble Mode ahead of
        # ``demucs_stems`` -- force a known separation method regardless of
        # whatever a previous session left persisted on disk (the app writes
        # ``chosen_process_method='Ensemble Mode'`` whenever you quit on the
        # Ensemble tab).
        window.settings.set("chosen_process_method", DEMUCS_ARCH_TYPE)
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

    def test_the_real_demucs_stem_focus_combo_re_syncs_slot_visibility(self):
        """Regression: changing focus through the widget must re-sync slots.

        Drives the real ``Adw.ComboRow`` widgets a user interacts with
        (model picker, then stem-focus picker) rather than calling
        ``_sync_secondary_slot_visibility`` directly, so this exercises the
        ``_on_demucs_focus_changed`` -> ``_notify`` ->
        ``_on_save_stems_changed`` wiring, not just the predicate.
        """
        from ui.widgets.rows import set_combo_value

        window = self._window()
        # ``four_stem_secondaries_apply`` special-cases Ensemble Mode ahead of
        # ``demucs_stems`` -- force a known separation method regardless of
        # whatever a previous session left persisted on disk (the app writes
        # ``chosen_process_method='Ensemble Mode'`` whenever you quit on the
        # Ensemble tab).
        window.settings.set("chosen_process_method", DEMUCS_ARCH_TYPE)
        # Selecting a model does not reset ``demucs_stems`` -- ``configure_demucs``
        # only (re)populates the focus combo's items; ``sync_from_settings`` then
        # reflects whatever is already stored back into the combo without writing
        # it (see ``SaveStemsSection._sync_demucs_from_settings``). So the starting
        # "all stems" state below must be set explicitly, or this test would only
        # be checking whatever a previous run (or a stale data.pkl) left behind.
        window.settings.set("demucs_stems", ALL_STEMS)
        view = self._view(window, "demucs")

        # Pick a real installed-metadata Demucs model so the stem-focus combo
        # is populated (``configure_demucs`` only runs once a model resolves).
        if not set_combo_value(view.model_row, "v4 | hdemucs_mmi"):
            self.skipTest("v4 | hdemucs_mmi not installed (downloaded weights only)")
        self.assertEqual(view.save_stems.mode, "demucs")
        self.assertEqual(window.settings.get("demucs_stems"), ALL_STEMS)
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertTrue(row.get_visible(), f"{slot} should start visible")

        focus_row = view.save_stems._demucs_focus_row
        self.assertTrue(set_combo_value(focus_row, "focus_vocals"))
        self.assertEqual(window.settings.get("demucs_stems"), "Vocals")
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertFalse(
                    row.get_visible(),
                    f"{slot} should hide once the real combo drops to Vocals-only",
                )

    def test_the_options_sheet_re_syncs_reused_views_on_update_context(self):
        """Regression: the sheet reuses view instances across opens.

        Writes ``chosen_process_method`` / ``ensemble_main_stem`` the way
        ``ui/ensemble/window.py`` does, then calls
        ``ModelOptionsSheet.update_context`` (not the sync method directly)
        and checks the reused MDX view picks up the new visibility.
        """
        from ui.model_options import OPEN_CONTEXT_ENSEMBLE
        from ui.model_options.sheet import ModelOptionsSheet

        window = self._window()
        sheet = ModelOptionsSheet(
            window,
            views=window._views,
            views_by_stack=window._views_by_stack,
            settings=window.settings,
        )
        mdx_view = self._view(window, "mdx")
        mdx_view._sync_secondary_slot_visibility()
        for slot in ("other", "bass", "drums"):
            for row in mdx_view._secondary_slot_rows[slot]:
                self.assertFalse(row.get_visible(), f"{slot} should start hidden")

        # Same two settings.set calls ui/ensemble/window.py makes: on_activated()
        # sets chosen_process_method, _on_main_stem_changed sets the stem pair.
        window.settings.set("chosen_process_method", ENSEMBLE_MODE)
        window.settings.set("ensemble_main_stem", FOUR_STEM_ENSEMBLE)

        sheet.update_context(
            context=OPEN_CONTEXT_ENSEMBLE,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )

        for slot in ("other", "bass", "drums"):
            for row in mdx_view._secondary_slot_rows[slot]:
                self.assertTrue(
                    row.get_visible(),
                    f"{slot} should be visible after update_context re-syncs",
                )


if __name__ == "__main__":
    unittest.main()
