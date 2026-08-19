"""JobCallbacks lives in core.job_callbacks, not job_runner."""

from __future__ import annotations

import unittest
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
