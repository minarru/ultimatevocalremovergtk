"""Secondary stem slots that cannot affect the run are hidden, not dimmed."""

from __future__ import annotations

import os
import typing
import unittest

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
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

    def _select_installed_model(self, window: typing.Any, view: typing.Any, model_id: str) -> None:
        from core.model_identity import ModelIdentityService
        from ui.widgets.rows import set_combo_value

        record = ModelIdentityService(window.context.repo).lookup(model_id)
        if not record.installed:
            self.skipTest(f"{record.id} not installed")
        self.assertTrue(
            set_combo_value(view.model_row, record.id),
            f"installed picker item missing: {record.id!r} ({record.display!r})",
        )

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
        window.settings.set("ensemble_main_stem", "mode.four_stem")
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
        self.assertEqual(window.settings.get("mdx_bass_secondary_model"), "VR Arc: 1_HP-UVR")

    def test_native_demucs_checkbox_edit_re_syncs_full_source_slot_visibility(self):
        """Migrating legacy focus through the checkbox restores four-source slots.

        Native subsets filter saved files while Demucs keeps its all-source
        processing branch. The checkbox callback must both persist that branch
        and refresh the existing option rows.
        """
        window = self._window()
        window.settings.set("chosen_process_method", DEMUCS_ARCH_TYPE)
        window.settings.demucs.stems = "bass"
        window.settings.demucs.stems_selected = []
        window.settings.process.stem_focus = "instrument.bass"
        view = self._view(window, "demucs")
        self._select_installed_model(window, view, "demucs:hdemucs_mmi")
        # Restore the changed settings even if the installed model was already
        # selected when this reused view was constructed.
        view.load()
        self.assertEqual(view.save_stems.mode, "demucs")
        self.assertEqual(window.settings.demucs.stems, "bass")
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertFalse(row.get_visible(), f"{slot} should start hidden for legacy focus")

        output = view.output_stems
        controls = output.controls
        self.assertIsNotNone(controls)
        drums = next(
            choice
            for choice in controls.snapshot().choices
            if choice.route.native and choice.route.native.raw == "drums"
        )
        output._output_rows[drums.id][1].set_active(True)
        self.assertEqual(window.settings.demucs.stems_selected, ["drums", "bass"])
        self.assertEqual(window.settings.demucs.stems, ALL_STEMS)
        self.assertEqual(window.settings.process.stem_focus, "")
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertTrue(
                    row.get_visible(), f"{slot} should be visible for native-subset processing"
                )

        output._select_all.emit("clicked")
        self.assertEqual(window.settings.demucs.stems_selected, [])
        for slot in ("other", "bass", "drums"):
            for row in view._secondary_slot_rows[slot]:
                self.assertTrue(row.get_visible(), f"{slot} should stay visible for All Stems")

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
        window.settings.set("ensemble_main_stem", "mode.four_stem")

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
