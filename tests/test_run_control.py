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


if __name__ == "__main__":
    unittest.main()
