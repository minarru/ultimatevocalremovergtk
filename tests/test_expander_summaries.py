"""Collapsed option expanders show their live state."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ExpanderSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.expander-summaries")
        cls._app.register()

    def _window(self):
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window

    def test_secondary_expander_reports_off_when_disabled(self):
        from ui.option_summaries import OFF

        window = self._window()
        window.settings.set("mdx_is_secondary_model_activate", False)
        view = window._views_by_stack["mdx"]
        view._sync_expander_summaries()
        self.assertEqual(view.secondary_expander.get_subtitle(), OFF)

    def test_secondary_expander_auto_expands_when_enabled(self):
        window = self._window()
        window.settings.set("mdx_is_secondary_model_activate", True)
        view = window._views_by_stack["mdx"]
        view._sync_expander_summaries()
        self.assertTrue(view.secondary_expander.get_expanded())

    def test_secondary_expander_stays_collapsed_when_disabled(self):
        window = self._window()
        window.settings.set("mdx_is_secondary_model_activate", False)
        view = window._views_by_stack["mdx"]
        view.secondary_expander.set_expanded(False)
        view._sync_expander_summaries()
        self.assertFalse(view.secondary_expander.get_expanded())

    def test_a_manually_opened_expander_is_never_auto_collapsed(self):
        window = self._window()
        window.settings.set("mdx_is_secondary_model_activate", False)
        view = window._views_by_stack["mdx"]
        view.secondary_expander.set_expanded(True)
        view._sync_expander_summaries()
        self.assertTrue(view.secondary_expander.get_expanded())

    def test_preproc_expander_reports_off_when_disabled(self):
        from ui.option_summaries import OFF

        window = self._window()
        window.settings.set("is_demucs_pre_proc_model_activate", False)
        view = window._views_by_stack["demucs"]
        view._sync_expander_summaries()
        self.assertEqual(view.preproc_expander.get_subtitle(), OFF)

    def test_views_without_a_preproc_section_are_skipped(self):
        window = self._window()
        view = window._views_by_stack["mdx"]
        self.assertFalse(hasattr(view, "preproc_expander"))
        view._sync_expander_summaries()  # must not raise

    # -- Wiring: reached through the real call sites, not the transform directly --

    def test_load_auto_expands_the_secondary_expander(self):
        """``load()`` itself must trigger auto-expand -- not just the helper.

        Every test above calls ``_sync_expander_summaries()`` directly, which
        would stay green even if ``load()`` stopped calling it. This one drives
        the behaviour through ``load()`` only, the way the options sheet
        actually opens a view.
        """
        window = self._window()
        view = window._views_by_stack["mdx"]
        window.settings.set("mdx_is_secondary_model_activate", True)
        view.secondary_expander.set_expanded(False)

        view.load()

        self.assertTrue(view.secondary_expander.get_expanded())

    def test_load_refreshes_the_secondary_subtitle(self):
        from ui.option_summaries import ON_NO_MODEL

        window = self._window()
        view = window._views_by_stack["mdx"]
        window.settings.set("mdx_is_secondary_model_activate", True)

        view.load()

        self.assertEqual(view.secondary_expander.get_subtitle(), ON_NO_MODEL)

    def test_toggling_the_real_switch_row_refreshes_the_subtitle(self):
        """The "keep subtitles live" wiring (Step 5), reached through the actual
        switch widget rather than by calling ``_refresh_expander_subtitles()``.
        """
        from ui.option_summaries import OFF, ON_NO_MODEL

        window = self._window()
        view = window._views_by_stack["mdx"]
        window.settings.set("mdx_is_secondary_model_activate", False)
        view.load()
        self.assertEqual(view.secondary_expander.get_subtitle(), OFF)

        switch_row = view._switch_rows["mdx_is_secondary_model_activate"]
        switch_row.set_active(True)

        self.assertEqual(view.secondary_expander.get_subtitle(), ON_NO_MODEL)

    # -- Regression: every control that feeds a summary must refresh it, not
    # just the activate switch (previously only ``_bind_switch_dependents``,
    # ``sync_dynamic_option_state`` and ``_sync_expander_summaries`` reached
    # ``_refresh_expander_subtitles`` -- combos, scales and non-activate
    # switches wrote through ``_touch_settings`` and left the subtitle stale).

    def test_picking_a_secondary_model_in_the_combo_updates_the_subtitle_live(self):
        from bundled.constants import CHOOSE_MODEL
        from ui.widgets.rows import set_combo_tag_values

        window = self._window()
        view = window._views_by_stack["mdx"]
        window.settings.set("mdx_net_model", CHOOSE_MODEL)
        window.settings.set("mdx_is_secondary_model_activate", True)
        view.load()  # auto-expands the row, which populates (and readies) the combo

        entry = next(
            e for e in view._model_combos if e["key"] == "mdx_voc_inst_secondary_model"
        )
        self.assertTrue(entry["ready"])
        # Seed a known option so the test doesn't depend on installed models.
        set_combo_tag_values(
            entry["row"],
            ["No Model Selected", ("MDX-Net: 14_SP-UVR-4B-44100-2", "14_SP-UVR-4B-44100-2")],
        )

        entry["row"].set_selected(1)  # real widget signal, not a direct settings write

        self.assertEqual(
            window.settings.get("mdx_voc_inst_secondary_model"),
            "MDX-Net: 14_SP-UVR-4B-44100-2",
        )
        self.assertIn("14_SP-UVR-4B-44100-2", view.secondary_expander.get_subtitle())

    def test_dragging_the_influence_scale_updates_the_subtitle_live(self):
        from bundled.constants import CHOOSE_MODEL
        from ui.widgets.rows import set_scale_row_float

        window = self._window()
        view = window._views_by_stack["mdx"]
        window.settings.set("mdx_net_model", CHOOSE_MODEL)
        window.settings.set("mdx_is_secondary_model_activate", True)
        window.settings.set(
            "mdx_voc_inst_secondary_model", "MDX-Net: 14_SP-UVR-4B-44100-2"
        )
        window.settings.set("mdx_voc_inst_secondary_model_scale", 0.9)
        view.load()
        self.assertIn("(0.90)", view.secondary_expander.get_subtitle())

        scale_row = view._scale_rows["mdx_voc_inst_secondary_model_scale"]
        set_scale_row_float(scale_row, 0.5)  # real slider signal

        self.assertEqual(window.settings.get("mdx_voc_inst_secondary_model_scale"), 0.5)
        self.assertIn("(0.50)", view.secondary_expander.get_subtitle())
        self.assertNotIn("(0.90)", view.secondary_expander.get_subtitle())

    def test_toggling_save_instrumental_mixture_updates_the_preproc_subtitle_live(self):
        from bundled.constants import CHOOSE_MODEL

        window = self._window()
        view = window._views_by_stack["demucs"]
        # No Demucs *main* model selected: a dry-check resolution of a real
        # >=3-stem model with the pre-process option active recurses inside
        # ``core.model_data.ModelData`` (a separate, pre-existing issue) --
        # irrelevant to this subtitle-wiring test, so keep it out of the way.
        window.settings.set("demucs_model", CHOOSE_MODEL)
        window.settings.set("is_demucs_pre_proc_model_activate", True)
        window.settings.set("demucs_pre_proc_model", "Demucs: v4: hdemucs_mmi")
        window.settings.set("is_demucs_pre_proc_model_inst_mix", False)
        view.load()
        self.assertNotIn(
            "saves instrumental mixture", view.preproc_expander.get_subtitle()
        )

        switch_row = view._switch_rows["is_demucs_pre_proc_model_inst_mix"]
        switch_row.set_active(True)  # real switch signal

        self.assertIn(
            "saves instrumental mixture", view.preproc_expander.get_subtitle()
        )


if __name__ == "__main__":
    unittest.main()
