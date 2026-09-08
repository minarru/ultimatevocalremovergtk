"""Output summary stays connected to the existing stem-selection controls."""

import unittest

from tests.private_gtk import require_private_gtk


class OutputStemsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        require_private_gtk()

    def setUp(self):
        from gi.repository import Adw

        from core.settings import Settings
        from ui.widgets.output_stems import OutputStemsSection
        from ui.widgets.stem_only import SaveStemsSection

        self.settings = Settings.defaults()
        self.section = SaveStemsSection(settings=self.settings, on_changed=self.changed)
        self.host = Adw.PreferencesGroup()
        self.output = OutputStemsSection(self.section, self.host, use_direct_controls=False)

    def changed(self):
        self.section.persist_to_settings()
        self.output.refresh()

    def test_exclusive_edit_updates_summary_and_existing_settings(self):
        from ui.widgets.rows import set_combo_value

        self.section.configure_exclusive(
            primary_stem="Vocals",
            secondary_stem="Instrumental",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        self.output.refresh(model_name="Vocal model", workload="1 pass · 2 outputs")
        self.assertEqual(self.output.count.get_label(), "2 files")
        self.assertCountEqual(
            (self.output.row.get_subtitle() or "").split(", "), ["Vocals", "Instrumental"]
        )
        self.assertTrue(self.output.row.get_sensitive())
        body = self.output.dialog.get_child()
        assert body is not None
        self.assertTrue(self.section._exclusive_row.is_ancestor(body))
        vocals = next(
            option.name
            for option in self.section.presentation().choices
            if option.display_label == "Vocals"
        )
        set_combo_value(self.section._exclusive_row, vocals)
        self.assertTrue(self.settings.process.stem_focus)
        self.assertIn("Vocals", self.output.row.get_subtitle() or "")
        self.assertEqual(self.output.count.get_label(), "1 file")
        self.assertEqual(self.output.result_count.get_label(), "1 file per input")

    def test_subset_custom_selection_and_demucs_focus_are_retained(self):
        from bundled.constants import ALL_STEMS
        from ui.widgets.rows import set_combo_value

        self.section.configure_subset(
            stems=["Vocals", "Drums", "Bass", "Other"],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        self.section._subset_mode = "custom"
        self.section._set_custom_selection({"Drums", "Bass"})
        self.changed()
        self.assertEqual(self.output.count.get_label(), "2 files")
        self.assertIn("Drums", self.output.row.get_subtitle() or "")

        self.assertIn("Bass", self.output.row.get_subtitle() or "")
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, "Vocals", "Drums", "Bass", "Other"],
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        set_combo_value(self.section._demucs_focus_row, "Drums")
        self.assertTrue(self.section._demucs_export_row.get_visible())
        self.assertIn("Drums", self.output.row.get_subtitle() or "")

    def test_custom_checkbox_applies_without_save_and_leaves_dialog_open(self):
        from gi.repository import Adw

        self.section.configure_subset(
            stems=["Vocals", "Drums", "Bass", "Other"],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        self.output.refresh()
        parent = Adw.Window(content=self.host)
        self.addCleanup(parent.close)
        parent.present()
        self.output.row.emit("activated")
        self.section._custom_row.emit("activated")
        self.addCleanup(self.output.dialog.close)
        self.addCleanup(self.section._custom_dialog.close)
        self.assertEqual(self.settings.get("mdx_stems_selected"), [])
        self.section._custom_checks[self.section._subset_token_id("Drums")].set_active(True)
        self.assertEqual(self.settings.get("mdx_stems_selected"), ["Drums"])
        self.assertIn("Drums", self.output.row.get_subtitle() or "")
        self.assertEqual(self.output.count.get_label(), "1 file")
        self.assertIsNotNone(self.section._custom_dialog.get_root())
        self.section._custom_checks[self.section._subset_token_id("Bass")].set_active(True)
        self.assertEqual(self.settings.get("mdx_stems_selected"), ["Drums", "Bass"])
        self.assertEqual(self.output.count.get_label(), "2 files")

    def test_missing_model_disables_action_and_role_review_remains_reachable(self):
        self.section.configure_hidden()
        self.output.refresh()
        self.assertFalse(self.output.row.get_sensitive())
        self.assertFalse(self.output.count.get_visible())
        self.section.configure_exclusive(
            primary_stem="Vocals",
            secondary_stem="Instrumental",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        self.section.require_refresh_repick("raw:missing")
        self.output.refresh()
        self.assertTrue(self.output.row.get_sensitive())
        self.assertFalse(self.output.count.get_visible())
        self.assertTrue(self.section.selection_warning_row.get_visible())
        body = self.output.dialog.get_child()
        assert body is not None
        self.assertTrue(self.section.selection_warning_row.is_ancestor(body))

    def test_custom_dialog_reflects_quick_choice_without_applying_on_open(self):
        from unittest.mock import patch

        from bundled.constants import ALL_STEMS
        from core.stem_selection import _QUICK_INSTRUMENTAL, _QUICK_VOCALS
        from ui.widgets.rows import set_combo_value

        self.section.configure_subset(
            stems=["Vocals", "Drums", "Bass", "Other"],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        for choice in (_QUICK_VOCALS, _QUICK_INSTRUMENTAL):
            set_combo_value(self.section._quick_row, choice)
            focus = self.settings.process.stem_focus
            with patch("ui.widgets.stem_only.present_modal_dialog"):
                self.section._open_custom_stems_dialog()
            self.assertEqual(self.settings.process.stem_focus, focus)
            self.assertFalse(self.section._custom_checks[ALL_STEMS].get_active())
            vocal = self.section._custom_checks[self.section._subset_token_id("Vocals")]
            self.assertEqual(vocal.get_active(), choice == _QUICK_VOCALS)
            self.section._custom_checks[ALL_STEMS].set_active(True)
            self.assertEqual(self.settings.process.stem_focus, "")
            self.assertEqual(self.output.count.get_label(), "4 files")
            self.section._custom_checks[ALL_STEMS].set_active(False)
            self.assertTrue(self.section._custom_checks[ALL_STEMS].get_active())


class DirectOutputStemsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        require_private_gtk()

    def setUp(self):
        from gi.repository import Adw

        from core.settings import Settings
        from ui.widgets.output_stems import OutputStemsSection
        from ui.widgets.stem_only import SaveStemsSection

        self.settings = Settings.defaults()
        self.edits = 0
        self.section = SaveStemsSection(settings=self.settings, on_changed=self.changed)
        self.host = Adw.PreferencesGroup()
        self.output = OutputStemsSection(self.section, self.host)

    def changed(self):
        self.edits += 1
        self.section.persist_to_settings()
        self.output.refresh()

    def pair(self):
        self.section.set_model_context("mdx:vocal-model")
        self.section.configure_exclusive(
            primary_stem="Vocals",
            secondary_stem="Instrumental",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        self.output.refresh(model_name="Vocal model")

    def check(self, label: str):
        return next(
            check for row, check in self.output._output_rows.values() if row.get_title() == label
        )

    def test_pair_checkboxes_apply_and_reject_last_deselection(self):
        self.pair()
        vocals = self.check("Vocals")
        instrumental = self.check("Instrumental")
        self.assertTrue(vocals.get_active())
        self.assertTrue(instrumental.get_active())
        instrumental.set_active(False)
        focus = self.settings.process.stem_focus
        self.assertTrue(focus)
        self.assertEqual(self.edits, 1)
        self.assertEqual(self.output.count.get_label(), "1 stem")
        vocals.set_active(False)
        self.assertTrue(vocals.get_active())
        self.assertFalse(instrumental.get_active())
        self.assertEqual(self.settings.process.stem_focus, focus)
        self.assertEqual(self.edits, 1)
        self.output._select_all.emit("clicked")
        self.assertEqual(self.settings.process.stem_focus, "")
        self.assertTrue(instrumental.get_active())

    def test_search_does_not_drop_hidden_selected_outputs(self):
        stems = [f"Part {i}" for i in range(12)]
        self.section.configure_subset(
            stems=stems,
            show_quick_export=False,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.settings.mdx.stems_selected = ["Part 0", "Part 11"]
        self.section.sync_from_settings()
        self.output.refresh()
        self.output._search.set_text("Part 11")
        self.output._filter_outputs()
        self.assertEqual(self.settings.mdx.stems_selected, ["Part 0", "Part 11"])
        self.assertEqual(self.output.count.get_label(), "2 stems")
        self.check("Part 11").set_active(False)
        self.assertEqual(self.settings.mdx.stems_selected, ["Part 0"])
        self.output._select_all.emit("clicked")
        self.assertEqual(self.settings.mdx.stems_selected, [])
        self.assertTrue(all(check.get_active() for _, check in self.output._output_rows.values()))
        self.output._search.set_text("absent")
        self.output._filter_outputs()
        self.assertTrue(self.output._no_matches.get_visible())
        self.assertEqual(self.output.count.get_label(), "12 stems")

    def test_old_model_checkbox_cannot_edit_new_model(self):
        self.pair()
        stale = self.check("Vocals")
        self.section.set_model_context("mdx:drum-model")
        self.section.configure_exclusive(
            primary_stem="Drums",
            secondary_stem="No Drums",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        self.output.refresh()
        stale.set_active(False)
        self.assertEqual(self.edits, 0)
        self.assertEqual(self.settings.process.stem_focus, "")
        self.assertEqual(self.output.count.get_label(), "2 stems")

    def test_missing_role_is_reviewed_without_persisting_on_open(self):
        self.pair()
        self.settings.process.stem_focus = "raw:missing"
        self.section.require_refresh_repick("raw:missing")
        self.output.refresh()
        self.assertTrue(self.section.repick_required)
        self.assertTrue(self.output._review.get_visible())
        self.assertEqual(self.edits, 0)
        self.assertEqual(self.settings.process.stem_focus, "raw:missing")
        self.check("Vocals").set_active(True)
        self.assertFalse(self.section.repick_required)
        self.assertEqual(self.edits, 1)
        self.assertEqual(self.output.count.get_label(), "1 stem")

    def test_combined_mode_restores_native_subset_without_nested_dialog(self):
        from tests.stem_control_cases import KARAOKE_THREE, manifest_routes
        from ui.widgets.rows import set_combo_value

        routes = manifest_routes(KARAOKE_THREE)
        self.section.set_model_context(KARAOKE_THREE)
        self.section.configure_subset(
            stems=[r.native.raw for r in routes if r.native],
            show_quick_export=False,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            routes=routes,
        )
        self.settings.mdx.stems_selected = ["backing_vocal"]
        self.settings.process.stem_focus = "vocal.backing"
        self.section.sync_from_settings()
        self.output.refresh()
        assert self.output.controls is not None
        combined_id = self.output.controls.snapshot().modes[-1][0]
        set_combo_value(self.output._mode, combined_id)
        self.assertEqual(self.settings.process.stem_focus, "mix.instrumental_with_backing_vocals")
        self.assertEqual(self.settings.mdx.stems_selected, [])
        self.assertEqual(self.output.count.get_label(), "1 stem")
        self.assertIsNone(self.section._custom_dialog.get_root())
        set_combo_value(self.output._mode, "native_subset")
        self.assertEqual(self.settings.process.stem_focus, "vocal.backing")
        self.assertEqual(self.settings.mdx.stems_selected, ["backing_vocal"])

    def test_model_option_refresh_does_not_replace_selection(self):
        self.section.configure_subset(
            stems=["Vocals", "Drums", "Bass", "Other"],
            show_quick_export=False,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.settings.mdx.stems_selected = ["Drums"]
        self.section.sync_from_settings()
        self.output.refresh()
        self.assertFalse(self.output._additional.get_visible())
        self.settings.mdx.is_mdx_include_stem_complement = True
        self.output.refresh()
        self.assertTrue(self.output._additional.get_visible())
        self.assertEqual(self.settings.mdx.stems_selected, ["Drums"])
        self.assertEqual(self.edits, 0)
        self.settings.mdx.is_mdx_include_stem_complement = False
        self.output.refresh()
        self.assertFalse(self.output._additional.get_visible())

    def test_raw_demucs_review_can_explicitly_restore_all(self):
        from types import SimpleNamespace

        from bundled.constants import ALL_STEMS
        from core.stems import model_stem_routes

        model = SimpleNamespace(
            canonical_id="demucs:unreviewed_controls",
            demucs_source_list=["one", "two", "three"],
            demucs_stem_count=3,
            primary_stem="one",
            secondary_stem="No one",
            is_vocal_split_model=False,
            mdx_model_stems=[],
        )
        routes = model_stem_routes(model)
        self.section.set_model_context(model.canonical_id)
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, "one", "two", "three"],
            routes=routes,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            demucs_stem_count=3,
        )
        self.settings.demucs.stems = "two"
        self.settings.process.stem_focus = "raw:no two"
        self.section.sync_from_settings()
        self.output.refresh()
        self.assertTrue(self.section.repick_required)
        self.assertTrue(self.output._select_all.get_visible())
        self.assertTrue(self.output._select_all.get_sensitive())
        self.output._select_all.emit("clicked")
        self.assertFalse(self.section.repick_required)
        self.assertEqual(self.settings.demucs.stems, ALL_STEMS)
        self.assertEqual(self.settings.process.stem_focus, "")
        self.assertEqual(self.output.count.get_label(), "3 stems")

    def test_demucs_native_checkboxes_save_subset_and_restore_all(self):
        from bundled.constants import ALL_STEMS
        from tests.stem_control_cases import manifest_routes

        routes = manifest_routes("demucs:htdemucs_6s")
        self.section.set_model_context("demucs:htdemucs_6s")
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, *[r.native.raw for r in routes if r.native]],
            routes=routes,
            demucs_stem_count=6,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.section.sync_from_settings()
        self.output.refresh(model_name="Demucs six-stem model")
        self.assertFalse(self.output._focus.get_visible())
        self.assertTrue(self.output._select_all.get_visible())
        for route in routes:
            if route.native and route.native.raw not in {"vocals", "drums", "bass"}:
                self.check(route.label).set_active(False)
        self.assertCountEqual(self.settings.demucs.stems_selected, ["vocals", "drums", "bass"])
        self.assertEqual(self.settings.demucs.stems, ALL_STEMS)
        self.assertEqual(self.settings.process.stem_focus, "")
        self.assertEqual(self.output.result_count.get_label(), "3 stems per input")
        self.assertFalse(self.output._result_names.get_visible())
        self.section.sync_from_settings()
        self.output.refresh()
        self.assertEqual(self.output.count.get_label(), "3 stems")
        self.output._select_all.emit("clicked")
        self.assertEqual(self.settings.demucs.stems_selected, [])
        self.assertEqual(self.output.result_count.get_label(), "6 stems per input")
