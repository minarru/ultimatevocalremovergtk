"""Headless ensemble entry point (no models, no torch — JobRunner is faked)."""

import unittest
from typing import Any, List, Optional, Sequence
from unittest import mock

from bundled.constants import ENSEMBLE_MODE
from core.headless_run import build_settings, run_ensemble_sync
from core.settings import Settings
from core.types import ProcessMethod


class _FakeRunner:
    """Records which start method was used and fires callbacks synchronously."""

    calls: List[str] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._thread = None
        self.error: Optional[BaseException] = None

    def is_running(self) -> bool:
        return False

    def start(self, input_paths: Sequence[str], callbacks: Any) -> None:
        _FakeRunner.calls.append("single")
        callbacks.complete()

    def start_ensemble(self, input_paths: Sequence[str], callbacks: Any) -> None:
        _FakeRunner.calls.append("ensemble")
        callbacks.console("combining\n")
        if self.error is not None:
            callbacks.error(self.error)
        else:
            callbacks.complete()

    def release_inference_memory(self, **kwargs: Any) -> None:
        pass

    def stop(self, **kwargs: Any) -> None:
        pass


class RunEnsembleSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeRunner.calls = []
        self.settings = Settings()
        self.settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        self.settings.process.export_path = "/tmp/sweep-export"

    def test_uses_start_ensemble(self) -> None:
        with mock.patch("core.headless_run.JobRunner", _FakeRunner):
            result = run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)
        self.assertEqual(_FakeRunner.calls, ["ensemble"])
        self.assertTrue(result.ok)
        self.assertIn("combining\n", result.console)

    def test_reports_error(self) -> None:
        boom = RuntimeError("member failed")

        def factory(settings: Settings) -> _FakeRunner:
            runner = _FakeRunner(settings)
            runner.error = boom
            return runner

        with mock.patch("core.headless_run.JobRunner", factory):
            result = run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)
        self.assertFalse(result.ok)
        self.assertIs(result.error, boom)

    def test_requires_input_paths(self) -> None:
        with self.assertRaises(ValueError):
            run_ensemble_sync(self.settings, [], print_console=False)

    def test_requires_export_path(self) -> None:
        self.settings.process.export_path = ""
        with self.assertRaises(ValueError):
            run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)


class BuildSettingsEnsembleTests(unittest.TestCase):
    def test_rejects_ensemble_by_default(self) -> None:
        settings = Settings()
        settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        with mock.patch("core.headless_run.Settings.load", return_value=settings):
            with self.assertRaises(ValueError):
                build_settings(export_path="/tmp/out")

    def test_allows_ensemble_when_opted_in(self) -> None:
        settings = Settings()
        settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        with mock.patch("core.headless_run.Settings.load", return_value=settings):
            built = build_settings(export_path="/tmp/out", allow_ensemble=True)
        self.assertEqual(built.process.method, ENSEMBLE_MODE)


if __name__ == "__main__":
    unittest.main()
