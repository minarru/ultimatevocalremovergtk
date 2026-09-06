import unittest
from unittest.mock import Mock, patch

from ui.run_control import RunController


class ReadinessHintTests(unittest.TestCase):
    def setUp(self):
        self.host = Mock()
        self.host.target.start_blocked_reason.return_value = 'Choose a model'
        self.controller = RunController(self.host)

    def test_blocked_and_ready(self):
        self.controller.refresh_start_readiness()
        self.host.set_start_blocked_reason.assert_called_with('Choose a model')
        self.host.enable_start.assert_called_with(False)
        self.host.target.start_blocked_reason.return_value = None
        self.controller.refresh_start_readiness()
        self.host.set_start_blocked_reason.assert_called_with(None)
        self.host.enable_start.assert_called_with(True)

    def test_busy_hides_hint_and_keeps_start_disabled(self):
        for state in ('_preflight_in_progress', '_plan_dialog', '_running_target'):
            with self.subTest(state=state):
                controller = RunController(self.host)
                setattr(controller, state, True)
                controller.refresh_start_readiness()
                self.host.set_start_blocked_reason.assert_called_with(None)
                self.host.enable_start.assert_called_with(False)

    def test_terminal_restore_precedes_readiness(self):
        self.controller._running_target = Mock()

        def restored():
            self.assertIsNone(self.controller._running_target)
            self.host.target.start_blocked_reason.return_value = None

        self.host.restore_runner_settings.side_effect = restored
        self.controller._restore_idle_controls()
        self.host.enable_stop.assert_called_with(False)
        self.host.enable_start.assert_called_with(True)


class RunCallbackIdentityTests(unittest.TestCase):
    def test_old_terminal_callback_cannot_reset_a_new_run(self):
        controller = RunController(Mock())
        controller._operation_id = "old"
        with patch("ui.run_control.gtk_job_callbacks") as dispatch:
            controller._callbacks()
        callbacks = dispatch.call_args.kwargs
        controller._operation_id = "new"
        controller._running_target = Mock()
        for name, args in (
            ("on_complete", ()),
            ("on_stopped", ()),
            ("on_error", (RuntimeError("old"),)),
        ):
            with self.subTest(callback=name):
                callbacks[name](*args)
                self.assertIsNotNone(controller._running_target)
                self.assertEqual(controller._operation_id, "new")


class DeferredStopTests(unittest.TestCase):
    def test_stop_delivery_after_terminal_does_not_relock_controls(self):
        host = Mock()
        controller = RunController(host)
        controller._confirm_stop(Mock())
        host.enable_start.assert_not_called()
        host.enable_stop.assert_not_called()
