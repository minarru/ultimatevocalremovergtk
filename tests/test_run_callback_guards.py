"""Delayed UI deliveries belong to the operation that created them."""

import unittest
from unittest.mock import Mock, patch

from ui.run_control import RunController


class RunCallbackGuardsTests(unittest.TestCase):
    def setUp(self):
        self.host = Mock()
        self.controller = RunController(self.host)
        self.controller._operation_id = 'old'
        self.target = Mock()
        self.controller._running_target = self.target

    def test_old_stop_dialog_cannot_stop_a_new_run_on_same_page(self):
        dialog = Mock()
        handlers = {}
        dialog.connect.side_effect = lambda signal, cb, handlers=handlers: handlers.update(
            {signal: cb}
        )
        with patch('ui.run_control.Adw.AlertDialog', return_value=dialog):
            self.controller._present_stop_confirm()
        self.controller._operation_id = 'new'
        handlers['response'](dialog, 'stop')
        self.target.stop.assert_not_called()

    def test_deferred_cancel_cannot_resume_another_run(self):
        dialog = Mock()
        handlers = {}
        dialog.connect.side_effect = lambda signal, cb, handlers=handlers: handlers.update(
            {signal: cb}
        )
        deliveries = []
        with (
            patch('ui.run_control.Adw.AlertDialog', return_value=dialog),
            patch.object(
                self.controller,
                '_defer_dialog_action',
                side_effect=lambda callback, **_: deliveries.append(callback),
            ),
        ):
            self.controller._present_stop_confirm()
            handlers['response'](dialog, 'cancel')
        self.controller._operation_id = 'new'
        self.host.reset_mock()
        deliveries[0]()
        self.target.unpause.assert_not_called()
        self.host.set_pulse.assert_not_called()

    def test_stale_oom_delivery_unblocks_worker_without_presenting_dialog(self):
        with patch('ui.run_control.gtk_job_callbacks') as dispatch:
            self.controller._callbacks()
        self.controller._operation_id = 'new'
        request = Mock()
        with patch('ui.oom_dialog.present_oom_choice_dialog') as present:
            dispatch.call_args.kwargs['on_oom_choice'](request)
        present.assert_not_called()
        request.respond.assert_called_once_with('stop')

    def test_old_oom_choice_does_not_mutate_new_run(self):
        request = Mock()
        with patch('ui.oom_dialog.present_oom_choice_dialog') as present:
            self.controller._on_oom_choice(request)
        choice = present.call_args.kwargs['on_choice']
        self.controller._operation_id = 'new'
        self.host.reset_mock()
        choice('retry')
        self.host.set_pulse.assert_not_called()
        self.host.append_console.assert_not_called()
        request.respond.assert_called_once_with('stop')

    def test_closed_or_superseded_preflight_delivery_is_ignored(self):
        callback = Mock()
        self.controller._closing = True
        self.controller._deliver_operation('old', callback, 'result')
        self.controller._closing = False
        self.controller._deliver_operation('superseded', callback, 'result')
        callback.assert_not_called()
        self.controller._deliver_operation('old', callback, 'result')
        callback.assert_called_once_with('result')

    def test_window_close_invalidates_queued_run_deliveries(self):
        self.controller._running_target = None
        self.host.active_download_count.return_value = 0
        with patch('ui.run_control.gtk_job_callbacks') as dispatch:
            self.controller._callbacks()
        with patch.object(self.controller.shutdown, 'begin_exit_cleanup'):
            self.assertFalse(self.controller.handle_close_request(Mock()))
        self.host.reset_mock()
        dispatch.call_args.kwargs['on_progress'](1.0)
        dispatch.call_args.kwargs['on_console']('late output')
        dispatch.call_args.kwargs['on_complete']()
        self.assertTrue(self.controller._closing)
        self.host.set_progress_text.assert_not_called()
        self.host.append_console.assert_not_called()
        self.host.enable_start.assert_not_called()

    def test_terminal_dismisses_run_dialogs_without_resuming(self):
        dialog = Mock()
        self.controller._stop_confirm_dialog = dialog
        self.controller._restore_idle_controls()
        dialog.force_close.assert_called_once_with()
        self.assertIsNone(self.controller._stop_confirm_dialog)
        self.target.unpause.assert_not_called()


class ErrorAttributionTests(unittest.TestCase):
    def test_terminal_errors_keep_originating_page_after_tab_switch(self):
        for method in ('_on_error', 'fail_to_start'):
            with self.subTest(method=method):
                host = Mock()
                host.target.error_key = 'Separation'
                host.target.run_label = 'Separation'
                controller = RunController(host)
                target = Mock(error_key='Ensemble', run_label='Ensemble')
                controller._running_target = target
                with (
                    patch('ui.errorlog.log_error', return_value='report') as log,
                    patch('ui.errorlog.present_error_dialog') as dialog,
                    patch.object(controller, '_schedule_release_inference_memory'),
                    patch.object(controller, '_send_failure_notification'),
                ):
                    if method == '_on_error':
                        controller._on_error(ValueError('failed'))
                    else:
                        controller.fail_to_start('failed', ValueError('failed'))
                self.assertIsNone(controller.running_target)
                self.assertEqual(log.call_args.args[0], 'Ensemble')
                self.assertEqual(dialog.call_args.kwargs['heading'], 'Ensemble failed')


class StopTimeoutUiTests(unittest.TestCase):
    def test_timeout_offers_wait_or_quit_without_unlocking_live_worker(self):
        for response in ('wait', 'quit', 'stale'):
            with self.subTest(response=response):
                host, target, dialog = Mock(), Mock(), Mock()
                controller = RunController(host)
                controller._running_target = target
                controller._operation_id = 'run'
                handlers = {}
                dialog.connect.side_effect = lambda signal, cb, handlers=handlers: handlers.update(
                    {signal: cb}
                )
                with patch('ui.run_control.Adw.AlertDialog', return_value=dialog):
                    controller._on_stop_timeout(target)
                self.assertIs(controller.running_target, target)
                host.enable_start.assert_called_with(False)
                host.set_options_sensitive.assert_not_called()
                with (
                    patch.object(controller.shutdown, 'resume_inference_cleanup') as resume,
                    patch.object(controller, '_complete_shutdown') as quit_app,
                ):
                    if response == 'stale':
                        controller._running_target = None
                    handlers['response'](dialog, response)
                    self.assertEqual(resume.call_count, int(response == 'wait'))
                    self.assertEqual(quit_app.call_count, int(response == 'quit'))
