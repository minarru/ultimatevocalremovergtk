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
        release.assert_called_once()
        self.assertTrue(release.call_args.kwargs['force_if_alive'])
        self.assertTrue(callable(release.call_args.kwargs['on_done']))

    def test_forced_stop_waits_for_worker_exit_then_finishes_once(self):
        scheduler = Scheduler()
        release = Mock()
        stopped = Mock()
        life = RunShutdownCoordinator(Mock(), scheduler, release, Mock(), stopped)
        target = Mock()
        target.worker_is_running.return_value = True
        life.schedule_inference_cleanup(target)
        life.cleanup_attempts = 79
        self.assertFalse(life.poll_inference_cleanup())
        release.call_args.kwargs['on_done']()
        stopped.assert_not_called()
        self.assertEqual(scheduler.calls, [50, 50])
        self.assertTrue(life.poll_inference_cleanup())
        release.assert_called_once()
        target.worker_is_running.return_value = False
        self.assertFalse(life.poll_inference_cleanup())
        stopped.assert_called_once_with(target)
        self.assertIsNone(life.cleanup_target)
        self.assertFalse(life.poll_inference_cleanup())
        release.call_args.kwargs['on_done']()
        stopped.assert_called_once()

    def test_stop_without_terminal_callback_finishes_after_memory_cleanup(self):
        release = Mock()
        stopped = Mock()
        life = RunShutdownCoordinator(Mock(), Scheduler(), release, Mock(), stopped)
        target = Mock()
        target.worker_is_running.return_value = False
        life.schedule_inference_cleanup(target)
        self.assertFalse(life.poll_inference_cleanup())
        self.assertFalse(release.call_args.kwargs['force_if_alive'])
        stopped.assert_not_called()
        release.call_args.kwargs['on_done']()
        stopped.assert_called_once_with(target)

    def test_cancelled_cleanup_does_not_deliver_terminal_callback(self):
        release = Mock()
        stopped = Mock()
        life = RunShutdownCoordinator(Mock(), Scheduler(), release, Mock(), stopped)
        target = Mock()
        target.worker_is_running.return_value = False
        life.schedule_inference_cleanup(target)
        life.poll_inference_cleanup()
        life.cleanup_target = None
        release.call_args.kwargs['on_done']()
        stopped.assert_not_called()

    def test_old_cleanup_cannot_finish_later_run_on_same_target(self):
        release = Mock()
        stopped = Mock()
        life = RunShutdownCoordinator(Mock(), Scheduler(), release, Mock(), stopped)
        target = Mock()
        target.worker_is_running.return_value = False
        life.schedule_inference_cleanup(target)
        life.poll_inference_cleanup()
        old_done = release.call_args.kwargs['on_done']
        life.schedule_inference_cleanup(target)
        old_done()
        stopped.assert_not_called()
        self.assertIs(life.cleanup_target, target)
        life.poll_inference_cleanup()
        release.call_args.kwargs['on_done']()
        stopped.assert_called_once_with(target)

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
