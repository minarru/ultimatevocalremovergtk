"""Tests for download size formatting and job estimates."""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from core.download_sizes import (
    _CACHE_TTL_SECONDS,
    describe_download_size,
    format_download_size,
    prefetch_remote_sizes,
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
                self.assertEqual(describe_download_size(jobs), "Size unknown")

    def test_multi_file_shows_aggregate_size_only(self) -> None:
        with patch("core.download_sizes.fetch_remote_size", return_value=50 * 1024 * 1024):
            with tempfile.TemporaryDirectory() as tmp:
                jobs = [
                    ("https://example.com/a.ckpt", os.path.join(tmp, "a.ckpt")),
                    ("https://example.com/b.yaml", os.path.join(tmp, "b.yaml")),
                ]
                self.assertEqual(describe_download_size(jobs), "100 MB")


class PrefetchRemoteSizesTests(unittest.TestCase):
    def test_skips_fresh_cache_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            url = "https://example.com/model.onnx"
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump({url: {"size": 1024, "fetched_at": time.time()}}, handle)
            with patch("core.download_sizes._CACHE_PATH", cache_path):
                with patch("core.download_sizes._head_content_length") as head:
                    stats = prefetch_remote_sizes([url])
            self.assertEqual(stats, {"total": 1, "fresh": 1, "fetched": 0, "failed": 0})
            head.assert_not_called()

    def test_refetches_expired_cache_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "download_size_cache.json")
            url = "https://example.com/model.onnx"
            stale_at = time.time() - _CACHE_TTL_SECONDS - 60
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump({url: {"size": 1024, "fetched_at": stale_at}}, handle)
            with patch("core.download_sizes._CACHE_PATH", cache_path):
                with patch(
                    "core.download_sizes._head_content_length",
                    return_value=2048,
                ) as head:
                    stats = prefetch_remote_sizes([url])
            self.assertEqual(stats, {"total": 1, "fresh": 0, "fetched": 1, "failed": 0})
            head.assert_called_once_with(url)
            with open(cache_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload[url]["size"], 2048)


if __name__ == "__main__":
    unittest.main()
