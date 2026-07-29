import typing
import unittest
from unittest.mock import MagicMock, patch

from ui.dispatch import gtk_job_callbacks, idle_on_main, main_thread


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

    @patch("ui.dispatch.main_thread", side_effect=lambda func: func)
    def test_gtk_job_callbacks_wraps_handlers(self, _main_thread: typing.Any):
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

    @patch("ui.dispatch.main_thread", side_effect=lambda func: func)
    def test_gtk_job_callbacks_forward_progress_metadata(self, _main_thread: typing.Any):
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
