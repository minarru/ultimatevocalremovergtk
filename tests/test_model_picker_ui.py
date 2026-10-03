"""Native installed picker interactions and main-window selection adapter."""

from __future__ import annotations

import os
import unittest
from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from unittest.mock import Mock, call, patch

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


def _descendants(widget: Any) -> Iterator[Any]:
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _descendants(child)
        child = child.get_next_sibling()


@unittest.skipUnless(
    os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY'), 'GTK needs a display'
)
class PickerConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')

    def _picker(self, **kwargs: Any) -> Any:
        from core.model_repository import ModelRepository
        from ui.model_picker import ModelPicker

        inventory = patch(
            'core.model_identity.ModelIdentityService.records',
            return_value=(record('vocals a'),),
        )
        inventory.start()
        self.addCleanup(inventory.stop)
        return ModelPicker(ModelRepository(), lambda: '', Mock(), Mock(), **kwargs)

    def test_default_config_is_separation(self):
        from gi.repository import Adw, Gtk

        picker = self._picker()
        self.assertEqual(picker.dialog.get_title(), 'Choose Model')
        self.assertTrue(picker.get('purpose_tabs', Gtk.Box).get_visible())
        self.assertEqual(picker.search.get_placeholder_text(), 'Search installed models')
        self.assertFalse(picker.get('select_all', Gtk.Button).get_visible())
        self.assertFalse(picker.get('clear', Gtk.Button).get_visible())
        self.assertFalse(picker.get('header_title', Adw.WindowTitle).get_visible())

    def test_config_title_and_hidden_tabs(self):
        from gi.repository import Adw, Gtk

        from ui.model_picker import PickerConfig

        picker = self._picker(
            config=PickerConfig(
                title='Member Models', purposes=(), search_placeholder='Search compatible models'
            )
        )
        self.assertEqual(picker.dialog.get_title(), 'Member Models')
        self.assertEqual(picker.search.get_placeholder_text(), 'Search compatible models')
        self.assertFalse(picker.get('purpose_tabs', Gtk.Box).get_visible())
        self.assertFalse(picker.compact.get_visible())
        # Without tabs the header names the dialog instead.
        header_title = picker.get('header_title', Adw.WindowTitle)
        self.assertTrue(header_title.get_visible())
        self.assertEqual(header_title.get_title(), 'Member Models')
        picker.reset()
        self.assertEqual(picker.filters.purpose, 'all')
        # Narrow breakpoints must not reveal the compact purpose dropdown.
        from gi.repository import GLib

        parent = Adw.Window(default_width=480, default_height=700)
        parent.present()
        self.addCleanup(parent.set_visible, False)
        picker.present(parent)
        import time

        context = GLib.MainContext.default()
        deadline = time.monotonic() + 3
        while picker.dialog.get_current_breakpoint() is None:
            self.assertLess(time.monotonic(), deadline, 'no breakpoint applied')
            context.iteration(False)
            time.sleep(0.005)
        self.assertFalse(picker.compact.get_visible())
        self.assertFalse(picker.get('purpose_tabs', Gtk.Box).get_visible())


