"""Tests for cooperative download cancellation."""
import os
import tempfile
import threading
import typing
import unittest
from unittest import mock

from core.downloads import DownloadManager


class _Response:
    def __init__(self, payload: bytes, length: int | None) -> None:
        self.payload = payload
        self.length = length
        self.offset = 0

    def getheader(self, name: str) -> str | None:
        if name == "Content-Length" and self.length is not None:
            return str(self.length)
        return None

    def read(self, size: int) -> bytes:
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class DownloadCancelTests(unittest.TestCase):
    def test_cancelled_download_does_not_rename_missing_part(self) -> None:
        manager = DownloadManager.__new__(DownloadManager)
        stop_event = threading.Event()
        stop_event.set()

        with tempfile.TemporaryDirectory() as tmp:
            save_path = os.path.join(tmp, "model.onnx")
            tmp_path = f"{save_path}.part"

            def fake_download_url(*_args: typing.Any, **_kwargs: typing.Any) -> None:
                with open(tmp_path, "wb") as handle:
                    handle.write(b"partial")
                os.remove(tmp_path)

            with mock.patch.object(manager, "_download_file_url", side_effect=fake_download_url):
                manager._download_file(
                    "https://example.com/model.onnx",
                    save_path,
                    None,
                    stop_event,
                )

            self.assertFalse(os.path.isfile(save_path))
            self.assertFalse(os.path.isfile(tmp_path))

    def test_truncated_known_length_is_rejected_and_partial_removed(self) -> None:
        manager = DownloadManager.__new__(DownloadManager)
        with tempfile.TemporaryDirectory() as tmp:
            part_path = os.path.join(tmp, "model.onnx.part")
            with mock.patch(
                "core.downloads._urlopen", return_value=_Response(b"short", 10)
            ):
                with self.assertRaises(OSError):
                    manager._download_file_url("https://example.com/model", part_path, None, None)
            self.assertFalse(os.path.exists(part_path))

    def test_unknown_length_download_is_allowed(self) -> None:
        manager = DownloadManager.__new__(DownloadManager)
        with tempfile.TemporaryDirectory() as tmp:
            part_path = os.path.join(tmp, "model.onnx.part")
            with mock.patch(
                "core.downloads._urlopen", return_value=_Response(b"payload", None)
            ):
                manager._download_file_url("https://example.com/model", part_path, None, None)
            with open(part_path, "rb") as handle:
                self.assertEqual(handle.read(), b"payload")

    def test_truncated_download_uses_hugging_face_fallback(self) -> None:
        manager = DownloadManager.__new__(DownloadManager)
        with tempfile.TemporaryDirectory() as tmp:
            save_path = os.path.join(tmp, "model.onnx")
            responses = [_Response(b"short", 10), _Response(b"complete", 8)]
            with mock.patch("core.downloads._urlopen", side_effect=responses), mock.patch(
                "core.downloads.hf_fallback_url", return_value="https://hf.example/model"
            ):
                manager._download_file("https://example.com/model", save_path, None, None)
            with open(save_path, "rb") as handle:
                self.assertEqual(handle.read(), b"complete")
            self.assertFalse(os.path.exists(f"{save_path}.part"))

    def test_cancelled_download_skips_hf_fallback(self) -> None:
        manager = DownloadManager.__new__(DownloadManager)
        stop_event = threading.Event()

        with tempfile.TemporaryDirectory() as tmp:
            save_path = os.path.join(tmp, "model.onnx")

            def fake_download_url(_url: typing.Any, tmp_path: typing.Any, *_args: typing.Any, **_kwargs: typing.Any) -> None:
                stop_event.set()
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            with mock.patch.object(manager, "_download_file_url", side_effect=fake_download_url):
                with mock.patch("core.downloads.hf_fallback_url", return_value="https://hf.example/x"):
                    manager._download_file(
                        "https://example.com/model.onnx",
                        save_path,
                        None,
                        stop_event,
                    )

            self.assertFalse(os.path.isfile(save_path))


if __name__ == "__main__":
    unittest.main()
