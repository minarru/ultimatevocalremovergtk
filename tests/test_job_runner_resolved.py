from __future__ import annotations

import unittest
from unittest.mock import patch

from core.export_naming import OutputNamingContext
from core.job_plan import PlannedInput, PlannedOutput, ResolvedJob, ValidationLevel
from core.job_runner import InputOutcome, JobCallbacks, JobRunner
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
    def test_assembles_once_for_two_inputs(self) -> None:
        runner = JobRunner(Settings.defaults())
        job = _job(("/tmp/a.wav", "/tmp/b.wav"), "/tmp/out")
        with patch.object(runner, "resolve_models", return_value=["M"]) as resolve:
            with patch.object(runner, "_run_one_planned", return_value=InputOutcome("/tmp/a.wav", "success")):
                # If you name the per-item helper differently, patch that name.
                runner.start_resolved(job, JobCallbacks(), models=None, fail_fast=True)
                thread = runner._thread
                if thread is not None and thread.is_alive():
                    thread.join(timeout=2)
        resolve.assert_called_once()

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
