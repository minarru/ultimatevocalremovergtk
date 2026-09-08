"""Native installed picker interactions and main-window selection adapter."""

from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from tests.test_model_picker_state import record


@unittest.skipUnless(
    os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY'), 'GTK needs a display'
)
class ModelPickerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Adw

        cls.app = Adw.Application(application_id='org.uvr.test.model-picker')
        cls.app.register()

    def setUp(self):
        from core.model_repository import ModelRepository
        from ui.model_picker import ModelPicker

        self.records = [
            record('vocals a'),
            record('vocals b'),
            record('broken', identity_complete=False),
        ]
        self.inventory = patch(
            'core.model_identity.ModelIdentityService.records',
            side_effect=lambda: tuple(self.records),
        )
        self.inventory.start()
        self.addCleanup(self.inventory.stop)
        self.choose = Mock(return_value=True)
        self.more = Mock()
        self.picker = ModelPicker(ModelRepository(), lambda: 'vr:vocals a', self.choose, self.more)
        from gi.repository import Adw

        self.parent_window = Adw.Window()
        self.parent_window.present()
        self.picker.present(self.parent_window)
        self.addCleanup(self.parent_window.set_visible, False)

    def test_search_reset_details_and_close_do_not_commit(self):
        from gi.repository import Gtk

        picker = self.picker
        picker.search.set_text('no results')
        picker._refresh()
        self.assertEqual(picker.rows, {})
        picker.reset()
        self.assertEqual(len(picker.rows), 2)
        picker.show_details(picker.models[0])
        self.assertEqual(picker.pages.get_visible_child_name(), 'details')
        picker.get('back', Gtk.Button).emit('clicked')
        self.assertEqual(picker.pages.get_visible_child_name(), 'browser')
        picker.dialog.close()
        self.choose.assert_not_called()

    def test_row_uses_exact_id_and_removed_or_unsupported_model_cannot_commit(self):
        self.picker.rows['vr:vocals b'].emit('activated')
        self.choose.assert_called_once_with('vr:vocals b')
        self.choose.reset_mock()
        self.records = [self.records[0], self.records[2]]
        self.picker.select('vr:vocals b')
        self.picker.select('vr:broken')
        self.choose.assert_not_called()

    def test_supported_only_and_get_more(self):
        from gi.repository import Gtk

        self.assertNotIn('vr:broken', self.picker.rows)
        self.picker.reset()
        self.assertNotIn('vr:broken', self.picker.rows)
        self.picker.get('more', Gtk.Button).emit('clicked')
        self.more.assert_called_once_with()
        self.choose.assert_not_called()

    def test_filter_sort_and_reopen_reuse_rows_without_stale_details(self):
        from gi.repository import Gtk

        picker = self.picker
        original = dict(picker.rows)
        picker.search.set_text('vocals b')
        picker._refresh()
        self.assertEqual(list(picker.rows), ['vr:vocals b'])
        self.assertFalse(original['vr:vocals a'].get_child_visible())
        self.assertTrue(original['vr:vocals b'].get_child_visible())
        self.assertIs(picker.rows['vr:vocals b'], original['vr:vocals b'])
        picker.reset()
        picker._reverse()
        self.assertEqual(list(picker.rows), ['vr:vocals b', 'vr:vocals a'])
        self.assertLess(original['vr:vocals b'].get_index(), original['vr:vocals a'].get_index())
        for model_id, row in original.items():
            self.assertIs(picker.rows[model_id], row)
        picker.dialog.close()
        picker.present(self.parent_window)
        self.assertIs(picker.rows['vr:vocals a'], original['vr:vocals a'])
        self.records[0] = replace(self.records[0], display='Renamed vocals')
        picker.refresh_models()
        row = picker.rows['vr:vocals a']
        self.assertIs(row, original['vr:vocals a'])
        self.assertEqual(row.get_title(), 'Renamed vocals')

        # Exercise the existing details button after the record changed.
        def widgets(widget: Gtk.Widget):
            yield widget
            child = widget.get_first_child()
            while child:
                yield from widgets(child)
                child = child.get_next_sibling()

        info = next(w for w in widgets(row) if isinstance(w, Gtk.Button))
        info.emit('clicked')
        self.assertEqual(picker.get('detail_name', Gtk.Label).get_label(), 'Renamed vocals')

    def test_unchanged_inventory_reuses_projection_and_removal_evicts_rows(self):
        picker = self.picker
        models = picker.models
        picker.refresh_models()
        self.assertIs(picker.models, models)
        removed_row = picker.rows['vr:vocals b']
        self.records.pop(1)
        picker.refresh_models()
        self.assertIsNone(removed_row.get_parent())
        picker.reset()
        self.assertNotIn('vr:vocals b', picker.rows)
        from gi.repository import Gtk

        self.assertEqual(picker.get('count', Gtk.Label).get_label(), '1 models')

    def test_catalogue_support_update_invalidates_projection(self):
        from types import SimpleNamespace

        repo = self.picker.repo
        catalogue = SimpleNamespace(latest_snapshot=None)
        with patch.object(repo, '_catalogue', catalogue):
            self.picker.refresh_models()
            self.assertIn('vr:vocals b', self.picker.rows)
            catalogue.latest_snapshot = SimpleNamespace(
                meta_by_family={},
                unsupported={self.records[1].arch: [('vocals b', 'Unsupported update')]},
            )
            self.picker.refresh_models()
            self.assertNotIn('vr:vocals b', self.picker.rows)
            self.picker.select('vr:vocals b')
            self.choose.assert_not_called()

    def test_cross_family_choice_updates_real_method_settings_and_summary(self):
        from core.settings import Settings
        from ui.settings_bind import get_flat
        from ui.views.base import MethodView
        from ui.window import MainWindow

        target = replace(
            record('target'), id='demucs:target', family='demucs', display='Demucs — Target'
        )
        self.records.append(target)
        settings = Settings.defaults()
        with (
            patch.object(Settings, 'load', return_value=settings),
            patch.object(MethodView, 'update_stem_labels'),
        ):
            window = MainWindow()
            self.addCleanup(window._unsubscribe_model_events)
            self.addCleanup(window.set_visible, False)
            self.assertFalse(window.method_row.get_visible())
            self.assertTrue(all(not view.model_row.get_visible() for view in window._views))
            self.assertTrue(window._choose_model(target.id))
            self.assertEqual(window.settings.process.method, target.method)
            assert window._current_view is not None
            self.assertEqual(window._current_view.selected_model(), target.id)
            self.assertEqual(get_flat(settings, window._current_view.model_key), target.id)
            self.assertEqual(window.selected_model_row.get_title(), target.display)
            # An installed ID returning after removal still requires an explicit
            # repick; the summary must not claim it is already active.
            self.records.remove(target)
            window._current_view.refresh_models()
            window._sync_selected_model()
            self.assertIn('unavailable', window.selected_model_row.get_subtitle() or '')
            self.records.append(target)
            window._current_view.refresh_models()
            window._sync_selected_model()
            self.assertIn('Choose this model again', window.selected_model_row.get_subtitle() or '')
            self.assertNotEqual(window._selected_model_id(), target.id)
            self.assertTrue(window._choose_model(target.id))
            self.assertFalse(window._current_view.stored_model_banner.get_revealed())
            window.content_stack.set_visible_child_name('ensemble')
            method = settings.process.method
            self.assertFalse(window._choose_model('vr:vocals a'))
            self.assertEqual(settings.process.method, method)

    def test_separation_startup_does_not_resolve_hidden_ensemble_models(self):
        from core.settings import Settings
        from ui.window import MainWindow

        with (
            patch.object(Settings, 'load', return_value=Settings.defaults()),
            patch('ui.ensemble.window.installed_ensemble_pair_choices') as choices,
        ):
            choices.return_value = [('', 'Choose Stem Pair')]
            window = MainWindow()
            self.addCleanup(window._unsubscribe_model_events)
            self.addCleanup(window.set_visible, False)
            self.assertEqual(window.content_stack.get_visible_child_name(), 'separation')
            choices.assert_not_called()

    def test_ensemble_refresh_stays_lazy_after_switching_back_to_separation(self):
        from core.settings import Settings
        from ui.window import MainWindow

        with (
            patch.object(Settings, 'load', return_value=Settings.defaults()),
            patch(
                'ui.ensemble.window.installed_ensemble_pair_choices',
                return_value=[('', 'Choose Stem Pair')],
            ),
        ):
            window = MainWindow()
            self.addCleanup(window._unsubscribe_model_events)
            self.addCleanup(window.set_visible, False)
            window.content_stack.set_visible_child_name('ensemble')
            window.content_stack.set_visible_child_name('separation')
            with patch.object(
                window._ensemble_page,
                '_acquire_member_projection',
                wraps=window._ensemble_page._acquire_member_projection,
            ) as acquire:
                window._ensemble_page.refresh_models()
                acquire.assert_not_called()
                window.content_stack.set_visible_child_name('ensemble')
                acquire.assert_called_once()

    def test_preflight_plan_run_and_closing_block_configuration(self):
        from ui.run_control import RunController

        controller = RunController(Mock())
        self.assertTrue(controller.can_edit_configuration())
        for field in ('_closing', '_preflight_in_progress', '_plan_dialog', '_running_target'):
            previous = getattr(controller, field)
            setattr(controller, field, True)
            self.assertFalse(controller.can_edit_configuration(), field)
            setattr(controller, field, previous)