@unittest.skipUnless(
    os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY'), 'GTK needs a display'
)
class MemberPickerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Adw

        cls.app = Adw.Application(application_id='org.uvr.test.member-picker')
        cls.app.register()

    def setUp(self):
        from core.model_repository import ModelRepository
        from ui.model_picker import MemberCallbacks, ModelPicker, PickerConfig

        self.a = record('alpha')
        self.b = record('bravo')
        self.c = record('charlie')
        # The installed inventory holds a model the page did not offer.
        self.inventory = patch(
            'core.model_identity.ModelIdentityService.records',
            return_value=(self.a, self.b, self.c, record('outsider')),
        )
        self.inventory.start()
        self.addCleanup(self.inventory.stop)
        self.toggled = Mock()
        self.set_visible_active = Mock()
        self.filtered = Mock()
        self.more = Mock()
        self.picker = ModelPicker(
            ModelRepository(),
            lambda: '',
            Mock(return_value=False),
            self.more,
            config=PickerConfig(title='Member Models', purposes=()),
            members=MemberCallbacks(self.toggled, self.set_visible_active, self.filtered),
        )

    def test_members_reuse_checks_and_block_handlers(self):
        first = self.picker.set_members([self.a, self.b], {'vr:alpha'})
        self.assertEqual(list(first), ['vr:alpha', 'vr:bravo'])
        self.assertTrue(first['vr:alpha'].get_active())
        self.assertFalse(first['vr:bravo'].get_active())
        second = self.picker.set_members([self.a, self.b], {'vr:bravo'})
        for model_id in first:
            self.assertIs(second[model_id], first[model_id])
        self.assertFalse(second['vr:alpha'].get_active())
        self.assertTrue(second['vr:bravo'].get_active())
        self.toggled.assert_not_called()
        second['vr:alpha'].set_active(True)
        self.toggled.assert_called_once_with(second['vr:alpha'])

    def test_members_rows_come_only_from_set_members(self):
        self.picker.set_members([self.a, self.b], ())
        self.assertEqual(set(self.picker.rows), {'vr:alpha', 'vr:bravo'})
        self.picker.refresh_models()
        self.assertEqual(set(self.picker.rows), {'vr:alpha', 'vr:bravo'})
        dropped = self.picker.set_members([self.a], ())
        self.assertEqual(list(dropped), ['vr:alpha'])
        self.assertEqual(list(self.picker.rows), ['vr:alpha'])

    def test_member_rows_name_their_architecture(self):
        from dataclasses import replace

        shared_mdx = replace(record('shared'), id='mdx:shared', family='mdx')
        self.picker.set_members([record('shared'), shared_mdx], ())
        subtitles = {
            model_id: row.get_subtitle() or '' for model_id, row in self.picker.rows.items()
        }
        self.assertTrue(subtitles['vr:shared'].startswith('VR'))
        self.assertTrue(subtitles['mdx:shared'].startswith('MDX-Net'))

    def test_members_visible_ids_follow_search_and_sort(self):
        self.picker.set_members([self.c, self.a, self.b], ())
        self.assertEqual(self.picker.visible_ids(), ['vr:alpha', 'vr:bravo', 'vr:charlie'])
        self.picker.search.set_text('br')
        self.picker._refresh()
        self.assertEqual(self.picker.visible_ids(), ['vr:bravo'])
        self.picker.reset()
        self.picker._reverse()
        self.assertEqual(self.picker.visible_ids(), ['vr:charlie', 'vr:bravo', 'vr:alpha'])

    def test_members_select_all_and_clear_delegate(self):
        from gi.repository import Gtk

        self.picker.set_members([self.a], ())
        select_all = self.picker.get('select_all', Gtk.Button)
        clear = self.picker.get('clear', Gtk.Button)
        self.assertTrue(select_all.get_visible())
        self.assertTrue(clear.get_visible())
        select_all.emit('clicked')
        clear.emit('clicked')
        self.assertEqual(
            self.set_visible_active.call_args_list,
            [call(True), call(False)],
        )

    def test_members_status_text_is_kept_across_refresh(self):
        from gi.repository import Gtk

        self.picker.set_members([self.a, self.b], ())
        self.picker.set_status('Select at least 2 models')
        self.picker._refresh()
        self.assertEqual(
            self.picker.get('count', Gtk.Label).get_label(), 'Select at least 2 models'
        )

    def test_members_placeholder_shows_status_page(self):
        from gi.repository import Adw, Gtk

        self.picker.set_members(
            (),
            (),
            placeholder='Could not list models',
            placeholder_description='See Error Log for details',
        )
        empty = self.picker.get('empty', Adw.StatusPage)
        self.assertTrue(empty.get_visible())
        self.assertFalse(self.picker.list.get_visible())
        self.assertEqual(empty.get_title(), 'Could not list models')
        self.assertEqual(empty.get_description(), 'See Error Log for details')
        self.assertFalse(self.picker.get('empty_reset', Gtk.Button).get_visible())
        # Real rows bring back the search-miss wording.
        self.picker.set_members([self.a], ())
        self.picker.search.set_text('nothing matches')
        self.picker._refresh()
        self.assertEqual(empty.get_title(), 'No matching models')
        self.assertTrue(self.picker.get('empty_reset', Gtk.Button).get_visible())

    def test_members_details_toggle(self):
        from gi.repository import Gtk

        checks = self.picker.set_members([self.a, self.b], {'vr:alpha'})
        button = self.picker.get('choose_detail', Gtk.Button)
        model = next(m for m in self.picker.models if m.id == 'vr:alpha')
        self.picker.show_details(model)
        self.assertEqual(button.get_label(), 'Remove from Ensemble')
        self.assertTrue(button.get_sensitive())
        button.emit('clicked')
        self.assertFalse(checks['vr:alpha'].get_active())
        self.assertEqual(button.get_label(), 'Add to Ensemble')
        other = next(m for m in self.picker.models if m.id == 'vr:bravo')
        self.picker.show_details(other)
        self.assertEqual(button.get_label(), 'Add to Ensemble')
        button.emit('clicked')
        self.assertTrue(checks['vr:bravo'].get_active())
        self.assertEqual(self.toggled.call_count, 2)

    def test_members_row_activation_toggles_check(self):
        from gi.repository import Gtk

        checks = self.picker.set_members([self.a], ())
        row = self.picker.rows['vr:alpha']
        check = next(w for w in _descendants(row) if isinstance(w, Gtk.CheckButton))
        self.assertIs(check, checks['vr:alpha'])
        row.activate()
        self.assertTrue(checks['vr:alpha'].get_active())
        self.toggled.assert_called_once_with(checks['vr:alpha'])

    def test_members_search_notifies_the_page(self):
        self.picker.set_members([self.a, self.b], ())
        self.filtered.reset_mock()
        self.picker.search.set_text('alpha')
        self.picker._refresh()
        self.filtered.assert_called()
        self.assertEqual(self.picker.visible_ids(), ['vr:alpha'])
