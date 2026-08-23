"""JobCallbacks lives in core.job_callbacks, not job_runner."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


class JobCallbacksHomeTests(unittest.TestCase):
    def test_job_runner_source_does_not_define_job_callbacks(self) -> None:
        source = (_REPO / "core" / "job_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("class JobCallbacks", source)

    def test_job_callbacks_importable_from_own_module(self) -> None:
        from core.job_callbacks import JobCallbacks

        self.assertTrue(callable(JobCallbacks))

    def test_core_package_reexports_the_same_class(self) -> None:
        import core
        from core.job_callbacks import JobCallbacks

        self.assertIs(core.JobCallbacks, JobCallbacks)

    def test_job_runner_module_has_no_job_callbacks_attribute(self) -> None:
        import core.job_runner as job_runner

        self.assertFalse(hasattr(job_runner, "JobCallbacks"))


class JobCallbacksDiagnosticsTests(unittest.TestCase):
    def test_console_chunks_are_trace_only_and_errors_are_always_recorded(self) -> None:
        from core import debug_log
        from core.job_callbacks import JobCallbacks

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))
            self.addCleanup(debug_log.configure, level="errors", log_file="")
            callbacks = JobCallbacks(on_console=lambda _text: None)
            callbacks.console("model output")
            callbacks.error(RuntimeError("worker failed"))

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertNotIn("event=console_chunk", diagnostic)
            self.assertIn("event=callback_error", diagnostic)
            self.assertIn("error_type='RuntimeError'", diagnostic)

            debug_log.configure(level="trace", log_file=str(log_path))
            callbacks.console("model output")
            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertIn("level=TRACE", diagnostic)
            self.assertIn("event=console_chunk", diagnostic)
