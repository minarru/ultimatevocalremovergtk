"""Ensemble interaction work scales with actions, not checkbox count."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import Mock, patch

from core import Settings
from tests.private_gtk import require_private_gtk


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class EnsemblePerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        Gtk.init()
        Adw.init()
        require_private_gtk()
        cls.Gtk = Gtk

    def page(self):
        from ui.ensemble.window import EnsemblePage

        page: Any = object.__new__(EnsemblePage)
        page.settings = Settings.defaults()
        page._loading = False
        page._models_write_gated = False
        page.saved_row = Mock()
        page._model_checks = {}
        page._update_models_dialog_status = Mock()
        page._update_models_summary = Mock()
        page._rebuild_stem_only_toggles = Mock()
        for tag in ("mdx:a", "mdx:b", "mdx:hidden"):
            check = self.Gtk.CheckButton()
            check.connect("toggled", page._on_model_toggled)
            page._model_checks[tag] = check
        page._visible_model_tags = Mock(return_value=["mdx:a", "mdx:b"])
        return page

    def test_select_and_clear_visible_members_recompute_once(self):
        page = self.page()
        with patch("ui.ensemble.window.set_combo_value"):
            for active, action in (
                (True, page._on_models_select_all),
                (False, page._on_models_clear),
            ):
                page.settings.ensemble.chosen_ensemble = "Saved preset"
                page._rebuild_stem_only_toggles.reset_mock()
                with patch.object(
                    page, "_persist_selected_models", wraps=page._persist_selected_models
                ) as persist:
                    action()
                self.assertEqual(page._model_checks["mdx:a"].get_active(), active)
                self.assertEqual(page._model_checks["mdx:b"].get_active(), active)
                self.assertFalse(page._model_checks["mdx:hidden"].get_active())
                self.assertEqual(
                    page.settings.ensemble.selected_models, ["mdx:a", "mdx:b"] if active else []
                )
                self.assertNotEqual(page.settings.ensemble.chosen_ensemble, "Saved preset")
                persist.assert_called_once()
                page._rebuild_stem_only_toggles.assert_called_once()

    def test_noop_bulk_action_preserves_saved_preset(self):
        page = self.page()
        page.settings.ensemble.chosen_ensemble = "Saved preset"
        page._on_models_clear()
        self.assertEqual(page.settings.ensemble.chosen_ensemble, "Saved preset")
        page._rebuild_stem_only_toggles.assert_not_called()

    def test_deferred_load_does_not_resolve_models_or_mutate_saved_members(self):
        page = self.page()
        page.settings.ensemble.selected_models = ["mdx:missing"]
        page._sync_shared_from_settings = Mock()
        page._refresh_pair_choices = Mock()
        page._acquire_member_projection = Mock()
        page.load(defer_models=True)
        self.assertEqual(page.settings.ensemble.selected_models, ["mdx:missing"])
        page._refresh_pair_choices.assert_not_called()
        page._acquire_member_projection.assert_not_called()

    def test_reactivation_reuses_members_until_refresh_or_stem_change(self):
        from ui.ensemble.member_projection import project_members

        page = self.page()
        page._sync_shared_from_settings = Mock()
        page._refresh_pair_choices = Mock()
        page.vocal_split_row = Mock()
        page.models_dialog = Mock()
        page.models_dialog.get_mapped.return_value = False
        page._acquire_member_projection = Mock(
            return_value=project_members((), [], pair_id="", eligible_ids=None)
        )
        page._render_member_projection = Mock()
        page.on_activated()
        page.on_activated()
        page._acquire_member_projection.assert_called_once()
        page.settings.mdx.stems = "Bass"
        page.on_activated()
        self.assertEqual(page._acquire_member_projection.call_count, 2)
        page.on_deactivated()
        page.refresh_models()
        self.assertEqual(page._acquire_member_projection.call_count, 2)
        page.on_activated()
        self.assertEqual(page._acquire_member_projection.call_count, 3)

    def test_opening_dialog_reuses_existing_check_widgets(self):
        from ui.ensemble.member_projection import project_members

        page = self.page()
        page._sync_shared_from_settings = Mock()
        page._acquire_member_projection = Mock(
            return_value=project_members((), [], pair_id="", eligible_ids=None)
        )
        page._render_member_projection = Mock()
        page._stem_pair_chosen = Mock(return_value=True)
        page.models_dialog = Mock()
        page.window = Mock()
        original_checks = dict(page._model_checks)
        page.on_activated()
        with patch("ui.ensemble.window.present_modal_dialog") as present:
            page._open_models_dialog()
            page._open_models_dialog()
        self.assertEqual(present.call_count, 2)
        self.assertEqual(page._model_checks, original_checks)
        page._acquire_member_projection.assert_called_once()

    def test_deferred_activation_loads_with_ensemble_method(self):
        from core.types import ProcessMethod

        page = self.page()
        page._sync_shared_from_settings = Mock()
        page.load(defer_models=True)
        with patch.object(page, "load") as load:
            page.on_activated()
        load.assert_called_once_with()
        self.assertEqual(page.settings.process.method, ProcessMethod.ENSEMBLE)

    def test_failed_member_acquisition_retries_on_next_activation(self):
        from ui.ensemble.member_projection import project_members

        page = self.page()
        page._sync_shared_from_settings = Mock()
        page._acquire_member_projection = Mock(
            return_value=project_members(
                (), [], pair_id="pair.vocals_instrumental", eligible_ids=None, load_error=True
            )
        )
        page._render_member_projection = Mock()
        page.on_activated()
        page.on_activated()
        self.assertEqual(page._acquire_member_projection.call_count, 2)
