"""Tests for separator teardown helpers."""

import unittest
from unittest import mock

from pathlib import Path

from core.inference_cleanup import release_inference_memory, release_separator

_REPO = Path(__file__).resolve().parents[1]


class _FakeSeparator:
    def __init__(self) -> None:
        self.demucs = object()
        self.model_run = object()
        self._inference_model = object()
        self._ort_session = mock.MagicMock()
        self.primary_sources = {"Vocals": [1, 2, 3]}
        self.primary_source_map = {"Vocals": [1]}
        self.mix = [0, 1]


class ReleaseSeparatorTests(unittest.TestCase):
    def test_release_separator_clears_model_handles(self) -> None:
        separator = _FakeSeparator()
        ort_session = separator._ort_session
        release_separator(separator)
        self.assertIsNone(separator.demucs)
        self.assertIsNone(separator.model_run)
        self.assertIsNone(separator._inference_model)
        self.assertIsNone(separator._ort_session)
        ort_session.close.assert_called_once()
        self.assertIsNone(separator.primary_sources)
        self.assertEqual(separator.primary_source_map, {})

    def test_release_separator_accepts_none(self) -> None:
        release_separator(None)


class ReleaseInferenceMemoryTests(unittest.TestCase):
    def test_inference_cleanup_source_imports_gpu_cache(self) -> None:
        source = (_REPO / "core" / "inference_cleanup.py").read_text(encoding="utf-8")
        self.assertNotIn("engines.separate", source)
        self.assertIn("from engines.gpu_cache import clear_gpu_cache", source)

    @mock.patch("engines.gpu_cache.clear_gpu_cache")
    @mock.patch("engines.model_weight_cache.get_weight_cache")
    def test_release_inference_memory_calls_gpu_cache_clear(
        self, get_cache: mock.MagicMock, clear: mock.MagicMock
    ) -> None:
        cache = mock.MagicMock()
        get_cache.return_value = cache
        release_inference_memory(None)
        clear.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
