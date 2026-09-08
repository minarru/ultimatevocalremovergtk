"""Integrated Download Center behavior through its real GTK host."""

from __future__ import annotations

import os
import time
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


@unittest.skipUnless(
    os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY'), 'GTK needs a private display'
)
class DownloadCenterDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Adw

        cls.app = Adw.Application(application_id='org.uvr.test.dc-design')
        cls.app.register()

    def setUp(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_DUAL_VOC_INST
        from core.settings import Settings
        from ui.download_center import DownloadCenterWindow

        self.arch = MDX_ARCH_TYPE
        self.manager = MagicMock()
        self.manager.latest_snapshot = None
        meta = EntryMeta(
            label='Dual',
            display='Dual',
            arch=self.arch,
            files={'dual.onnx': 'https://example.invalid/dual.onnx'},
            stems=['Vocals', 'Instrumental'],
            intent=INTENT_DUAL_VOC_INST,
        )
        self.manager.catalogue_meta_by_family = {'mdx': {'Dual': meta}}
        self.manager.catalogue_meta = {'Dual': meta}
        self.manager.mdx_download_list = {'Dual': meta.files}
        self.center = DownloadCenterWindow(
            None, SimpleNamespace(settings=Settings.defaults()), self.manager, MagicMock()
        )
        self.addCleanup(self.center.window.set_visible, False)
        self.addCleanup(self.center.dispose)
        for method in (
            '_ensure_background_listeners',
            '_schedule_stem_yaml_fetches',
            '_lookup_row_size',
        ):
            patcher = patch.object(self.center, method)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.center._refresh_done(
            True, {self.arch: ['Dual']}, {self.arch: [('Future', 'Needs a newer build')]}
        )
        self.key = (self.arch, 'Dual')

    def test_selection_badges_and_footer_count_are_independent_of_filters(self) -> None:
        from core.model_scores import PURPOSE_INSTRUMENTAL, PURPOSE_VOCALS

        center = self.center
        center._row_checks[self.key].set_active(True)
        self.assertEqual(center.download_button.get_label(), 'Download')
        self.assertTrue(center.download_button.get_sensitive())
        for purpose in (PURPOSE_VOCALS, PURPOSE_INSTRUMENTAL):
            badge = center._purpose_badges[purpose]
            self.assertEqual(badge.get_label(), '1')
            self.assertTrue(badge.get_visible())
        center._search_entry.set_text('absent')
        center._on_search_changed()
        self.assertEqual(center.selection_label.get_label(), '1 selected · 1 outside this view')
        center.clear_button.emit('clicked')
        self.assertFalse(center.clear_button.get_visible())
        self.assertFalse(center.download_button.get_sensitive())
        self.assertEqual(center.selection_summary.get_visible_child_name(), 'empty')

    def test_sort_tracks_purpose_and_preserves_selected_row(self) -> None:
        from core.model_scores import (
            PURPOSE_INSTRUMENTAL,
            PURPOSE_STEMS,
            PURPOSE_VOCALS,
            SORT_NAME,
            SORT_SDR,
        )

        center = self.center
        action = center._row_actions[self.key]
        center._row_checks[self.key].set_active(True)
        with patch(
            'ui.download_center.sdr_for_files', return_value={'vocals': 12, 'instrumental': 8}
        ):
            center.sort_row.set_selected(1)
            center.select_catalogue(purpose=PURPOSE_INSTRUMENTAL)
            self.assertEqual(center._sort_mode, SORT_SDR)
            self.assertIn('Instrumental SDR 8.00 dB', action.get_subtitle() or "")
            center.select_catalogue(purpose=PURPOSE_VOCALS)
            self.assertIn('Vocal SDR 12.00 dB', action.get_subtitle() or "")
            center.select_catalogue(purpose=PURPOSE_STEMS)
            self.assertEqual(center._sort_mode, SORT_NAME)
            self.assertFalse(center.sort_row.get_visible())
            self.assertFalse(center._descending)
            center.select_catalogue(purpose=PURPOSE_VOCALS)
            self.assertTrue(center.sort_row.get_visible())
        self.assertIs(center._row_actions[self.key], action)
        self.assertTrue(center._row_checks[self.key].get_active())

    def test_architecture_filter_and_search_do_not_change_download_identity(self) -> None:
        from ui.download_presentation import ARCHITECTURES

        center = self.center
        center.arch_row.set_selected(
            next(i for i, (key, _) in enumerate(ARCHITECTURES) if key == 'classic_onnx')
        )
        self.assertTrue(center._row_matches_filter(center._row_actions[self.key]))
        center._search_entry.set_text('Classic MDX')
        self.assertTrue(center._row_matches_filter(center._row_actions[self.key]))
        self.assertNotIn('Classic MDX', center._row_actions[self.key].get_subtitle() or "")
        center._row_checks[self.key].set_active(True)
        self.assertEqual(center._selected_entries(), [('Dual', self.arch)])

    def test_unsupported_details_remain_accessible(self) -> None:
        from gi.repository import Gtk

        center = self.center
        row = center._row_actions[(self.arch, 'Future')]
        self.assertTrue(row.get_sensitive())
        self.assertIn('dim-label', row.get_css_classes())
        buttons = []

        def walk(widget: Gtk.Widget) -> None:
            if isinstance(widget, Gtk.MenuButton):
                buttons.append(widget)
            child = widget.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(row)
        self.assertEqual(len(buttons), 1)
        self.assertTrue(buttons[0].get_sensitive())
        self.assertEqual(buttons[0].get_icon_name(), 'info-outline-symbolic')
        self.assertIn('Needs a newer build', center._details_text((self.arch, 'Future')))

    def test_unchecked_and_disposed_rows_ignore_late_size_results(self) -> None:
        from ui.widget_state import fetch, stash

        center = self.center
        center._row_checks[self.key].set_active(True)
        center._size_lookup_ids[self.key] = 7
        stash(center._row_actions[self.key], '_uvr_size', 'Looking up size…')
        center._row_checks[self.key].set_active(False)
        center._apply_row_size(7, self.key, '99 MB', center.browser.generation)
        self.assertIsNone(fetch(center._row_actions[self.key], '_uvr_size', None))
        center._row_checks[self.key].set_active(True)
        center._size_lookup_ids[self.key] = 8
        center.dispose()
        center._apply_row_size(8, self.key, '99 MB', center.browser.generation)
        self.assertIsNone(fetch(center._row_actions[self.key], '_uvr_size', None))

    def test_footer_height_is_stable_and_filters_stay_horizontal_at_670(self) -> None:
        from gi.repository import GLib, Gtk

        center = self.center
        center.window.set_default_size(670, 620)
        center.window.present()

        def wait_for(predicate: Callable[[], bool]) -> None:
            deadline = time.monotonic() + 3
            while not predicate() and time.monotonic() < deadline:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.005)
            self.assertTrue(predicate())

        wait_for(lambda: center.window.get_width() == 670 and center.compact_purpose.get_visible())
        bar = center._layout_builder.get_object('filter_bar')
        assert isinstance(bar, Gtk.Box)
        self.assertEqual(bar.get_orientation(), Gtk.Orientation.HORIZONTAL)
        footer = center._layout_builder.get_object('action_bar')
        assert isinstance(footer, Gtk.Box)
        before = footer.measure(Gtk.Orientation.VERTICAL, 634)
        center._row_checks[self.key].set_active(True)
        after = footer.measure(Gtk.Orientation.VERTICAL, 634)
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[1], after[1])
        center.window.set_default_size(390, 620)
        wait_for(lambda: bar.get_orientation() == Gtk.Orientation.VERTICAL)
        self.assertTrue(center.compact_purpose.get_visible())
        self.assertFalse(center.switcher.get_visible())

    def test_download_click_uses_pinned_identity_and_clears_selection(self) -> None:
        center = self.center
        queue = MagicMock()
        center.queue = queue
        queue.active_item_id.return_value = None
        queue.enqueue.return_value = 'queue-id'
        center._row_checks[self.key].set_active(True)
        jobs = [('https://example.invalid/dual.onnx', '/tmp/dual.onnx')]
        with patch.object(center, '_resolve_pinned', return_value=jobs) as resolve:
            center.download_button.emit('clicked')
        resolve.assert_called_once_with('Dual', self.arch)
        self.assertEqual(queue.enqueue.call_args.args, ('Dual', self.arch))
        self.assertEqual(queue.enqueue.call_args.kwargs['jobs'], jobs)
        self.assertFalse(center._row_checks[self.key].get_active())
        self.assertFalse(center.download_button.get_sensitive())

    def test_online_refresh_updates_scores_before_delivering_rows(self) -> None:
        center = self.center
        self.manager.refresh.return_value = True
        self.manager.available_downloads.return_value = {}
        self.manager.unsupported_downloads.return_value = {}
        events = []
        with (
            patch(
                'ui.download_center.load_model_scores',
                side_effect=lambda **_: events.append('scores'),
            ) as scores,
            patch(
                'ui.download_center.idle_on_main', side_effect=lambda *_: events.append('delivery')
            ),
        ):
            center._refresh_worker()
        scores.assert_called_once_with(force=True)
        self.assertEqual(events, ['scores', 'delivery'])

    def test_mapped_details_popover_has_readable_width_at_narrow_window(self) -> None:
        from gi.repository import GLib, Gtk

        center = self.center
        center.window.set_default_size(390, 620)
        center.window.present()
        deadline = time.monotonic() + 3
        while center.window.get_width() != 390 and time.monotonic() < deadline:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.005)
        widgets: list[Gtk.Widget] = [center._row_actions[self.key]]
        button = None
        while widgets:
            widget = widgets.pop()
            if isinstance(widget, Gtk.MenuButton):
                button = widget
                break
            child = widget.get_first_child()
            while child is not None:
                widgets.append(child)
                child = child.get_next_sibling()
        assert button is not None
        center._create_details_popup(button, self.key)
        button.popup()
        popover = button.get_popover()
        assert popover is not None
        while popover.get_width() < 320 and time.monotonic() < deadline:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.005)
        self.assertGreaterEqual(popover.get_width(), 320)
        self.assertLessEqual(popover.get_width(), center.window.get_width())
        popover.popdown()

    def test_resize_moves_size_without_recomputing_catalogue_presentation(self) -> None:
        from gi.repository import GLib

        from ui.widget_state import fetch, stash

        center = self.center
        action = center._row_actions[self.key]
        center._row_checks[self.key].set_active(True)
        stash(action, '_uvr_size', '12 MB')
        center._render_row(self.key)
        base = action.get_subtitle()
        center.window.set_default_size(860, 620)
        center.window.present()

        def wait_for(predicate: Callable[[], bool]) -> None:
            deadline = time.monotonic() + 3
            while not predicate() and time.monotonic() < deadline:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.005)
            self.assertTrue(predicate())

        wait_for(lambda: center.window.get_width() == 860)
        with (
            patch.object(center, '_row_score', wraps=center._row_score) as scores,
            patch.object(action, 'set_subtitle', wraps=action.set_subtitle) as subtitles,
        ):
            center.window.set_default_size(670, 620)
            wait_for(lambda: center.window.get_width() == 670)
            self.assertEqual(action.get_subtitle(), f'{base} · 12 MB')
            self.assertFalse(fetch(action, '_uvr_status_label').get_visible())
            self.assertEqual(subtitles.call_count, 1)
            center.window.set_default_size(390, 620)
            wait_for(lambda: center.window.get_width() == 390)
            self.assertEqual(subtitles.call_count, 1)
            center.window.set_default_size(670, 620)
            wait_for(lambda: center.window.get_width() == 670)
            self.assertEqual(subtitles.call_count, 1)
            center.window.set_default_size(860, 620)
            wait_for(lambda: center.window.get_width() == 860)
            self.assertEqual(action.get_subtitle(), base)
            self.assertTrue(fetch(action, '_uvr_status_label').get_visible())
            self.assertEqual(subtitles.call_count, 2)
        scores.assert_not_called()

    def test_clear_selection_recomputes_metadata_once_and_invalidates_size_results(self):
        from ui.widget_state import fetch, stash

        center = self.center
        for index in range(20):
            name = f'Model {index}'
            center._add_model_row(self.arch, name)
            key = (self.arch, name)
            center._row_checks[key].set_active(True)
            center._size_lookup_ids[key] = 4
            stash(center._row_actions[key], '_uvr_size', '12 MB')
        with patch.object(center, '_refresh_browser_metadata', wraps=center._refresh_browser_metadata) as metadata:
            center._clear_selection()
        self.assertEqual(center.browser.selected_keys(), ())
        self.assertFalse(center.download_button.get_sensitive())
        self.assertEqual(metadata.call_count, 1)
        key = (self.arch, 'Model 0')
        center._apply_row_size(4, key, '99 MB', center.browser.generation)
        self.assertIsNone(fetch(center._row_actions[key], '_uvr_size', None))

    def test_rebuild_projects_each_identity_once_and_batches_selection_restore(self):
        center = self.center
        self.manager.available_downloads.return_value = {self.arch: ['Dual', 'Second']}
        center.browser.available = {self.arch: ['Dual', 'Second']}
        center._add_model_row(self.arch, 'Second')
        for check in center._row_checks.values():
            check.set_active(True)
        with (
            patch.object(center, '_project_browser_row', wraps=center._project_browser_row) as project,
            patch.object(center, '_update_download_button', wraps=center._update_download_button) as summary,
            patch.object(center._list_box, 'invalidate_filter', wraps=center._list_box.invalidate_filter) as filters,
        ):
            center._rebuild_catalogue()
        self.assertEqual(project.call_count, 3)  # two downloadable plus one unsupported
        self.assertEqual(summary.call_count, 1)
        self.assertEqual(filters.call_count, 1)
        self.assertEqual(set(center.browser.selected_keys()), {(self.arch, 'Dual'), (self.arch, 'Second')})
        self.assertTrue(all(check.get_active() for check in center._row_checks.values()))

    def test_hidden_stem_updates_coalesce_until_present_and_disposal_blocks_delivery(self):
        center = self.center
        self.manager.apply_catalogue_stem_cache.return_value = {'Dual'}
        with patch.object(center, '_render_row', wraps=center._render_row) as render:
            center._flush_stem_subtitles()
            center._flush_stem_subtitles()
            self.manager.apply_catalogue_stem_cache.assert_not_called()
            render.assert_not_called()
            center.present()
            self.manager.apply_catalogue_stem_cache.assert_called_once_with()
            render.assert_called_once_with(self.key)
            center.window.set_visible(False)
            center._flush_stem_subtitles()
            center.dispose()
            center.present()
            self.assertEqual(self.manager.apply_catalogue_stem_cache.call_count, 1)
            self.assertFalse(center.window.get_visible())

    def test_hidden_removal_refresh_retains_selection_until_present(self):
        center = self.center
        center._row_checks[self.key].set_active(True)
        retained = center._row_actions[(self.arch, 'Future')]
        self.manager.available_downloads.return_value = {self.arch: []}
        self.manager.unsupported_downloads.return_value = {
            self.arch: [('Future', 'Needs a newer build')]
        }
        center._flush_catalogue_row_refresh()
        center._flush_catalogue_row_refresh()
        self.manager.available_downloads.assert_not_called()
        self.assertTrue(center._row_checks[self.key].get_active())
        center.present()
        self.manager.available_downloads.assert_called_once_with()
        self.assertNotIn(self.key, center._row_actions)
        self.assertEqual(center.browser.selected_keys(), ())
        self.assertIs(center._row_actions[(self.arch, 'Future')], retained)
        self.assertFalse(center.download_button.get_sensitive())

    def test_new_source_refresh_takes_precedence_over_hidden_metadata_flush(self):
        center = self.center
        center._flush_stem_subtitles()
        center.browser.pending_source = True
        with patch.object(center, 'start_refresh') as refresh:
            center.present()
        refresh.assert_called_once_with()
        self.manager.apply_catalogue_stem_cache.assert_not_called()
        self.assertFalse(center.browser.pending_source)
        self.assertIn(self.key, center.browser.rows)

    def test_published_metadata_delta_survives_hidden_view_and_empty_cache_apply(self):
        from dataclasses import replace

        from core.catalogue_types import CatalogueDelta, DeltaKind

        center = self.center
        action = center._row_actions[self.key]
        center._row_checks[self.key].set_active(True)
        old = self.manager.catalogue_meta_by_family['mdx']['Dual']
        # The evidence service patches family metadata before publishing its delta.
        self.manager.catalogue_meta_by_family['mdx']['Dual'] = replace(
            old, stems=['Lead Vocals', 'Backing Vocals']
        )
        self.manager.apply_catalogue_stem_cache.return_value = set()
        delta = CatalogueDelta(kind=DeltaKind.METADATA_CHANGED, changed={'mdx': ('Dual',)})
        with patch('ui.download_center.idle_on_main', side_effect=lambda fn, *args: fn(*args)):
            center._on_catalogue_delta(delta)
            center._on_catalogue_delta(delta)
        center._flush_stem_subtitles()
        self.assertNotIn('Backing Vocals', action.get_subtitle() or '')
        with patch.object(center, '_render_row', wraps=center._render_row) as render:
            center.present()
            center._flush_stem_subtitles()  # A previously armed timeout must be harmless.
        self.assertIn('Lead Vocals, Backing Vocals', action.get_subtitle() or '')
        render.assert_called_once_with(self.key)
        self.assertIs(center._row_actions[self.key], action)
        self.assertTrue(center._row_checks[self.key].get_active())
