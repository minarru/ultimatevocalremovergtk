"""JobRunner separator lifecycle."""
import typing

import unittest
from unittest import mock
from types import SimpleNamespace

from core.job_runner import JobRunner
from core.separator_run import run_separator
from core.settings import Settings


class JobRunnerSeperatorTests(unittest.TestCase):
    @mock.patch("engines.stem_writer.finish_export")
    @mock.patch("core.separator_run.release_separator")
    def test_run_seperator_releases_in_finally(
        self, release_mock: mock.MagicMock, finish_mock: mock.MagicMock
    ) -> None:
        from engines.stem_writer import ExportPlan

        runner = JobRunner(Settings.defaults())
        separator = mock.MagicMock()
        plan = ExportPlan()
        separator.seperate.return_value = plan
        finish_mock.return_value = {}
        run_separator(runner, separator)
        separator.seperate.assert_called_once_with()
        finish_mock.assert_called_once_with(separator, plan)
        release_mock.assert_called_once_with(separator)
        self.assertIsNone(runner._active_separator)

    @mock.patch("core.separator_run.release_separator")
    def test_run_seperator_releases_after_exception(self, release_mock: mock.MagicMock) -> None:
        runner = JobRunner(Settings.defaults())
        separator = mock.MagicMock()
        separator.seperate.side_effect = ValueError("fail")
        with self.assertRaises(ValueError):
            run_separator(runner, separator)
        release_mock.assert_called_once_with(separator)
        self.assertIsNone(runner._active_separator)

    def test_cached_source_callback_uses_exact_basename(self) -> None:
        runner = JobRunner(Settings.defaults())
        runner._mdx_cache_source_mapper = {
            "model_a": {"Vocals": [1]},
            "model_ab": {"Vocals": [2]},
        }
        model_name, sources = runner._cached_source_callback("MDX-Net", "model_a")
        self.assertEqual(model_name, "model_a")
        self.assertEqual(sources, {"Vocals": [1]})

    def test_cached_source_callback_miss_returns_none(self) -> None:
        runner = JobRunner(Settings.defaults())
        runner._mdx_cache_source_mapper = {"model_a": {"Vocals": [1]}}
        model_name, sources = runner._cached_source_callback("MDX-Net", "other")
        self.assertIsNone(model_name)
        self.assertIsNone(sources)

    def test_build_all_models_uses_backend_names_for_cache_identity(self) -> None:
        from bundled.constants import DEMUCS_ARCH_TYPE

        runner = JobRunner(Settings.defaults())
        model = typing.cast(
            typing.Any,
            SimpleNamespace(
                model_basename="shared",
                backend_name="shared.onnx",
                is_secondary_model_activated=True,
                secondary_model=SimpleNamespace(
                    model_basename="shared",
                    backend_name="shared_secondary.ckpt",
                ),
                pre_proc_model=SimpleNamespace(
                    model_basename="shared",
                    backend_name="shared_pre_proc.yaml",
                ),
                process_method=DEMUCS_ARCH_TYPE,
                is_demucs_4_stem_secondaries=True,
                secondary_model_4_stem_model_names_list=["slot_a.onnx", "slot_b.onnx"],
            ),
        )

        runner._build_all_models([model])

        self.assertEqual(
            runner.all_models,
            [
                "shared.onnx",
                "shared_secondary.ckpt",
                "shared_pre_proc.yaml",
                "slot_a.onnx",
                "slot_b.onnx",
            ],
        )

    def test_start_does_not_prepare_on_caller_thread(self) -> None:
        """``prepare_input_paths`` must not run before the worker starts."""
        from core.job_callbacks import JobCallbacks

        runner = JobRunner(Settings.from_flat({"model_sample_mode": False}))
        prepare = mock.Mock(side_effect=lambda settings, paths, **kwargs: list(paths))
        created: list = []

        class _DeferredThread:
            def __init__(self, target: typing.Any=None, args: typing.Any=()):
                self._target = target
                self._args = args
                created.append(self)

            def start(self):
                # Intentionally deferred — caller must not have prepared yet.
                pass

            def is_alive(self):
                return False

            def run_now(self):
                assert self._target is not None
                self._target(*self._args)

        with mock.patch.dict("sys.modules", {"kthread": mock.Mock(KThread=_DeferredThread)}):
            with mock.patch("core.job_runner.prepare_input_paths", prepare):
                with mock.patch.object(
                    runner,
                    "_run_separation",
                    side_effect=lambda paths, callbacks, mode: runner._prepare_paths_for_run(
                        paths, callbacks
                    ),
                ):
                    runner.start(["/tmp/a.wav"], JobCallbacks())
                    prepare.assert_not_called()
                    self.assertEqual(len(created), 1)
                    created[0].run_now()
                    prepare.assert_called_once()


if __name__ == "__main__":
    unittest.main()
