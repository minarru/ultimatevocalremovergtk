"""Tests for separator teardown helpers."""

import unittest
from unittest import mock

from core.inference_cleanup import release_separator


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


if __name__ == "__main__":
    unittest.main()
