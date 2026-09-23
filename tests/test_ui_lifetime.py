"""Deferred UI work is discarded after terminal disposal, including recurring timers."""

import unittest
from unittest.mock import Mock

from tests.test_run_lifecycle import Scheduler
from ui.lifetime import UiLifetime


class UiLifetimeTests(unittest.TestCase):
    def test_dispose_removes_recurring_timer_and_queued_delivery(self):
        lifetime = UiLifetime()
        scheduler = Scheduler()
        delivered = Mock(return_value=True)
        lifetime.timeout(scheduler, 50, delivered)
        callback = scheduler.callbacks[0]
        self.assertTrue(callback())
        cleanup = Mock()
        lifetime.own(cleanup)
        lifetime.dispose()
        lifetime.dispose()
        self.assertFalse(callback())
        delivered.assert_called_once_with()
        cleanup.assert_called_once_with()
        self.assertEqual(scheduler.calls, [50, ('remove', 1)])

    def test_finished_timer_is_not_removed_again(self):
        lifetime = UiLifetime()
        scheduler = Scheduler()
        lifetime.timeout(scheduler, 50, lambda: False)
        self.assertFalse(scheduler.callbacks[0]())
        lifetime.dispose()
        self.assertEqual(scheduler.calls, [50])
