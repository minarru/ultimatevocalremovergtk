"""Tests for lazy separate-engine import warmup."""

import os
import unittest
from unittest import mock

from core.separate_import import skip_separate_warmup, warm_import_separate_engines


class SeparateImportWarmupTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("UVR_SKIP_SEPARATE_WARMUP", None)

    def test_skip_flag_default_false(self) -> None:
        os.environ.pop("UVR_SKIP_SEPARATE_WARMUP", None)
        self.assertFalse(skip_separate_warmup())

    def test_skip_flag_enabled(self) -> None:
        os.environ["UVR_SKIP_SEPARATE_WARMUP"] = "1"
        self.assertTrue(skip_separate_warmup())

    @mock.patch("core.separate_import.threading.Thread")
    def test_warm_import_respects_skip_flag(self, thread_cls: mock.MagicMock) -> None:
        os.environ["UVR_SKIP_SEPARATE_WARMUP"] = "1"
        warm_import_separate_engines()
        thread_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
