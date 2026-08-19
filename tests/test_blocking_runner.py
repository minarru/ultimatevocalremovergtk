from __future__ import annotations

import unittest

from core.blocking_runner import RunResult, run_blocking
from core.job_callbacks import JobCallbacks


class FakeRunner:
    def __init__(self, running: bool = False) -> None:
        self.running = running
        self.stops: list[bool] = []
        self._thread = None

    def is_running(self) -> bool:
        return self.running

    def stop(self, *, force: bool = False) -> None:
        self.stops.append(force)
        self.running = False


class BlockingRunnerTests(unittest.TestCase):
    def test_success_collects_console(self) -> None:
        runner = FakeRunner()

        def start(callbacks: JobCallbacks) -> None:
            callbacks.console("ready\n")
            callbacks.complete()

        result = run_blocking(runner, start)
        self.assertIsInstance(result, RunResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.console, ("ready\n",))

    def test_callback_error_is_structured(self) -> None:
        error = RuntimeError("failed")
        result = run_blocking(FakeRunner(), lambda callbacks: callbacks.error(error))
        self.assertIs(result.error, error)
        self.assertFalse(result.ok)

    def test_start_error_is_structured(self) -> None:
        error = ValueError("bad start")

        def start(_callbacks: JobCallbacks) -> None:
            raise error

        result = run_blocking(FakeRunner(), start)
        self.assertIs(result.error, error)

    def test_timeout_force_stops_and_returns_error(self) -> None:
        runner = FakeRunner(running=True)
        result = run_blocking(runner, lambda _callbacks: None, timeout=0.001)
        self.assertIsInstance(result.error, TimeoutError)
        self.assertTrue(result.stopped)
        self.assertEqual(runner.stops, [True])


if __name__ == "__main__":
    unittest.main()
