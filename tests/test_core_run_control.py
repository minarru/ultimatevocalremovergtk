import unittest

from core.run_control import ProcessStopped, check_stopped, pausable_callback


class _FakeRunner:
    def __init__(self):
        self._is_paused = False
        self._is_stopped = False


class RunControlTests(unittest.TestCase):
    def test_check_stopped_raises_when_stopped(self):
        runner = _FakeRunner()
        runner._is_stopped = True
        with self.assertRaises(ProcessStopped):
            check_stopped(runner)

    def test_pausable_callback_honors_stop(self):
        runner = _FakeRunner()
        runner._is_stopped = True
        wrapped = pausable_callback(runner, lambda: 42)
        with self.assertRaises(ProcessStopped):
            wrapped()


if __name__ == "__main__":
    unittest.main()
