import unittest
from unittest import mock

from ui.run_control import RunController, _format_mmss


class FormatMmssTests(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_format_mmss(0), "0:00")

    def test_under_one_minute(self):
        self.assertEqual(_format_mmss(42.9), "0:42")

    def test_over_one_minute(self):
        self.assertEqual(_format_mmss(125), "2:05")


class SetRunningUnlockTests(unittest.TestCase):
    def test_unlock_keeps_model_options_enabled(self) -> None:
        """Regression: unlock must clear Stop before syncing Model options.

        ``is_running()`` is ``_running_target and stop_button.sensitive``. If
        sync runs while Stop is still sensitive, Model options is disabled
        again after a completed separation.
        """
        stop_sensitive = {"value": True}
        stop_button = mock.Mock()
        stop_button.get_sensitive.side_effect = lambda: stop_sensitive["value"]
        stop_button.set_sensitive.side_effect = lambda value: stop_sensitive.__setitem__(
            "value", bool(value)
        )

        model_options = mock.Mock()
        actions = {
            "settings": mock.Mock(),
            "view_inputs": mock.Mock(),
            "model_options": model_options,
        }

        window = mock.Mock()
        window.stop_button = stop_button
        window.start_button = mock.Mock()
        window._options_pages = []
        window.lookup_action.side_effect = lambda name: actions.get(name)

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._running_target = object()

        def sync_model_options_action() -> None:
            model_options.set_enabled(not controller.is_running())

        window._sync_model_options_action = sync_model_options_action

        controller._set_running(False)

        self.assertFalse(controller.is_running())
        model_options.set_enabled.assert_called_with(True)


class HandleCloseRequestTests(unittest.TestCase):
    def test_closing_window_force_closes_stale_stop_confirm_dialog(self) -> None:
        """Regression: a Stop-confirm dialog left open when the window closes
        must be force-closed, not just have its Python reference dropped —
        otherwise its response/closed handlers stay live against state the
        shutdown-confirm flow (presented right after) goes on to mutate.
        """
        stop_button = mock.Mock()
        stop_button.get_sensitive.return_value = True
        window = mock.Mock()
        window.stop_button = stop_button

        controller = RunController.__new__(RunController)
        controller._window = window
        target = mock.Mock()
        controller._running_target = target
        controller._on_close_complete = None
        controller._shutdown_dialog = None
        stale_dialog = mock.Mock()
        controller._stop_confirm_dialog = stale_dialog
        controller._run_ui_suspended = True
        controller._close_deferred = False
        controller._present_shutdown_confirm = mock.Mock()

        result = controller.handle_close_request(lambda _keep_open: None)

        self.assertTrue(result)
        stale_dialog.force_close.assert_called_once()
        self.assertIsNone(controller._stop_confirm_dialog)
        target.unpause.assert_called_once()
        controller._present_shutdown_confirm.assert_called_once()

    def test_active_downloads_alone_require_shutdown_confirmation(self) -> None:
        stop_button = mock.Mock()
        stop_button.get_sensitive.return_value = False
        context = mock.Mock()
        context.active_download_count.return_value = 2
        window = mock.Mock(stop_button=stop_button, context=context)

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._running_target = None
        controller._on_close_complete = None
        controller._shutdown_dialog = None
        controller._stop_confirm_dialog = None
        controller._close_deferred = False
        controller._present_shutdown_confirm = mock.Mock()

        result = controller.handle_close_request(lambda _deferred: None)

        self.assertTrue(result)
        self.assertTrue(controller._close_deferred)
        controller._present_shutdown_confirm.assert_called_once_with()

    def test_shutdown_poll_waits_for_download_cleanup(self) -> None:
        context = mock.Mock()
        context.active_download_count.side_effect = [1, 0]
        window = mock.Mock(context=context)

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._shutdown_target = None
        controller._shutdown_attempts = 0
        controller._close_deferred = True
        controller._complete_shutdown = mock.Mock()

        self.assertTrue(controller._poll_shutdown())
        self.assertFalse(controller._poll_shutdown())
        controller._complete_shutdown.assert_called_once_with(deferred=True)


class ApplicationQuitTests(unittest.TestCase):
    def test_quit_action_closes_main_window_through_its_guard(self) -> None:
        from ui.application import UVRApplication

        window = mock.Mock()
        app = mock.Mock(_main_window=window)

        UVRApplication._on_quit_requested(app)

        window.close.assert_called_once_with()
        app.quit.assert_not_called()


