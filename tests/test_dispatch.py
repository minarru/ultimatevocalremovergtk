import typing
import unittest
from unittest.mock import MagicMock, patch

from ui.dispatch import gtk_job_callbacks, idle_on_main, latest_main_thread, main_thread


class DispatchTests(unittest.TestCase):
    @patch("ui.dispatch.GLib.idle_add")
    def test_idle_on_main_schedules_once(self, idle_add: typing.Any):
        calls = []

        def capture(func: typing.Any):
            func()
            return True

        idle_add.side_effect = capture
        idle_on_main(calls.append, "done")
        self.assertEqual(calls, ["done"])

    @patch("ui.dispatch.GLib.idle_add")
    def test_main_thread_wrapper(self, idle_add: typing.Any):
        seen = []

        def capture(func: typing.Any):
            func()
            return True

        idle_add.side_effect = capture
        wrapped = main_thread(lambda value: seen.append(value))
        wrapped("ok")
        self.assertEqual(seen, ["ok"])

    @patch("ui.dispatch.GLib.idle_add")
    def test_latest_main_thread_bounds_pending_work_and_delivers_newest(
        self, idle_add: typing.Any
    ) -> None:
        pending = []
        idle_add.side_effect = lambda func: pending.append(func) or len(pending)
        seen = []
        wrapped = latest_main_thread(seen.append)

        for value in range(100):
            wrapped(value)

        self.assertEqual(len(pending), 1)
        pending.pop()()
        self.assertEqual(seen, [99])

        wrapped(100)
        self.assertEqual(len(pending), 1)
        pending.pop()()
        self.assertEqual(seen, [99, 100])

    @patch("ui.dispatch.GLib.idle_add")
    def test_coalesced_progress_delivers_final_value_before_completion(
        self, idle_add: typing.Any
    ) -> None:
        pending = []
        idle_add.side_effect = lambda func: pending.append(func) or len(pending)
        seen = []
        callbacks = gtk_job_callbacks(
            on_progress=lambda value, **_metadata: seen.append(("progress", value)),
            on_complete=lambda: seen.append(("complete", None)),
        )

        callbacks.progress(0.2)
        callbacks.progress(0.8)
        callbacks.progress(1.0)
        callbacks.complete()

        self.assertEqual(len(pending), 2)
        pending.pop(0)()
        pending.pop(0)()
        self.assertEqual(seen, [("progress", 1.0), ("complete", None)])

    @patch("ui.dispatch.latest_main_thread", side_effect=lambda func: func)
    @patch("ui.dispatch.main_thread", side_effect=lambda func: func)
    def test_gtk_job_callbacks_wraps_handlers(
        self, _main_thread: typing.Any, _latest_main_thread: typing.Any
    ):
        progress = MagicMock()
        console = MagicMock()
        complete = MagicMock()
        stopped = MagicMock()
        error = MagicMock()

        callbacks = gtk_job_callbacks(
            on_progress=progress,
            on_console=console,
            on_complete=complete,
            on_stopped=stopped,
            on_error=error,
        )

        callbacks.progress(0.5)
        callbacks.console("line")
        callbacks.complete()
        callbacks.stopped()
        callbacks.error(RuntimeError("boom"))

        progress.assert_called_once()
        self.assertEqual(progress.call_args.args, (0.5,))
        # JobCallbacks.progress always forwards its metadata keywords; unset
        # ones arrive as None. Assert that rather than an exact kwarg set so
        # adding a field does not break this test.
        self.assertTrue(
            all(value is None for value in progress.call_args.kwargs.values()),
            f"unset progress metadata should forward as None: {progress.call_args.kwargs}",
        )
        console.assert_called_once_with("line")
        complete.assert_called_once_with()
        stopped.assert_called_once_with()
        error.assert_called_once()
        self.assertIsInstance(error.call_args.args[0], RuntimeError)

    @patch("ui.dispatch.latest_main_thread", side_effect=lambda func: func)
    @patch("ui.dispatch.main_thread", side_effect=lambda func: func)
    def test_gtk_job_callbacks_forward_progress_metadata(
        self, _main_thread: typing.Any, _latest_main_thread: typing.Any
    ):
        progress = MagicMock()
        callbacks = gtk_job_callbacks(on_progress=progress)

        callbacks.progress(0.25, pass_index=2, pass_total=5, detail="MDX")

        progress.assert_called_once()
        self.assertEqual(progress.call_args.args, (0.25,))
        self.assertEqual(progress.call_args.kwargs["pass_index"], 2)
        self.assertEqual(progress.call_args.kwargs["pass_total"], 5)
        self.assertEqual(progress.call_args.kwargs["detail"], "MDX")


if __name__ == "__main__":
    unittest.main()
