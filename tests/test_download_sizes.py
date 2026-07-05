"""Tests for download size formatting and job estimates."""

import os
import tempfile
import unittest
from unittest.mock import patch

from core.download_sizes import (
    describe_download_size,
    format_download_size,
)


class FormatDownloadSizeTests(unittest.TestCase):
    def test_bytes(self) -> None:
        self.assertEqual(format_download_size(512), "512 B")

    def test_megabytes(self) -> None:
        self.assertEqual(format_download_size(245 * 1024 * 1024), "245 MB")

    def test_gigabytes(self) -> None:
        self.assertEqual(format_download_size(int(1.2 * 1024**3)), "1.2 GB")

    def test_unknown(self) -> None:
        self.assertEqual(format_download_size(None), "unknown")


class DescribeDownloadSizeTests(unittest.TestCase):
    def test_single_known_file(self) -> None:
        with patch("core.download_sizes.fetch_remote_size", return_value=100 * 1024 * 1024):
            with tempfile.TemporaryDirectory() as tmp:
                jobs = [("https://example.com/model.onnx", os.path.join(tmp, "model.onnx"))]
                self.assertEqual(describe_download_size(jobs), "100 MB")

    def test_already_downloaded(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            jobs = [("https://example.com/model.onnx", path)]
            self.assertEqual(describe_download_size(jobs), "Already downloaded")
        finally:
            os.remove(path)

    def test_unknown_sizes(self) -> None:
        with patch("core.download_sizes.fetch_remote_size", return_value=None):
            with tempfile.TemporaryDirectory() as tmp:
                jobs = [("https://example.com/a.onnx", os.path.join(tmp, "a.onnx"))]
                self.assertEqual(describe_download_size(jobs), "Size unknown · 1 file")


if __name__ == "__main__":
    unittest.main()
