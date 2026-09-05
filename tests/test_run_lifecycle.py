"""Shutdown polling and exit cleanup have deterministic scheduling/ordering."""

import unittest
from typing import Callable
from unittest.mock import Mock

from ui.run_lifecycle import RunShutdownCoordinator


class Scheduler:
    def __init__(self):
        self.calls = []
        self.callbacks = []

    def timeout_add(self, delay: int, callback: Callable[[], bool]):
        self.calls.append(delay)
        self.callbacks.append(callback)
        return len(self.callbacks)

    def source_remove(self, ident: int):
        self.calls.append(('remove', ident))


class LifecycleTests(unittest.TestCase):
    def test_stop_poll_forces_only_at_eighty_attempts(self):
        scheduler = Scheduler()
        host = Mock()
        release = Mock()
        life = RunShutdownCoordinator(host, scheduler, release, Mock())
        target = Mock()
        target.worker_is_running.return_value = True
        life.schedule_inference_cleanup(target)
        self.assertEqual(scheduler.calls, [50])
        for _ in range(79):
            self.assertTrue(life.poll_inference_cleanup())
        release.assert_not_called()
        self.assertFalse(life.poll_inference_cleanup())
        release.assert_called_once_with(force_if_alive=True)

    def test_quit_waits_for_downloads_then_finishes(self):
        scheduler = Scheduler()
        host = Mock()
        host.active_download_count.side_effect = [1, 0]
        done = Mock()
        life = RunShutdownCoordinator(host, scheduler, Mock(), done)
        life.schedule_shutdown_poll(None)
        self.assertTrue(life.poll_shutdown())
        done.assert_not_called()
        self.assertFalse(life.poll_shutdown())
        done.assert_called_once_with()

    def test_exit_hold_timeout_release_quit_once(self):
        scheduler = Scheduler()
        host = Mock()
        release = Mock()
        life = RunShutdownCoordinator(host, scheduler, release, Mock())
        life.begin_exit_cleanup()
        life.begin_exit_cleanup()
        host.get_application.return_value.hold.assert_called_once_with()
        self.assertEqual(scheduler.calls, [10000])
        scheduler.callbacks[0]()
        release.call_args.kwargs['on_done']()
        host.stop_all_workers.assert_called_once_with(force=True)
        app = host.get_application.return_value
        app.release.assert_called_once_with()
        app.quit.assert_called_once_with()
