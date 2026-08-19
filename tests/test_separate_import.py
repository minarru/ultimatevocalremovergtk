"""Tests for lazy separate-engine import warmup."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import get_type_hints
from unittest import mock

import core.separate_import as separate_import
from core.separate_import import (
    engines_imported,
    import_separate_engines,
    skip_separate_warmup,
    warm_import_separate_engines,
    warm_status,
)

_REPO = Path(__file__).resolve().parents[1]


def _reset_warmup_state() -> None:
    with separate_import._lock:
        separate_import._warm_thread = None
        separate_import._imported = False


class SeparateImportWarmupTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_warmup_state()

    def tearDown(self) -> None:
        os.environ.pop("UVR_SKIP_SEPARATE_WARMUP", None)
        _reset_warmup_state()

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

    @mock.patch("core.separate_import.threading.Thread")
    def test_warm_import_starts_daemon_thread_when_not_skipped(
        self, thread_cls: mock.MagicMock
    ) -> None:
        os.environ.pop("UVR_SKIP_SEPARATE_WARMUP", None)
        thread = mock.MagicMock()
        thread_cls.return_value = thread
        warm_import_separate_engines()
        thread_cls.assert_called_once()
        self.assertEqual(thread_cls.call_args.kwargs["name"], "uvr-separate-warm")
        self.assertTrue(thread_cls.call_args.kwargs["daemon"])
        thread.start.assert_called_once()

    @mock.patch("core.separate_import.threading.Thread")
    def test_warm_import_is_idempotent(self, thread_cls: mock.MagicMock) -> None:
        os.environ.pop("UVR_SKIP_SEPARATE_WARMUP", None)
        thread = mock.MagicMock()
        thread_cls.return_value = thread
        warm_import_separate_engines()
        warm_import_separate_engines()
        thread_cls.assert_called_once()

    def test_import_separate_engines_returns_none(self) -> None:
        hints = get_type_hints(import_separate_engines)
        self.assertIs(hints.get("return"), type(None))

    def test_warmup_source_uses_factory_preload(self) -> None:
        source = (_REPO / "core" / "separate_import.py").read_text(encoding="utf-8")
        self.assertIn("preload_engine_modules", source)
        self.assertNotIn("engines.separate", source)

    def test_import_separate_engines_preloads_once(self) -> None:
        import engines.separator_factory as factory

        self.assertTrue(callable(getattr(factory, "preload_engine_modules", None)))
        with mock.patch.object(factory, "preload_engine_modules") as preload:
            self.assertFalse(engines_imported())
            self.assertIsNone(import_separate_engines())
            self.assertIsNone(import_separate_engines())
            self.assertEqual(preload.call_count, 1)
            self.assertTrue(engines_imported())
            self.assertEqual(warm_status(), "done")

    def test_engines_imported_false_until_import_completes(self) -> None:
        import engines.separator_factory as factory

        self.assertTrue(callable(getattr(factory, "preload_engine_modules", None)))

        def _preload() -> None:
            self.assertFalse(engines_imported())

        with mock.patch.object(factory, "preload_engine_modules", side_effect=_preload):
            self.assertFalse(engines_imported())
            self.assertEqual(warm_status(), "not_started")
            import_separate_engines()
            self.assertTrue(engines_imported())

    def test_warm_status_in_progress_while_thread_alive(self) -> None:
        thread = mock.MagicMock()
        thread.is_alive.return_value = True
        with separate_import._lock:
            separate_import._warm_thread = thread
        self.assertEqual(warm_status(), "in_progress")

    def test_application_activate_calls_warmup(self) -> None:
        source = (_REPO / "ui" / "application.py").read_text(encoding="utf-8")
        self.assertIn("warm_import_separate_engines", source)


if __name__ == "__main__":
    unittest.main()
