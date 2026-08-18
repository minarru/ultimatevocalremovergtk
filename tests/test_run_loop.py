"""Shared file/chunk loop."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

from core.run_loop import run_models_on_files


class _Hooks:
    process_kind = "separation"

    def __init__(self) -> None:
        self.before: list[str] = []
        self.states: list = []
        self.mix_present_at_after_file: list[bool] = []

    def before_file(self, runner, state) -> None:
        self.before.append(state.audio_file)

    def export_and_base(self, runner, state, model):
        return "base", "/tmp"

    def extra_process_data(self, runner, state, model) -> dict:
        return {"is_ensemble_master": False, "is_4_stem_ensemble": False}

    def after_chunk(self, runner, state, model, stems, paths, chunked) -> None:
        return

    def after_model(self, runner, state, model) -> None:
        return

    def after_file(self, runner, state) -> None:
        self.mix_present_at_after_file.append(state.decoded_mix is not None)
        self.states.append(state)


def _model(basename: str) -> SimpleNamespace:
    return SimpleNamespace(
        model_basename=basename,
        model_name=basename,
        process_method="MDX-Net",
        repo=None,
        mdx_segment_size=256,
    )


def _runner(*, true_model_count: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(
            process=SimpleNamespace(
                long_file_chunk_seconds=0.0,
                long_file_chunk_overlap_seconds=0.0,
            )
        ),
        true_model_count=true_model_count,
        iteration=0,
        _cached_sources_clear=lambda: None,
        _is_stopped=False,
        _is_paused=False,
        _process_iteration=lambda: None,
        _build_separator=MagicMock(),
        _cached_source_callback=lambda *a, **k: (None, None),
        _cached_model_source_holder=lambda *a, **k: None,
        all_models=[],
        _last_backend_name=None,
    )


def _callbacks() -> tuple[SimpleNamespace, list[str]]:
    console: list[str] = []
    return SimpleNamespace(console=console.append, progress=lambda *a, **k: None), console


class RunLoopMissingFileTests(unittest.TestCase):
    @patch("core.run_loop._decoded_mix_for_process")
    @patch("core.run_loop.run_separator")
    def test_skips_missing_input(self, run_sep: MagicMock, decode: MagicMock) -> None:
        hooks = _Hooks()
        callbacks, console = _callbacks()
        runner = _runner()
        missing = os.path.join(tempfile.gettempdir(), "uvr-missing-no-such-file.wav")
        self.assertFalse(os.path.isfile(missing))
        engines = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        run_models_on_files(
            runner,
            [missing],
            callbacks,
            [_model("m")],
            engines=engines,
            hooks=hooks,
        )
        self.assertEqual(hooks.before, [])
        run_sep.assert_not_called()
        decode.assert_not_called()
        self.assertTrue(any("was not found" in line for line in console))
        self.assertEqual(runner.iteration, 1)


class RunLoopLazyDecodeTests(unittest.TestCase):
    @patch("core.run_loop.snapshot_worker_file")
    @patch("core.run_loop.run_separator", return_value={})
    @patch("core.run_loop._decoded_mix_for_process")
    def test_decodes_once_per_file_not_per_model(
        self, decode: MagicMock, run_sep: MagicMock, _snapshot: MagicMock
    ) -> None:
        mix = np.zeros((2, 8), dtype=np.float32)
        events: list[str] = []

        def _decode(path: str):
            events.append(f"decode:{os.path.basename(path)}")
            return mix

        def _run_sep(*_a, **_k):
            events.append("run_separator")
            return {}

        decode.side_effect = _decode
        run_sep.side_effect = _run_sep

        hooks = _Hooks()
        callbacks, _console = _callbacks()
        runner = _runner(true_model_count=2)
        engines = (MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
        with tempfile.TemporaryDirectory() as tmp:
            path_a = os.path.join(tmp, "a.wav")
            path_b = os.path.join(tmp, "b.wav")
            for path in (path_a, path_b):
                with open(path, "wb") as handle:
                    handle.write(b"")
            run_models_on_files(
                runner,
                [path_a, path_b],
                callbacks,
                [
                    _model("m1"),
                    _model("m2"),
                ],
                engines=engines,
                hooks=hooks,
            )

        self.assertEqual(decode.call_count, 2)
        self.assertEqual(
            events,
            [
                "decode:a.wav",
                "run_separator",
                "run_separator",
                "decode:b.wav",
                "run_separator",
                "run_separator",
            ],
        )
        self.assertEqual(hooks.mix_present_at_after_file, [True, True])
        self.assertTrue(all(state.decoded_mix is None for state in hooks.states))
        self.assertTrue(all(state.chunks == [] for state in hooks.states))


if __name__ == "__main__":
    unittest.main()

