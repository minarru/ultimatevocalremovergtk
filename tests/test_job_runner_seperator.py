"""JobRunner separator lifecycle."""

import unittest
from unittest import mock

from core.job_runner import JobRunner
from core.settings import SettingsModel


class JobRunnerSeperatorTests(unittest.TestCase):
    @mock.patch("core.job_runner.release_separator")
    def test_run_seperator_releases_in_finally(self, release_mock: mock.MagicMock) -> None:
        runner = JobRunner(SettingsModel())
        separator = mock.MagicMock()
        runner._run_seperator(separator)
        separator.seperate.assert_called_once_with()
        release_mock.assert_called_once_with(separator)
        self.assertIsNone(runner._active_separator)

    @mock.patch("core.job_runner.release_separator")
    def test_run_seperator_releases_after_exception(self, release_mock: mock.MagicMock) -> None:
        runner = JobRunner(SettingsModel())
        separator = mock.MagicMock()
        separator.seperate.side_effect = ValueError("fail")
        with self.assertRaises(ValueError):
            runner._run_seperator(separator)
        release_mock.assert_called_once_with(separator)
        self.assertIsNone(runner._active_separator)

    def test_cached_source_callback_uses_exact_basename(self) -> None:
        runner = JobRunner(SettingsModel())
        runner._mdx_cache_source_mapper = {
            "model_a": {"Vocals": [1]},
            "model_ab": {"Vocals": [2]},
        }
        model_name, sources = runner._cached_source_callback("MDX-Net", "model_a")
        self.assertEqual(model_name, "model_a")
        self.assertEqual(sources, {"Vocals": [1]})

    def test_cached_source_callback_miss_returns_none(self) -> None:
        runner = JobRunner(SettingsModel())
        runner._mdx_cache_source_mapper = {"model_a": {"Vocals": [1]}}
        model_name, sources = runner._cached_source_callback("MDX-Net", "other")
        self.assertIsNone(model_name)
        self.assertIsNone(sources)


if __name__ == "__main__":
    unittest.main()
