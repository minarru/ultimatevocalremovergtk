from __future__ import annotations

import unittest
import dataclasses
import tempfile
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from core.export_naming import OutputNamingContext
from core.job_plan import PlannedInput, PlannedOutput, ResolvedJob, ValidationLevel
from core.job_callbacks import JobCallbacks
from core.job_runner import InputOutcome, JobRunner
from core.settings import Settings


def _job(paths: tuple[str, ...], output: str) -> ResolvedJob:
    settings = Settings.defaults()
    settings.process.export_path = output
    inputs = tuple(
        PlannedInput(
            path,
            OutputNamingContext(
                input_path=path,
                track="song",
                track_base="song",
                export_directory=output,
                extension="wav",
                file_index=1,
                file_total=len(paths),
            ),
            (PlannedOutput(f"{output}/song (Vocals).wav", "Vocals", False),),
        )
        for path in paths
    )
    return ResolvedJob(
        "separate", settings, inputs, (), {}, (),
        ValidationLevel.MODEL, 0, "fp", "cpu", output,
    )


class StartResolvedTests(unittest.TestCase):
    def test_worker_lifecycle_keeps_explicit_operation_id(self) -> None:
        from core import debug_log

        runner = JobRunner(Settings.defaults())
        job = _job(("/tmp/a.wav",), "/tmp/out")
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))
            self.addCleanup(debug_log.configure, level="errors", log_file="")
            with patch.object(runner, "resolve_models", return_value=["M"]), patch.object(
                runner,
                "_run_one_planned",
                return_value=InputOutcome("/tmp/a.wav", "success"),
            ):
                runner.start_resolved(
                    job,
                    JobCallbacks(),
                    fail_fast=True,
                    operation_id="job-42",
                )
                thread = runner._thread
                if thread is not None:
                    thread.join(timeout=2)

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertIn("event=worker_started", diagnostic)
            self.assertIn("event=worker_completed", diagnostic)
            self.assertGreaterEqual(diagnostic.count("operation=job-42"), 2)

    def test_worker_inherits_ui_operation_context_when_id_is_omitted(self) -> None:
        from core import debug_log

        runner = JobRunner(Settings.defaults())
        job = _job(("/tmp/a.wav",), "/tmp/out")
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))
            self.addCleanup(debug_log.configure, level="errors", log_file="")
            with patch.object(runner, "resolve_models", return_value=["M"]), patch.object(
                runner,
                "_run_one_planned",
                return_value=InputOutcome("/tmp/a.wav", "success"),
            ), debug_log.operation("ui-run-8"):
                runner.start_resolved(job, JobCallbacks(), fail_fast=True)
                thread = runner._thread
                if thread is not None:
                    thread.join(timeout=2)

            diagnostic = log_path.read_text(encoding="utf-8")
            started_line = next(
                line
                for line in diagnostic.splitlines()
                if "event=worker_started" in line
            )
            self.assertIn("operation=ui-run-8", started_line)

    def test_assembles_once_for_two_inputs(self) -> None:
        runner = JobRunner(Settings.defaults())
        job = _job(("/tmp/a.wav", "/tmp/b.wav"), "/tmp/out")
        dependencies = {"mdx.model": Mock(id="mdx:primary")}
        job = dataclasses.replace(job, model_dependencies=dependencies)
        with patch.object(runner, "resolve_models", return_value=["M"]) as resolve:
            with patch.object(runner, "_run_one_planned", return_value=InputOutcome("/tmp/a.wav", "success")):
                # If you name the per-item helper differently, patch that name.
                runner.start_resolved(job, JobCallbacks(), models=None, fail_fast=True)
                thread = runner._thread
                if thread is not None and thread.is_alive():
                    thread.join(timeout=2)
        resolve.assert_called_once_with(dependencies)

    def test_fail_fast_stops_after_first_error(self) -> None:
        runner = JobRunner(Settings.defaults())
        job = _job(("/tmp/a.wav", "/tmp/b.wav"), "/tmp/out")
        seen: list[str] = []

        def one(planned: PlannedInput, _callbacks: JobCallbacks) -> InputOutcome:
            seen.append(planned.path)
            return InputOutcome(planned.path, "failed", error="boom")

        with patch.object(runner, "resolve_models", return_value=["M"]):
            with patch.object(runner, "_run_one_planned", side_effect=one):
                runner.start_resolved(job, JobCallbacks(), fail_fast=True)
                thread = getattr(runner, "_thread", None)
                if thread is not None:
                    thread.join(timeout=2)
        self.assertEqual(seen, ["/tmp/a.wav"])

    def test_continue_on_error_runs_second_input(self) -> None:
        runner = JobRunner(Settings.defaults())
        job = _job(("/tmp/a.wav", "/tmp/b.wav"), "/tmp/out")
        seen: list[str] = []

        def one(planned: PlannedInput, _callbacks: JobCallbacks) -> InputOutcome:
            seen.append(planned.path)
            status = "failed" if planned.path.endswith("a.wav") else "success"
            return InputOutcome(planned.path, status, error="boom" if status == "failed" else None)

        with patch.object(runner, "resolve_models", return_value=["M"]):
            with patch.object(runner, "_run_one_planned", side_effect=one):
                runner.start_resolved(job, JobCallbacks(), fail_fast=False)
                thread = getattr(runner, "_thread", None)
                if thread is not None:
                    thread.join(timeout=2)
        self.assertEqual(seen, ["/tmp/a.wav", "/tmp/b.wav"])
