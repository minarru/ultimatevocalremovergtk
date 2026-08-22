"""Source-level checks for engine/orchestration identity consumers."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


class EngineIdentityConsumerTests(unittest.TestCase):
    def test_demucs_layout_validation_precedes_preproc_vocal_graft(self) -> None:
        source = (_REPO / "engines" / "demucs_engine.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("validate_demucs_inference_layouts(", source)
        self.assertIn("inst_source[self.demucs_source_map[VOCAL_STEM]]", source)
        self.assertLess(
            source.index("validate_demucs_inference_layouts("),
            source.index("inst_source[self.demucs_source_map[VOCAL_STEM]]"),
        )

    def test_secondary_model_trace_prefers_carried_display_label(self) -> None:
        source = (_REPO / "engines" / "orchestration.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('getattr(secondary_model, "model_display_label", None)', source)
        self.assertNotIn("model=secondary_model.model_basename", source)


if __name__ == "__main__":
    unittest.main()
