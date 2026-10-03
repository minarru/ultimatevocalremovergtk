"""Core reports each finished input's source, reference and written outputs."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from core.export_naming import OutputNamingContext
from core.job_callbacks import JobCallbacks
from core.job_plan import PlannedInput, PlannedOutput
from core.job_runner import JobRunner
from core.run_loop import run_models_on_files
from core.settings import Settings
from tests.test_run_loop import _Hooks, _model, _runner


def _planned(path: str, out_dir: str, *stems: str) -> PlannedInput:
    return PlannedInput(
        path=path,
        naming=OutputNamingContext(
            input_path=path,
            track="song",
            track_base="song",
            export_directory=out_dir,
            extension="wav",
        ),
        outputs=tuple(
            PlannedOutput(os.path.join(out_dir, f"song ({stem}).wav"), stem) for stem in stems
        ),
    )


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, paths: Any, generated: Any, error: Any, reference: Any) -> None:
        self.calls.append((paths, generated, error, reference))


class InputFinishedCallbackTests(unittest.TestCase):
    def test_reference_is_forwarded_positionally(self) -> None:
        rec = _Recorder()
        JobCallbacks(on_input_finished=rec).input_finished(
            ("/in/a.wav",), ("/out/a (Vocals).wav",), None, reference="/tmp/clip.wav"
        )
        self.assertEqual(
            rec.calls, [(("/in/a.wav",), ("/out/a (Vocals).wav",), None, "/tmp/clip.wav")]
        )

    def test_reference_defaults_to_none(self) -> None:
        rec = _Recorder()
        JobCallbacks(on_input_finished=rec).input_finished(("/in/a.wav",))
        self.assertEqual(rec.calls, [(("/in/a.wav",), (), None, None)])


class FinishedInputReportTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.src = os.path.join(self.dir, "song.wav")
        self.runner = JobRunner(Settings.defaults())

    def _touch(self, path: str) -> None:
        with open(path, "wb") as handle:
            handle.write(b"x")

    def test_reports_existing_outputs_in_plan_order(self) -> None:
        planned = _planned(self.src, self.dir, "Vocals", "Instrumental", "Other")
        self._touch(planned.outputs[1].path)
        self._touch(planned.outputs[0].path)
        self.runner._run_planned = (planned,)

        source, reference, outputs = self.runner.finished_input_report(self.src)

        self.assertEqual(source, self.src)
        self.assertEqual(reference, os.path.abspath(self.src))
        self.assertEqual(outputs, (planned.outputs[0].path, planned.outputs[1].path))

    def test_sample_mode_maps_clip_back_to_source(self) -> None:
        planned = _planned(self.src, self.dir, "Vocals")
        self._touch(planned.outputs[0].path)
        clip = os.path.join(self.dir, "clip.wav")
        self.runner._run_planned = (planned,)
        self.runner._run_path_map = {os.path.abspath(clip): os.path.abspath(self.src)}

        source, reference, outputs = self.runner.finished_input_report(clip)

        self.assertEqual(source, self.src)
        self.assertEqual(reference, os.path.abspath(clip))
        self.assertEqual(outputs, (planned.outputs[0].path,))

    def test_unplanned_run_reports_no_outputs(self) -> None:
        source, reference, outputs = self.runner.finished_input_report(self.src)
        self.assertEqual((source, reference, outputs), (os.path.abspath(self.src),) * 2 + ((),))


class RunLoopEmitsInputFinishedTests(unittest.TestCase):
    @patch("core.run_loop.snapshot_worker_file")
    @patch("core.run_loop._decoded_mix_for_process")
    @patch("core.run_loop.run_separator")
    def test_emits_once_per_input_after_after_file(
        self, _run_sep: Any, decode: Any, _snapshot: Any
    ) -> None:
        import numpy as np

        decode.return_value = np.zeros((2, 4410), dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "song.wav")
            with open(path, "wb") as handle:
                handle.write(b"x")
            runner = _runner()
            runner.finished_input_report = lambda f: (f, f + ".ref", (f + ".out",))
            rec = _Recorder()
            order: list[str] = []
            hooks = _Hooks()
            original_after = hooks.after_file

            def after_file(r: Any, state: Any) -> None:
                order.append("after_file")
                original_after(r, state)

            hooks.after_file = after_file  # type: ignore[method-assign]

            def recorder(*args: Any) -> None:
                order.append("input_finished")
                rec(*args)

            callbacks = JobCallbacks(on_input_finished=recorder)
            run_models_on_files(runner, [path], callbacks, [_model("m")], hooks=hooks)

        self.assertEqual(order, ["after_file", "input_finished"])
        self.assertEqual(rec.calls, [((path,), (path + ".out",), None, path + ".ref")])

    @patch("core.run_loop.run_separator")
    def test_missing_input_reports_no_outputs(self, _run_sep: Any) -> None:
        missing = os.path.join(tempfile.gettempdir(), "uvr-missing-output-report.wav")
        rec = _Recorder()
        run_models_on_files(
            _runner(),
            [missing],
            JobCallbacks(on_input_finished=rec),
            [_model("m")],
            hooks=_Hooks(),
        )
        self.assertEqual(rec.calls, [((missing,), (), None, None)])

    @patch("core.run_loop.snapshot_worker_file")
    @patch("core.run_loop._decoded_mix_for_process")
    @patch("core.run_loop.run_separator")
    def test_runner_without_report_hook_still_runs(
        self, _run_sep: Any, decode: Any, _snapshot: Any
    ) -> None:
        import numpy as np

        decode.return_value = np.zeros((2, 4410), dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "song.wav")
            with open(path, "wb") as handle:
                handle.write(b"x")
            rec = _Recorder()
            run_models_on_files(
                _runner(),
                [path],
                JobCallbacks(on_input_finished=rec),
                [_model("m")],
                hooks=_Hooks(),
            )
        self.assertEqual(rec.calls, [])


if __name__ == "__main__":
    unittest.main()
