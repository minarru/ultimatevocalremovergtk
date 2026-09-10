"""Real Ensemble widgets preserve selection ownership and expose the new layout."""

import os
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.settings import Settings
from tests.private_gtk import require_private_gtk
from tests.test_ensemble_stem_selection import route


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "GTK needs a display"
)
class EnsemblePageDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        require_private_gtk()

    def setUp(self):
        from core.access_policy import access_policy
        from ui.window import MainWindow

        scratch = self.enterContext(tempfile.TemporaryDirectory())
        settings = Settings.defaults()
        settings.path = str(Path(scratch) / "settings.json")
        settings.ui.window_maximized = False
        self.enterContext(access_policy(allow_network=False, allow_metadata_writes=False))
        self.enterContext(patch("ui.context.Settings.load", return_value=settings))
        self.enterContext(patch("ui.ensemble.window.estimate_workload", return_value=None))
        self.window: Any = MainWindow()
        self.addCleanup(self.window._unsubscribe_model_events)
        self.addCleanup(self.window.set_visible, False)
        self.page: Any = self.window._ensemble_page
        self.page._active = True
        self.enterContext(
            patch.object(self.page, "_selected_model_tags", return_value=["mdx:a", "mdx:b"])
        )
        self.enterContext(
            patch.object(self.page, "_effective_selected_models", return_value=["mdx:a", "mdx:b"])
        )
        routes = (
            route("vocal.vocals", "Vocals"),
            route("instrument.drums", "Drums"),
            route("instrument.bass", "Bass"),
        )
        self.enterContext(
            patch.object(self.page, "_dry_resolved_member_routes", return_value=(routes, routes))
        )

    def test_multi_checkbox_reaches_run_settings_without_touching_separation_subset(self):
        page = self.page
        page.settings.ensemble.main_stem = "mode.multi_stem"
        page.settings.mdx.stems_selected = ["keep"]
        page._rebuild_stem_only_toggles()
        page.output_stems._output_rows["vocal.vocals"][1].set_active(False)
        self.assertEqual(
            page.settings.ensemble.stems_selected, ["instrument.drums", "instrument.bass"]
        )
        page._flush_run_settings()
        self.assertEqual(page.settings.process.stem_focus, "")
        self.assertEqual(page.settings.mdx.stems_selected, ["keep"])
        self.assertEqual(page.output_stems.count.get_label(), "2 stems")

    def test_member_reconciliation_refreshes_available_output_roles(self):
        from types import SimpleNamespace

        page = self.page
        page.settings.ensemble.main_stem = "mode.multi_stem"
        page._rebuild_stem_only_toggles()
        replacement = (route("instrument.piano", "Piano"),)
        projection = SimpleNamespace(reconcile_after_render=False, placeholder="")
        with (
            patch.object(page, "_acquire_member_projection", return_value=projection),
            patch.object(
                page,
                "_render_member_projection",
                side_effect=lambda *_: setattr(
                    page._dry_resolved_member_routes, "return_value", (replacement, replacement)
                ),
            ),
        ):
            page._reconcile_member_list(["mdx:a", "mdx:b"])
        self.assertEqual(
            [choice.id for choice in page.output_stems.controls.snapshot().choices],
            ["instrument.piano"],
        )

    def test_custom_algorithms_remain_inline_after_member_refresh(self):
        from ui.widgets.rows import set_combo_value

        page = self.page
        page.settings.ensemble.main_stem = "mode.multi_stem"
        page._refresh_ensemble_type_values()
        self.assertFalse(page.primary_algo_row.get_visible())
        set_combo_value(page.preset_row, "Custom")
        self.assertTrue(page.primary_algo_row.get_visible())
        self.assertFalse(page.secondary_algo_row.get_visible())
        page._update_models_summary()
        self.assertTrue(page.primary_algo_row.get_visible())

    def test_pair_dialog_keeps_existing_focus_encoding(self):
        page = self.page
        page.settings.ensemble.main_stem = "pair.vocals_instrumental"
        self.enterContext(
            patch.object(page, "_resolve_ensemble_semantics_model", return_value=None)
        )
        page._rebuild_stem_only_toggles()
        choices = page.output_stems.controls.snapshot().choices
        vocal = next(choice for choice in choices if str(choice.route.role) == "vocal.vocals")
        page.output_stems._output_rows[vocal.id][1].set_active(False)
        self.assertEqual(page.settings.process.stem_focus, "mix.instrumental")
        self.assertEqual(page.settings.ensemble.stems_selected, [])
        self.assertEqual(page.output_stems.count.get_label(), "1 stem")
        # A different tab writes the shared focus after this page's edit was saved.
        page.settings.process.stem_focus = "vocal.vocals"
        page._flush_run_settings()
        self.assertEqual(page.settings.process.stem_focus, "mix.instrumental")

    def test_saving_multi_ensemble_does_not_capture_separation_focus(self):
        page = self.page
        page.settings.ensemble.main_stem = "mode.multi_stem"
        page.settings.process.stem_focus = "mix.instrumental"
        page.settings.ensemble.stems_selected = ["instrument.drums"]
        with patch("core.ensemble_service.EnsembleService") as service:
            page._do_save_ensemble("My ensemble", ["mdx:a", "mdx:b"])
        saved = service.return_value.create.call_args.kwargs
        self.assertEqual(saved["stem_focus"], "")
        self.assertEqual(saved["stems_selected"], ["instrument.drums"])

    def test_output_settings_live_together_and_inactive_edits_do_not_persist(self):
        page = self.page
        self.assertTrue(page.format_row.is_ancestor(page.stems_group))
        self.assertTrue(page.save_all_row.is_ancestor(page.stems_group))
        page.settings.ensemble.main_stem = "mode.multi_stem"
        page._rebuild_stem_only_toggles()
        page._active = False
        page.output_stems._output_rows["vocal.vocals"][1].set_active(False)
        self.assertEqual(page.settings.ensemble.stems_selected, [])

    def test_real_window_stacks_ensemble_groups_when_narrow(self):
        from gi.repository import GLib, Gtk

        self.enterContext(patch.object(self.page, "_ensure_member_list"))
        self.window.content_stack.set_visible_child_name("ensemble")
        self.window.set_default_size(1100, 700)
        self.window.present()

        def wait_for(predicate: Callable[[], bool]) -> None:
            deadline = time.monotonic() + 15
            while not predicate():
                self.assertLess(time.monotonic(), deadline, "Ensemble layout did not settle")
                GLib.MainContext.default().iteration(False)
                time.sleep(0.005)

        wait_for(lambda: self.page.columns_box.get_width() > 900)
        self.assertEqual(self.page.columns_box.get_orientation(), Gtk.Orientation.HORIZONTAL)
        self.window.unmaximize()
        self.window.set_default_size(700, 700)
        wait_for(lambda: self.page.columns_box.get_orientation() == Gtk.Orientation.VERTICAL)
        self.assertLessEqual(self.page._col_start.get_width(), self.window.get_width())
        self.assertLessEqual(self.page._col_end.get_width(), self.window.get_width())
