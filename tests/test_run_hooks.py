"""File-pass hooks live in core.run_hooks, not job_runner."""

from __future__ import annotations

import typing
import unittest
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[1]


class RunHooksHomeTests(unittest.TestCase):
    def test_job_runner_source_does_not_define_hook_classes(self) -> None:
        source = (_REPO / "core" / "job_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("class _SingleRunHooks", source)
        self.assertNotIn("class _EnsembleRunHooks", source)

    def test_hook_classes_importable_from_own_module(self) -> None:
        from core.run_hooks import _EnsembleRunHooks, _SingleRunHooks

        self.assertTrue(callable(_SingleRunHooks))
        self.assertTrue(callable(_EnsembleRunHooks))

    def test_job_runner_module_has_no_hook_attributes(self) -> None:
        import core.job_runner as job_runner

        self.assertFalse(hasattr(job_runner, "_SingleRunHooks"))
        self.assertFalse(hasattr(job_runner, "_EnsembleRunHooks"))
        self.assertFalse(hasattr(job_runner, "_model_output_label"))

    def test_model_output_label_prefers_carried_display_label(self) -> None:
        from core.run_hooks import _model_output_label

        model = typing.cast(
            typing.Any,
            SimpleNamespace(
                model_display_label="Friendly Demucs",
                model_name="demucs:raw-id",
                model_basename="raw-id",
                process_method="Demucs",
                repo=None,
            ),
        )

        self.assertEqual(_model_output_label(model), "Friendly Demucs")
