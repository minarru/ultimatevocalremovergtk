"""Terminal run transitions through a constructed window and its real GTK host."""

from __future__ import annotations

import copy
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class RunTerminalUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        cls.app = Adw.Application(application_id="org.uvr.test.run-terminal")
        cls.app.register()

    def setUp(self) -> None:
        from core.access_policy import access_policy
        from core.settings import Settings
        from ui.window import MainWindow

        scratch = self.enterContext(tempfile.TemporaryDirectory())
        settings = Settings.defaults()
        settings.path = str(Path(scratch) / "settings.json")
        settings.process.input_paths = []
        settings.process.export_path = scratch
        self.enterContext(access_policy(allow_network=False, allow_metadata_writes=False))
        self.enterContext(mock.patch("ui.context.Settings.load", return_value=settings))
        self.window: Any = MainWindow(application=self.app)
        self.addCleanup(self.window.set_application, None)
        self.addCleanup(self.window._unsubscribe_model_events)
        self.addCleanup(self.window.log_panel.stop_progress_pulse)
        self.addCleanup(self.window.log_panel._cancel_done_collapse)
        self.addCleanup(self.window.log_panel.set_start_blocked_reason, None)
        self.addCleanup(self.window.set_visible, False)
        self.window.present()
        from gi.repository import GLib

        deadline = time.monotonic() + 5
        while not self.window.get_mapped():
            self.assertLess(time.monotonic(), deadline, "window did not map")
            GLib.MainContext.default().iteration(False)
        # Do not seed this field: the missing constructor initialization was
        # the cause of the real completion failure.
        self.assertIsNone(self.window._deferred_model_refresh)
        self.controller = self.window._run_controller
        self.target = mock.Mock(run_label="Separation", error_key="fixture")
        self.target.start_blocked_reason.return_value = None
        self.window._run_target = self.target
        self.complete_toast = self.enterContext(
            mock.patch.object(self.controller, "_show_complete_toast")
        )
        for method in (
            "_send_completion_notification",
            "_send_failure_notification",
            "_schedule_release_inference_memory",
            "_report_error",
        ):
            self.enterContext(mock.patch.object(self.controller, method))

    def _begin(self) -> None:
        settings = copy.deepcopy(self.window.settings)
        self.controller._host.bind_run_settings(settings)
        self.window._audio_tools_page.bind_run_settings(settings)
        self.controller.begin_run(self.target)
        self.assertTrue(self.window.stop_button.get_sensitive())
        self.assertFalse(self.window.start_button.get_sensitive())
        self.assertTrue(all(not p.get_sensitive() for p in self.window._options_pages))

    def _finish(self, outcome: str) -> None:
        if outcome == "complete":
            self.controller._on_complete()
        elif outcome == "stopped":
            self.controller._on_stopped()
        elif outcome == "error":
            self.controller._on_error(RuntimeError("fixture failure"))
        else:
            self.controller.fail_to_start("Unable to start fixture", RuntimeError("launch"))

    def _check_terminal(self, outcome: str, reason: str | None, *, deferred: bool) -> None:
        self._begin()
        if deferred:
            self.window._refresh_models(source="terminal_test")
            self.assertEqual(self.window._deferred_model_refresh, "terminal_test")

        readiness_states = []

        def readiness() -> str | None:
            # Every readiness evaluation during unlocking, including one from
            # deferred model refresh, must see restored idle state.
            readiness_states.append(
                (
                    self.controller._running_target is None,
                    self.window.context.runner.settings is self.window.settings,
                    self.window._audio_tools_page.runner.settings is self.window.settings,
                )
            )
            return reason

        with mock.patch.object(self.target, "start_blocked_reason", side_effect=readiness) as check:
            with mock.patch.object(
                self.window, "_apply_model_refresh", wraps=self.window._apply_model_refresh
            ) as refresh:
                self._finish(outcome)
                if deferred:
                    refresh.assert_called_once_with(source="terminal_test")
                else:
                    refresh.assert_not_called()
            self.assertGreater(check.call_count, 0)
        self.assertTrue(all(state == (True, True, True) for state in readiness_states))
        self.assertIsNone(self.window._deferred_model_refresh)
        self.assertIsNone(self.controller._running_target)
        self.assertFalse(self.controller.is_running())
        self.assertFalse(self.window.stop_button.get_sensitive())
        self.assertEqual(self.window.start_button.get_sensitive(), reason is None)
        self.assertTrue(all(p.get_sensitive() for p in self.window._options_pages))
        for name in ("settings", "view_inputs", "download"):
            self.assertTrue(self.window.lookup_action(name).get_enabled())
        self.assertEqual(self.window.start_button.get_tooltip_text(), reason or "Start processing")
        status = self.window.log_panel._progress_status
        if outcome == "complete":
            self.assertEqual(status, "Done")
            self.complete_toast.assert_called_once()
        else:
            self.assertNotEqual(status, "Done")
            self.complete_toast.assert_not_called()
            if outcome == "error":
                self.assertEqual(status, "Failed")
        self.target.start_blocked_reason.return_value = None
        self.controller.refresh_start_readiness()
        self.assertTrue(self.window.start_button.get_sensitive())
        self._begin()
        self.controller._on_stopped()

    def test_terminal_outcomes_restore_ready_and_blocked_controls(self) -> None:
        for outcome in ("complete", "stopped", "error", "fail_to_start"):
            for reason in (None, "Choose an input file"):
                with self.subTest(outcome=outcome, reason=reason):
                    self.complete_toast.reset_mock()
                    self._check_terminal(outcome, reason, deferred=False)

    def test_terminal_outcomes_apply_deferred_refresh_after_restoring_settings(self) -> None:
        for outcome in ("complete", "stopped", "error", "fail_to_start"):
            for reason in (None, "Choose a model"):
                with self.subTest(outcome=outcome, reason=reason):
                    self.complete_toast.reset_mock()
                    self._check_terminal(outcome, reason, deferred=True)

    def test_requested_stop_stays_locked_until_worker_reports_stopped(self) -> None:
        self._begin()
        with mock.patch.object(self.controller.shutdown, "schedule_inference_cleanup"):
            self.controller._confirm_stop(self.target)
        self.target.stop.assert_called_once()
        self.assertIs(self.controller._running_target, self.target)
        self.assertTrue(self.controller.is_running())
        self.window._refresh_models(source="stopping_test")
        self.assertEqual(self.window._deferred_model_refresh, "stopping_test")
        self.assertFalse(self.window.start_button.get_sensitive())
        self.assertFalse(self.window.stop_button.get_sensitive())
        self.assertTrue(all(not p.get_sensitive() for p in self.window._options_pages))
        self.assertEqual(self.window.log_panel._progress_status, "Stopping…")
        self.controller.refresh_start_readiness()
        self.assertFalse(self.window.start_button.get_sensitive())
        self.controller._on_stopped()
        self.assertIsNone(self.controller._running_target)
        self.assertTrue(self.window.start_button.get_sensitive())
        self.assertFalse(self.window.stop_button.get_sensitive())
        self.assertTrue(all(p.get_sensitive() for p in self.window._options_pages))
        self.complete_toast.assert_not_called()

    def test_forced_stop_cleanup_restores_controls_without_worker_callback(self) -> None:
        self._begin()
        self.target.worker_is_running.return_value = True
        lifecycle = self.controller.shutdown
        with mock.patch.object(lifecycle, "release") as release:
            with mock.patch.object(lifecycle.scheduler, "timeout_add"):
                self.controller._confirm_stop(self.target)
                lifecycle.cleanup_attempts = 79
                self.assertFalse(lifecycle.poll_inference_cleanup())
                release.assert_called_once()
                self.assertTrue(release.call_args.kwargs["force_if_alive"])
                self.assertFalse(self.window.start_button.get_sensitive())
                self.assertTrue(self.controller.is_running())
                # A forced KThread exit can omit the normal stopped callback.
                # The coordinator must recover only after cleanup and exit.
                self.target.worker_is_running.return_value = False
                release.call_args.kwargs["on_done"]()
        self.assertFalse(self.controller.is_running())
        self.assertIsNone(self.controller._running_target)
        self.assertIsNone(lifecycle.cleanup_target)
        self.assertTrue(self.window.start_button.get_sensitive())
        self.assertFalse(self.window.stop_button.get_sensitive())
        self.assertTrue(all(p.get_sensitive() for p in self.window._options_pages))
        self.assertIs(self.window.context.runner.settings, self.window.settings)
        self.assertEqual(self.window.log_panel._progress_status, "")
        self.complete_toast.assert_not_called()