class OnProgressBarTests(unittest.TestCase):
    def _controller(self) -> tuple[RunController, mock.Mock]:
        from core.run_estimate import ProgressEtaTracker

        window = mock.Mock()
        window.log_panel = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._run_ui_suspended = False
        controller._eta_tracker = ProgressEtaTracker()
        controller._last_progress_ui_at = 0.0
        controller._last_progress_phase = None
        controller._last_progress_pass = None
        controller._last_progress_combine = None
        controller._run_started_at = 0.0
        return controller, window

    def test_save_ticks_move_the_bar(self) -> None:
        controller, window = self._controller()
        controller._on_progress(0.4, local_step=0.50, pass_index=1, pass_total=1)
        first = window.log_panel.set_progress_fraction.call_args[0][0]
        controller._last_progress_ui_at = 0.0
        controller._on_progress(0.93, local_step=0.93, pass_index=1, pass_total=1)
        second = window.log_panel.set_progress_fraction.call_args[0][0]
        self.assertGreater(second, first)
        self.assertAlmostEqual(second, 0.93)

    def test_load_without_fill_pulses(self) -> None:
        controller, window = self._controller()
        controller._on_progress(0.05, local_step=0.05, pass_index=1, pass_total=1)
        window._start_pulse.assert_called()
        window.log_panel.set_progress_fraction.assert_not_called()


class AudioPreflightTests(unittest.TestCase):
    def test_audio_plan_skips_confirmation_but_still_uses_acceptance_recheck(self) -> None:
        from bundled.constants import TIME_STRETCH
        from core.audio_plan import ResolvedAudioJob
        from core.job_plan import ValidationLevel
        from core.settings import Settings

        settings = Settings.defaults()
        plan = ResolvedAudioJob(
            TIME_STRETCH, settings, "/tmp/out", (), {}, (),
            ValidationLevel.RUNTIME, 0, "fingerprint", "cpu",
        )
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._accept_plan = mock.Mock()
        controller._present_plan_confirmation = mock.Mock()
        target = object()

        controller._finish_preflight(target, "fingerprint", plan, None)

        controller._accept_plan.assert_called_once_with(target, "fingerprint", plan)
        controller._present_plan_confirmation.assert_not_called()


class StartTargetSettingsCopyTests(unittest.TestCase):
    def test_start_target_does_not_mutate_window_settings(self) -> None:
        from core.settings import Settings

        window_settings = Settings.defaults()
        self.assertIsNone(window_settings.mdx.compensate)

        plan_settings = Settings.defaults()
        plan_settings.mdx.compensate = 1.055
        plan = mock.Mock(settings=plan_settings)

        runner = mock.Mock()
        runner.settings = window_settings
        context = mock.Mock()
        context._runner = runner
        context.runner = runner

        window = mock.Mock()
        window.settings = window_settings
        window.context = context

        target = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._callbacks = mock.Mock(return_value=object())

        controller._start_target(target, plan)

        self.assertIsNone(window.settings.mdx.compensate)
        self.assertEqual(window.context.runner.settings.mdx.compensate, 1.055)
        target.start.assert_called_once()

    def test_start_target_applies_plan_to_audio_tools_page_runner(self) -> None:
        from core.settings import Settings

        window_settings = Settings.defaults()
        plan_settings = Settings.defaults()
        plan_settings.mdx.compensate = 1.055
        plan = mock.Mock(settings=plan_settings)

        context_runner = mock.Mock()
        context_runner.settings = window_settings
        context = mock.Mock()
        context._runner = context_runner
        context.runner = context_runner

        page_runner = mock.Mock()
        page_runner.settings = window_settings
        target = mock.Mock()
        target._runner = page_runner

        window = mock.Mock()
        window.settings = window_settings
        window.context = context
        window._audio_tools_page = target

        controller = RunController.__new__(RunController)
        controller._window = window
        controller._callbacks = mock.Mock(return_value=object())

        controller._start_target(target, plan)

        self.assertIsNone(window.settings.mdx.compensate)
        self.assertEqual(page_runner.settings.mdx.compensate, 1.055)
        self.assertIsNot(page_runner.settings, plan.settings)

        controller._restore_runner_settings()
        self.assertIs(page_runner.settings, window_settings)
        self.assertIs(context_runner.settings, window_settings)


class PlanRecheckTests(unittest.TestCase):
    def test_finished_recheck_starts_only_when_settings_and_models_are_current(self) -> None:
        from core.job_plan import settings_fingerprint
        from core.settings import Settings

        settings = Settings.defaults()
        target = mock.Mock()
        target.build_job_spec.return_value = mock.Mock(settings=settings)
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._start_target = mock.Mock()
        controller._begin_preflight = mock.Mock()
        plan = object()

        controller._finish_plan_recheck(
            target, settings_fingerprint(settings), plan, True, None
        )

        controller._set_preflight_busy.assert_called_once_with(False)
        controller._start_target.assert_called_once_with(target, plan)
        controller._begin_preflight.assert_not_called()

    def test_stale_recheck_returns_to_preflight(self) -> None:
        from core.job_plan import settings_fingerprint
        from core.settings import Settings

        settings = Settings.defaults()
        target = mock.Mock()
        target.build_job_spec.return_value = mock.Mock(settings=settings)
        window = mock.Mock()
        controller = RunController.__new__(RunController)
        controller._window = window
        controller._set_preflight_busy = mock.Mock()
        controller._start_target = mock.Mock()
        controller._begin_preflight = mock.Mock()

        controller._finish_plan_recheck(
            target, settings_fingerprint(settings), object(), False, None
        )

        controller._start_target.assert_not_called()
        controller._begin_preflight.assert_called_once_with(target)


if __name__ == "__main__":
    unittest.main()
