"""Tests for the suspend inhibitor held while a run is processing."""

import unittest
from typing import Any, cast
from unittest import mock

from gi.repository import Gtk

from ui.run_control import RunController
from ui.run_host import GtkRunHost
from ui.sleep_inhibit import SleepInhibitor


def _inhibitor(app: Any, window: Any = None) -> SleepInhibitor:
    return SleepInhibitor(lambda: app, lambda: window)


class SleepInhibitorTests(unittest.TestCase):
    def test_acquire_inhibits_suspend_with_reason(self) -> None:
        app = mock.Mock()
        app.inhibit.return_value = 7
        window = object()
        inhibitor = _inhibitor(app, window)

        inhibitor.acquire("Separation in progress")

        app.inhibit.assert_called_once_with(
            window, Gtk.ApplicationInhibitFlags.SUSPEND, "Separation in progress"
        )
        self.assertTrue(inhibitor.active)

    def test_acquire_is_idempotent(self) -> None:
        app = mock.Mock()
        app.inhibit.return_value = 7
        inhibitor = _inhibitor(app)

        inhibitor.acquire("a")
        inhibitor.acquire("b")

        app.inhibit.assert_called_once()

    def test_release_uninhibits_the_acquired_cookie(self) -> None:
        app = mock.Mock()
        app.inhibit.return_value = 7
        inhibitor = _inhibitor(app)
        inhibitor.acquire("run")

        inhibitor.release()
        inhibitor.release()

        app.uninhibit.assert_called_once_with(7)
        self.assertFalse(inhibitor.active)

    def test_refused_inhibit_is_not_released(self) -> None:
        app = mock.Mock()
        app.inhibit.return_value = 0  # session manager declined
        inhibitor = _inhibitor(app)

        inhibitor.acquire("run")
        inhibitor.release()

        self.assertFalse(inhibitor.active)
        app.uninhibit.assert_not_called()

    def test_missing_application_is_a_no_op(self) -> None:
        inhibitor = _inhibitor(None)

        inhibitor.acquire("run")
        inhibitor.release()

        self.assertFalse(inhibitor.active)

    def test_inhibit_failure_never_breaks_the_run(self) -> None:
        app = mock.Mock()
        app.inhibit.side_effect = RuntimeError("no session bus")
        inhibitor = _inhibitor(app)

        inhibitor.acquire("run")

        self.assertFalse(inhibitor.active)

    def test_release_targets_the_application_that_granted_the_cookie(self) -> None:
        first, second = mock.Mock(), mock.Mock()
        first.inhibit.return_value = 3
        apps = iter([first, second])
        inhibitor = SleepInhibitor(lambda: next(apps), lambda: None)

        inhibitor.acquire("run")
        inhibitor.release()

        first.uninhibit.assert_called_once_with(3)
        second.uninhibit.assert_not_called()


class RunControllerSleepInhibitTests(unittest.TestCase):
    def _controller(self) -> tuple[RunController, mock.Mock]:
        app = mock.Mock()
        app.inhibit.return_value = 11
        window = mock.Mock()
        window._options_pages = []
        window.lookup_action.return_value = None
        window.get_application.return_value = app
        return RunController(GtkRunHost(cast(Any, window))), app

    def test_running_holds_the_inhibitor_until_idle(self) -> None:
        controller, app = self._controller()

        controller._set_running(True)
        app.inhibit.assert_called_once()
        app.uninhibit.assert_not_called()

        controller._set_running(False)
        app.uninhibit.assert_called_once_with(11)

    def test_reason_names_the_run(self) -> None:
        controller, app = self._controller()
        controller._run_label = "Ensemble"

        controller._set_running(True)

        self.assertEqual(app.inhibit.call_args.args[2], "Ensemble in progress")


if __name__ == "__main__":
    unittest.main()
