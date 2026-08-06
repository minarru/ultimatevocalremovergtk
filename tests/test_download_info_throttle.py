"""Tests for throttled download status text updates."""

import os
import tempfile
import unittest
from unittest import mock

from core.downloads import DownloadManager, _INFO_UPDATE_INTERVAL_S


class _FakeChunkResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def getheader(self, name: str) -> str | None:
        if name == "Content-Length":
            return str(len(self._data))
        return None

    def read(self, size: int) -> bytes:
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> "_FakeChunkResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class DownloadInfoThrottleTests(unittest.TestCase):
    def test_on_info_throttled_during_chunked_download(self) -> None:
        manager = DownloadManager.__new__(DownloadManager)
        chunk_size = 64 * 1024
        payload = b"x" * (chunk_size * 20)
        info_calls: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = os.path.join(tmp, "model.onnx.part")
            with mock.patch(
                "core.downloads._urlopen",
                return_value=_FakeChunkResponse(payload),
            ):
                with mock.patch("core.downloads.time.monotonic") as monotonic:
                    monotonic.side_effect = [index * _INFO_UPDATE_INTERVAL_S for index in range(200)]
                    manager._download_file_url(
                        "https://example.com/model.onnx",
                        tmp_path,
                        None,
                        None,
                        info_calls.append,
                    )

        self.assertGreater(len(info_calls), 1)
        self.assertLess(len(info_calls), 20)


if __name__ == "__main__":
    unittest.main()
