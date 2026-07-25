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


if __name__ == "__main__":
    unittest.main()
