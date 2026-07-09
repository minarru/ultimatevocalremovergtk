"""Tests for cooperative download cancellation."""

import os
import tempfile
import threading
import unittest
from unittest import mock

from core.downloads import DownloadManager


class DownloadCancelTests(unittest.TestCase):
    def test_cancelled_download_does_not_rename_missing_part(self) -> None:
        manager = DownloadManager.__new__(DownloadManager)
        stop_event = threading.Event()
        stop_event.set()

        with tempfile.TemporaryDirectory() as tmp:
            save_path = os.path.join(tmp, "model.onnx")
            tmp_path = f"{save_path}.part"

            def fake_download_url(*_args, **_kwargs) -> None:
                with open(tmp_path, "wb") as handle:
                    handle.write(b"partial")
                os.remove(tmp_path)

            with mock.patch.object(manager, "_download_file_url", side_effect=fake_download_url):
                manager._download_file(
                    "https://example.com/model.onnx",
                    save_path,
                    0,
                    1,
                    None,
                    stop_event,
                )

            self.assertFalse(os.path.isfile(save_path))
            self.assertFalse(os.path.isfile(tmp_path))

    def test_cancelled_download_skips_hf_fallback(self) -> None:
        manager = DownloadManager.__new__(DownloadManager)
        stop_event = threading.Event()

        with tempfile.TemporaryDirectory() as tmp:
            save_path = os.path.join(tmp, "model.onnx")

            def fake_download_url(_url, tmp_path, *_args, **_kwargs) -> None:
                stop_event.set()
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            with mock.patch.object(manager, "_download_file_url", side_effect=fake_download_url):
                with mock.patch("core.downloads.hf_fallback_url", return_value="https://hf.example/x"):
                    manager._download_file(
                        "https://example.com/model.onnx",
                        save_path,
                        0,
                        1,
                        None,
                        stop_event,
                    )

            self.assertFalse(os.path.isfile(save_path))


if __name__ == "__main__":
    unittest.main()
