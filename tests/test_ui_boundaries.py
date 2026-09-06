"""Bounded private-GTK integration at projection and delivery boundaries."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from tests.private_gtk import require_private_gtk


def setUpModule() -> None:
    require_private_gtk()
    import gi

    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')


class MemberRenderTests(unittest.TestCase):
    def test_real_render_is_read_only_then_action_prunes_and_sorts(self):
        from gi.repository import Gtk

        from core.settings import Settings
        from tests.test_ensemble_member_projection import record
        from ui.ensemble.window import EnsemblePage

        page = cast(Any, EnsemblePage.__new__(EnsemblePage))
        page.settings = Settings.defaults()
        page.settings.ensemble.main_stem = 'pair.vocals_instrumental'
        page.settings.ensemble.selected_models = ['mdx:b', 'mdx:a', 'mdx:missing']
        original_list = page.settings.ensemble.selected_models
        original = page.settings.to_dict()
        page.models_listbox = Gtk.ListBox()
        page.context = SimpleNamespace(
            repo=SimpleNamespace(ensemble_model_list=lambda *_: ['mdx:a', 'mdx:b'])
        )
        page._ensemble_pair = lambda: 'pair.vocals_instrumental'
        page._update_models_dialog_status = mock.Mock()
        page._update_models_summary = mock.Mock()
        with mock.patch(
            'core.model_identity.ModelIdentityService.records',
            return_value=(record('b', 'Zulu'), record('a', 'Alpha')),
        ):
            projection = page._acquire_member_projection(list(original_list))
            page._render_member_projection(projection, list(original_list))
            self.assertIs(page.settings.ensemble.selected_models, original_list)
            self.assertEqual(page.settings.to_dict(), original)
            page._reconcile_member_list(list(original_list))
        self.assertEqual(page.settings.ensemble.selected_models, ['mdx:a', 'mdx:b'])


class DownloadBindingTests(unittest.TestCase):
    def test_disposal_discards_queued_ui_and_retains_new_callback_owner(self):
        from core.download_queue import DownloadQueue
        from ui.download import DownloadQueueUiBinding

        queue = DownloadQueue(mock.Mock())
        context = SimpleNamespace(download_queue=queue, settings=mock.Mock())
        indicator = mock.Mock()
        window = SimpleNamespace(_download_queue_indicator=indicator)
        scheduled = []
        with mock.patch(
            'ui.download.latest_main_thread', side_effect=lambda fn: lambda: scheduled.append(fn)
        ):
            first = DownloadQueueUiBinding(cast(Any, window), cast(Any, context))
            first.center = mock.Mock()
            second = DownloadQueueUiBinding(cast(Any, window), cast(Any, context))
        first.dispose()
        first.dispose()
        indicator.reset_mock()
        scheduled[0]()
        first.after_batch()
        indicator.refresh.assert_not_called()
        first.center.dispose.assert_called_once_with()
        queue._notify()
        self.assertEqual(len(scheduled), 3)
        second.dispose()

    def test_rebinding_retains_the_cached_browser_without_replaying_terminal_items(self):
        from core.download_queue import DownloadQueue, DownloadQueueItem
        from ui.download import init_download_queue_ui

        queue = DownloadQueue(mock.Mock())
        with queue._lock:
            queue._items.append(
                DownloadQueueItem("done", "Model", "MDX-Net", "Model", [], status="complete")
            )
        context = SimpleNamespace(download_queue=queue, settings=mock.Mock())
        window = SimpleNamespace(_download_queue_indicator=mock.Mock(), _download_ui=None)
        with mock.patch("ui.download.latest_main_thread", side_effect=lambda fn: lambda: None):
            init_download_queue_ui(cast(Any, window), cast(Any, context))
            first = window._download_ui
            center = mock.Mock()
            first.center = center
            init_download_queue_ui(cast(Any, window), cast(Any, context))
        second = window._download_ui
        self.assertIs(second.center, center)
        with mock.patch("ui.download._send_download_notifications") as notify:
            second.after_batch()
            notify.assert_not_called()
        center.dispose.assert_not_called()
        second.dispose()
        center.dispose.assert_called_once_with()

    def test_browser_hide_retains_pin_and_listeners_terminal_dispose_removes_once(self):
        from ui.catalogue_browser import CatalogueBrowserState
        from ui.download_center import DownloadCenterWindow
        from ui.lifetime import UiLifetime

        browser = cast(Any, DownloadCenterWindow.__new__(DownloadCenterWindow))
        browser.window = mock.Mock()
        browser.browser = CatalogueBrowserState()
        browser._lifetime = UiLifetime()
        browser._listening = False
        browser.manager = mock.Mock()
        pin = mock.Mock()
        browser.browser.pin(pin)
        with (
            mock.patch('core.catalogue_stem_cache.subscribe') as subscribe,
            mock.patch('core.catalogue_stem_cache.unsubscribe') as unsubscribe,
            mock.patch('core.catalogue_stem_cache.ensure_worker_started'),
        ):
            browser._ensure_background_listeners()
            browser._on_close_request(browser.window)
            browser._ensure_background_listeners()
            self.assertIs(browser.browser.snapshot, pin)
            self.assertFalse(browser._lifetime.disposed)
            subscribe.assert_called_once()
            browser.dispose()
            browser.dispose()
            unsubscribe.assert_called_once()
            browser.manager.unsubscribe_delta.assert_called_once()


class RunDialogOrderingTests(unittest.TestCase):
    def test_stop_response_stops_immediately_then_unpauses_and_stops_on_idle(self):
        from ui.protocols import RunHost, RunTarget
        from ui.run_control import RunController

        host = mock.Mock(spec=RunHost)
        host.stop_enabled.return_value = True
        target = mock.Mock(spec=RunTarget)
        target.start_blocked_reason.return_value = None
        host.target = target
        order = []
        host.set_pulse.side_effect = lambda active: order.append(('pulse', active))
        host.enable_stop.side_effect = lambda active: order.append(('stop_enabled', active))
        host.set_options_sensitive.side_effect = lambda active: order.append(('options', active))
        host.append_console.side_effect = lambda text: order.append(('console', text))
        target.pause.side_effect = lambda: order.append('pause')
        target.unpause.side_effect = lambda: order.append('unpause')
        target.stop.side_effect = lambda: order.append('stop')
        controller = RunController(host)
        controller._running_target = target
        handlers = {}
        dialog = mock.Mock()
        dialog.connect.side_effect = lambda signal, callback: handlers.update({signal: callback})
        deferred = []
        with (
            mock.patch('ui.run_control.Adw.AlertDialog', return_value=dialog),
            mock.patch(
                'ui.run_control.GLib.idle_add',
                side_effect=lambda callback: deferred.append(callback),
            ),
            mock.patch('ui.run_control.GLib.timeout_add') as timeout,
        ):
            controller._present_stop_confirm()
            self.assertEqual(order[:2], [('pulse', False), 'pause'])
            handlers['response'](dialog, 'stop')
            self.assertEqual(order[-1], 'stop')
            self.assertNotIn('unpause', order)
            self.assertEqual(len(deferred), 1)
            deferred.pop()()
            self.assertEqual(order.count('stop'), 2)
            self.assertLess(order.index('unpause'), order.index(('stop_enabled', False)))
            self.assertNotIn(('options', True), order)
            self.assertTrue(controller.is_running())
            self.assertEqual(order[-1], 'stop')
            timeout.assert_called_once_with(50, controller.shutdown.poll_inference_cleanup)

    def test_shutdown_orders_context_stop_deferred_poll_cleanup_and_destroy(self):
        from ui.protocols import RunHost, RunTarget
        from ui.run_control import RunController

        host = mock.Mock(spec=RunHost)
        host.stop_enabled.return_value = True
        host.active_download_count.return_value = 0
        target = mock.Mock(spec=RunTarget)
        target.worker_is_running.return_value = False
        target.start_blocked_reason.return_value = None
        host.target = target
        order = []
        target.stop.side_effect = lambda: order.append('stop')
        target.unpause.side_effect = lambda: order.append('unpause')
        host.stop_context_workers.side_effect = lambda **kwargs: order.append(
            ('context_stop', kwargs['force'])
        )
        host.stop_all_workers.side_effect = lambda **kwargs: order.append(
            ('all_stop', kwargs['force'])
        )
        host.destroy.side_effect = lambda: order.append('destroy')
        host.get_application.return_value.hold.side_effect = lambda: order.append('hold')
        host.get_application.return_value.release.side_effect = lambda: order.append('release')
        host.get_application.return_value.quit.side_effect = lambda: order.append('quit')
        controller = RunController(host)
        controller._running_target = target
        controller._close_deferred = True
        controller._on_close_complete = lambda deferred: order.append(('close', deferred))
        completion = []
        controller.shutdown.release = lambda **kwargs: completion.append(kwargs['on_done'])
        handlers = {}
        dialog = mock.Mock()
        dialog.connect.side_effect = lambda signal, callback: handlers.update({signal: callback})
        deferred = []
        with (
            mock.patch('ui.run_control.Adw.AlertDialog', return_value=dialog),
            mock.patch(
                'ui.run_control.GLib.idle_add',
                side_effect=lambda callback: deferred.append(callback),
            ),
            mock.patch('ui.run_control.GLib.timeout_add', return_value=7),
            mock.patch('ui.run_control.GLib.source_remove'),
        ):
            controller._present_shutdown_confirm()
            handlers['response'](dialog, 'quit')
            self.assertEqual(order, ['stop', ('context_stop', False)])
            deferred.pop()()
            self.assertEqual(order[-2:], ['unpause', 'stop'])
            self.assertFalse(controller.shutdown.poll_shutdown())
            self.assertEqual(order[-4:], [('all_stop', True), ('close', True), 'hold', 'destroy'])
            completion[0]()
            completion[0]()
            self.assertEqual(order[-2:], ['release', 'quit'])


class BrowserGenerationTests(unittest.TestCase):
    def test_replaced_row_rejects_an_old_size_result_with_same_lookup_id(self):
        from gi.repository import Adw

        from ui.catalogue_browser import BrowserRow, CatalogueBrowserState
        from ui.download_center import DownloadCenterWindow
        from ui.lifetime import UiLifetime
        from ui.widget_state import fetch

        browser = cast(Any, DownloadCenterWindow.__new__(DownloadCenterWindow))
        browser.browser = CatalogueBrowserState()
        browser._lifetime = UiLifetime()
        key = ('MDX-Net', 'Model')
        row = BrowserRow(key, 'Model', 'MDX-Net')
        browser.browser.replace_rows((row,))
        old_generation = browser.browser.generation
        browser.browser.replace_rows((row,))
        action = Adw.ActionRow()
        action.set_subtitle('current')
        browser._row_actions = {key: action}
        browser._size_lookup_ids = {key: 1}
        browser._apply_row_size(1, key, 'old result', old_generation)
        self.assertEqual(action.get_subtitle(), 'current')
        self.assertIsNone(fetch(action, '_uvr_size', None))

    def test_indicator_disposal_cannot_unbind_a_newer_owner(self):
        from core.download_queue import DownloadQueue
        from ui.widgets.download_queue_indicator import DownloadQueueIndicator

        indicator = DownloadQueueIndicator()
        queue = DownloadQueue(mock.Mock())
        first, second = object(), object()
        indicator.bind(queue, owner=first)
        indicator.bind(queue, owner=second)
        indicator.dispose(owner=first)
        with mock.patch.object(queue, 'items', return_value=[]) as items:
            indicator.refresh()
            items.assert_called_once_with()
        indicator.dispose(owner=second)
        with mock.patch.object(queue, 'items') as items:
            indicator.refresh()
            items.assert_not_called()


class ReviewedContractTests(unittest.TestCase):
    def test_readiness_uses_host_target_with_an_ordinary_dialog_parent(self):
        from gi.repository import Gtk

        from ui.protocols import RunHost, RunTarget
        from ui.run_control import RunController

        host = mock.Mock(spec=RunHost)
        host.dialog_parent = Gtk.Window()
        self.addCleanup(host.dialog_parent.set_visible, False)
        host.target = mock.Mock(spec=RunTarget)
        controller = RunController(host)
        for reason in (None, 'Choose an input file'):
            with self.subTest(reason=reason):
                host.target.start_blocked_reason.return_value = reason
                host.target.start_blocked_reason.reset_mock()
                self.assertEqual(controller.refresh_start_readiness(), reason)
                host.target.start_blocked_reason.assert_called_once_with()
                host.enable_start.assert_called_with(reason is None)
                host.describe_start.assert_called_with(reason or 'Start processing')

    def test_live_counts_and_empty_state_survive_pinned_incremental_removal(self):
        from gi.repository import Gtk

        from bundled.constants import MDX_ARCH_TYPE
        from core.catalogue_types import CatalogueDelta, DeltaKind
        from tests.test_download_center_state import DownloadCenterStateTests

        win = DownloadCenterStateTests()._make_bare_window()
        win.manager.catalogue_meta_by_family = {}
        win._search_entry = Gtk.SearchEntry()
        win.browser.available = {MDX_ARCH_TYPE: ['Survivor', 'Removed']}
        win._rebuild_catalogue()
        survivor = win._row_actions[(MDX_ARCH_TYPE, 'Survivor')]
        with mock.patch.object(win, '_lookup_row_size'):
            win._row_checks[(MDX_ARCH_TYPE, 'Survivor')].set_active(True)
        pinned = SimpleNamespace(mdx={'Survivor': 'original-url'}, vr={}, demucs={}, apollo={})
        win.browser.pin(cast(Any, pinned))
        win._on_catalogue_delta(
            CatalogueDelta(kind=DeltaKind.SOURCES_CHANGED, added={'mdx': ('Added later',)})
        )
        cast(Any, win.manager.available_downloads).return_value = {
            MDX_ARCH_TYPE: ['Survivor', 'Added later']
        }
        cast(Any, win.manager.unsupported_downloads).return_value = {}
        win._flush_catalogue_row_refresh()
        self.assertEqual(win._matching_count(MDX_ARCH_TYPE, ''), 2)
        self.assertIn('2 available', win._search_entry.get_placeholder_text() or '')
        win._search_entry.set_text('Missing entry')
        win._update_catalogue_page_state(MDX_ARCH_TYPE)
        self.assertEqual(win._empty_pages[MDX_ARCH_TYPE].get_title(), 'No matching models')
        self.assertTrue(win._empty_pages[MDX_ARCH_TYPE].get_visible())
        win._search_entry.set_text('Added later')
        win._update_catalogue_page_state(MDX_ARCH_TYPE)
        self.assertFalse(win._empty_pages[MDX_ARCH_TYPE].get_visible())
        self.assertEqual(win._matching_count(MDX_ARCH_TYPE, 'Added later'), 1)
        self.assertIs(win._row_actions[(MDX_ARCH_TYPE, 'Survivor')], survivor)
        self.assertNotIn((MDX_ARCH_TYPE, 'Added later'), win.browser.rows)
        self.assertNotIn((MDX_ARCH_TYPE, 'Removed'), win.browser.rows)
        self.assertEqual(win.browser.selected_keys(), ((MDX_ARCH_TYPE, 'Survivor'),))
        self.assertIs(win.browser.snapshot, pinned)
        self.assertTrue(win.browser.pending_source)
        self.assertEqual(win.browser.pinned_catalogue(MDX_ARCH_TYPE), {'Survivor': 'original-url'})

    def test_live_count_metadata_keeps_supported_scope_and_unsupported_fallback(self):
        from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.catalogue_types import StemSemanticProjection
        from core.model_scores import PURPOSE_FX
        from tests.test_download_center_dedupe_refresh import _bare_window

        win = _bare_window()
        win._purpose = PURPOSE_FX

        def metadata(role: str):
            return EntryMeta(
                label='Neutral',
                display='Neutral',
                arch=MDX_ARCH_TYPE,
                stem_semantics=StemSemanticProjection(
                    backend_primary_stem=None,
                    backend_target_stem=None,
                    logical_primary_role=role,
                    logical_secondary_role=None,
                    status='reviewed',
                    context='full_mix',
                    routes=(),
                ),
            )

        crowd = metadata('cinematic.crowd')
        drums = metadata('music.drums')
        win.browser.available = {MDX_ARCH_TYPE: ['Neutral'], VR_ARCH_TYPE: ['Neutral']}
        win.browser.unsupported = {MDX_ARCH_TYPE: [('Unavailable', 'new build')]}
        win.manager.catalogue_meta_by_family = {'mdx': {'Neutral': crowd}}
        win.manager.catalogue_meta = {'Neutral': drums, 'Unavailable': crowd}
        self.assertEqual(win._matching_count(MDX_ARCH_TYPE, ''), 2)
        self.assertEqual(win._matching_count(VR_ARCH_TYPE, ''), 0)
        win.manager.catalogue_meta_by_family = {}
        win.manager.catalogue_meta = {'Neutral': crowd, 'Unavailable': crowd}
        self.assertEqual(win._matching_count(MDX_ARCH_TYPE, ''), 1)
        self.assertEqual(win._matching_count(VR_ARCH_TYPE, ''), 0)
        win._hide_unsupported = True
        self.assertEqual(win._matching_count(MDX_ARCH_TYPE, ''), 0)
