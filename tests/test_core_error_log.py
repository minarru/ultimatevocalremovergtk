"""Shared recording semantics and contention, independent of GTK."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from core import error_log


class ErrorLogStoreTests(unittest.TestCase):
    def test_join_clear_empty_and_reentrant_notification(self) -> None:
        store = error_log.ErrorLogStore()
        seen = []
        unsubscribe = store.subscribe(lambda: seen.append(store.get()))
        store.set('seed \n')
        store.append('  first')
        store.append('')
        self.assertEqual(seen, ['seed \n', 'seed\n\n---\n\nfirst'])
        unsubscribe()
        unsubscribe()
        store.set('')
        self.assertEqual(store.get(), '')
        self.assertEqual(len(seen), 2)

    def test_contended_appends_keep_both_entries_and_notify_outside_lock(self) -> None:
        store = error_log.ErrorLogStore()
        store.set('seed')
        first_entered = threading.Event()
        second_waiting = threading.Event()
        lock = threading.Lock()

        class ContendedLock:
            def __enter__(self):
                if threading.current_thread().name == 'second':
                    second_waiting.set()
                lock.acquire()
                if threading.current_thread().name == 'first':
                    first_entered.set()
                    if not second_waiting.wait(5):
                        raise AssertionError('second writer never contended')

            def __exit__(self, *args: object):
                lock.release()

        seen = []
        unsubscribe = store.subscribe(lambda: seen.append(store.get()))
        with patch.object(store, '_lock', ContendedLock()):
            first = threading.Thread(name='first', target=store.append, args=('first',))
            second = threading.Thread(name='second', target=store.append, args=('second',))
            first.start()
            self.assertTrue(first_entered.wait(5))
            second.start()
            first.join(5)
            second.join(5)
            self.assertFalse(first.is_alive() or second.is_alive())
        unsubscribe()
        self.assertEqual(store.get(), 'seed\n\n---\n\nfirst\n\n---\n\nsecond')
        self.assertEqual(len(seen), 2)

    def test_shared_worker_context_and_event_fields(self) -> None:
        from core.error_context import clear_run_error_context, set_run_error_context

        error_log.set_error_log('')
        set_run_error_context(process='MDX-Net', models=['shared model'])
        self.addCleanup(clear_run_error_context)
        exc = ValueError('bad input')
        with patch('core.debug_log.log_event') as event:
            worker = threading.Thread(target=error_log.log_error, args=('Download', exc))
            worker.start()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertIn('shared model', error_log.get_error_log())
        self.assertEqual(event.call_args.args, ('error', 'ui_error'))
        self.assertEqual(event.call_args.kwargs['error_type'], 'ValueError')
        self.assertEqual(event.call_args.kwargs['error'], 'bad input')

    def test_disposing_duplicate_callback_subscription_is_idempotent(self) -> None:
        store = error_log.ErrorLogStore()
        seen = []

        def changed() -> None:
            seen.append(store.get())

        first = store.subscribe(changed)
        second = store.subscribe(changed)
        first()
        first()
        store.set("remaining subscription")
        self.assertEqual(seen, ["remaining subscription"])
        second()

    def test_notification_can_unsubscribe_itself(self) -> None:
        store = error_log.ErrorLogStore()
        seen = []

        def changed() -> None:
            unsubscribe()
            seen.append(store.get())

        unsubscribe = store.subscribe(changed)
        worker = threading.Thread(target=store.append, args=('first',), daemon=True)
        worker.start()
        worker.join(5)
        self.assertFalse(worker.is_alive(), 'notification ran under storage lock')
        store.append('second')
        self.assertEqual(seen, ['first'])
