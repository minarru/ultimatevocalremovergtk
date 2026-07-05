import unittest
from unittest.mock import MagicMock, patch

from ui.dispatch import gtk_job_callbacks, idle_on_main, main_thread


class DispatchTests(unittest.TestCase):
    @patch("ui.dispatch.GLib.idle_add")
    def test_idle_on_main_schedules_once(self, idle_add):
        calls = []

        def capture(func):
            func()
            return True

        idle_add.side_effect = capture
        idle_on_main(calls.append, "done")
        self.assertEqual(calls, ["done"])

    @patch("ui.dispatch.GLib.idle_add")
    def test_main_thread_wrapper(self, idle_add):
        seen = []

        def capture(func):
            func()
            return True

        idle_add.side_effect = capture
        wrapped = main_thread(lambda value: seen.append(value))
        wrapped("ok")
        self.assertEqual(seen, ["ok"])

    @patch("ui.dispatch.main_thread", side_effect=lambda func: func)
    def test_gtk_job_callbacks_wraps_handlers(self, _main_thread):
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

        progress.assert_called_once_with(0.5)
        console.assert_called_once_with("line")
        complete.assert_called_once_with()
        stopped.assert_called_once_with()
        error.assert_called_once()
        self.assertIsInstance(error.call_args.args[0], RuntimeError)


if __name__ == "__main__":
    unittest.main()
