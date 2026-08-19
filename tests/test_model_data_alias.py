"""_ModelConfigImplementation is gone; ModelConfig is not aliased under the old name."""

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
