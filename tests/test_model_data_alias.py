"""Canonical homes: ModelConfig is not aliased; process_determine_* left model_data."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


class ModelConfigAliasGoneTests(unittest.TestCase):
    def test_model_data_source_does_not_define_the_alias(self) -> None:
        source = (_REPO / "core" / "model_data.py").read_text(encoding="utf-8")
        self.assertNotIn("_ModelConfigImplementation", source)

    def test_model_data_module_has_no_alias_attribute(self) -> None:
        import core.model_data as model_data

        self.assertFalse(hasattr(model_data, "_ModelConfigImplementation"))


class ProcessDetermineHomeTests(unittest.TestCase):
    _NAMES = (
        "process_determine_secondary_model",
        "process_determine_demucs_pre_proc_model",
        "process_determine_vocal_split_model",
    )

    def test_model_data_source_does_not_define_process_determine(self) -> None:
        source = (_REPO / "core" / "model_data.py").read_text(encoding="utf-8")
        for name in self._NAMES:
            with self.subTest(name=name):
                self.assertNotIn(name, source)

    def test_model_data_module_has_no_process_determine(self) -> None:
        import core.model_data as model_data

        for name in self._NAMES:
            with self.subTest(name=name):
                self.assertFalse(hasattr(model_data, name))

    def test_model_config_exports_process_determine(self) -> None:
        import core.model_config as model_config

        for name in self._NAMES:
            with self.subTest(name=name):
                self.assertTrue(hasattr(model_config, name))
