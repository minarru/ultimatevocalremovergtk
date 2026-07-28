"""Vocal splitter + deverb row (global settings, hosted on the run pages)."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class VocalSplitRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.vocal-split-row")
        cls._app.register()

    def _settings(self, **overrides):
        from core.settings import SettingsModel

        settings = SettingsModel()
        for key, value in overrides.items():
            settings.set(key, value)
        return settings

    def _row(self):
        from ui.widgets.vocal_split_row import VocalSplitRow

        class _Repo:
            def karaoke_model_list(self, _settings):
                return ["VR Arc: UVR-BVE-4B"]

        self.changed = 0

        def on_changed():
            self.changed += 1

        return VocalSplitRow(_Repo(), on_changed)

    def test_applies_stored_switches(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=True, is_deverb_vocals=True)
        )
        self.assertTrue(row.split_switch.get_active())
        self.assertTrue(row.deverb_switch.get_active())

    def test_applying_settings_does_not_fire_on_changed(self):
        row = self._row()
        row.apply_from_settings(self._settings(is_set_vocal_splitter=True))
        self.assertEqual(self.changed, 0)

    def test_auto_expands_when_either_switch_is_on(self):
        row = self._row()
        row.apply_from_settings(self._settings(is_deverb_vocals=True))
        self.assertTrue(row.get_expanded())

    def test_stays_collapsed_when_both_switches_are_off(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertFalse(row.get_expanded())

    def test_never_auto_collapses_a_manually_opened_section(self):
        row = self._row()
        row.set_expanded(True)
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertTrue(row.get_expanded())

    def test_subtitle_reports_off_when_both_are_off(self):
        from ui.option_summaries import OFF

        row = self._row()
        row.apply_from_settings(self._settings(is_set_vocal_splitter=False))
        self.assertEqual(row.get_subtitle(), OFF)

    def test_subtitle_follows_a_switch_toggle(self):
        from ui.option_summaries import OFF

        row = self._row()
        row.apply_from_settings(self._settings(is_deverb_vocals=False))
        self.assertEqual(row.get_subtitle(), OFF)
        row.deverb_switch.set_active(True)
        self.assertIn("deverb", row.get_subtitle())

    def test_toggling_a_switch_fires_on_changed(self):
        row = self._row()
        row.apply_from_settings(self._settings())
        row.deverb_switch.set_active(True)
        self.assertGreaterEqual(self.changed, 1)

    def test_persist_writes_every_global_key(self):
        settings = self._settings()
        row = self._row()
        row.apply_from_settings(settings)
        row.split_switch.set_active(True)
        row.save_inst_switch.set_active(True)
        row.deverb_switch.set_active(True)
        row.persist_to_settings(settings)
        self.assertTrue(settings.get("is_set_vocal_splitter"))
        self.assertTrue(settings.get("is_save_inst_set_vocal_splitter"))
        self.assertTrue(settings.get("is_deverb_vocals"))
        self.assertIsNotNone(settings.get("deverb_vocal_opt"))

    def test_persist_does_not_clobber_an_unloaded_model_list(self):
        """Before the karaoke list is populated the stored tag must survive."""
        settings = self._settings(set_vocal_splitter="VR Arc: UVR-BVE-4B")
        row = self._row()
        row.apply_from_settings(settings)
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("set_vocal_splitter"), "VR Arc: UVR-BVE-4B")

    def test_dependent_rows_are_dimmed_while_their_switch_is_off(self):
        row = self._row()
        row.apply_from_settings(
            self._settings(is_set_vocal_splitter=False, is_deverb_vocals=False)
        )
        self.assertFalse(row.splitter_row.get_sensitive())
        self.assertFalse(row.save_inst_switch.get_sensitive())
        self.assertFalse(row.deverb_row.get_sensitive())

    def test_dependent_rows_wake_up_with_their_switch(self):
        row = self._row()
        row.apply_from_settings(self._settings())
        row.split_switch.set_active(True)
        self.assertTrue(row.splitter_row.get_sensitive())
        self.assertTrue(row.save_inst_switch.get_sensitive())
        self.assertFalse(row.deverb_row.get_sensitive())

    def test_expanding_populates_the_splitter_model_list(self):
        from ui.widgets.rows import combo_values

        row = self._row()
        row.apply_from_settings(self._settings())
        row.set_expanded(True)
        self.assertIn("UVR-BVE-4B", " ".join(combo_values(row.splitter_row)))


if __name__ == "__main__":
    unittest.main()
