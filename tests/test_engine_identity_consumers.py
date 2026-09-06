"""Source-level checks for engine/orchestration identity consumers."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


class EngineIdentityConsumerTests(unittest.TestCase):
    def test_demucs_layout_validation_precedes_preproc_vocal_graft(self) -> None:
        from unittest.mock import patch

        import numpy as np

        from bundled.constants import INST_STEM
        from engines.demucs_engine import SeperateDemucs
        from engines.demucs_runtime import infer_demucs_native
        from tests.test_model_option_parity import partial_model
        from tests.test_stem_writer import _copy_engine_attributes

        model = partial_model()
        model.pre_proc_model = object()
        model.primary_stem = "Bass"
        model.demucs_stem_count = 4
        engine = SeperateDemucs(model, _copy_engine_attributes(model).process_data)
        original = np.ones((4, 2, 8))
        preprocessed = np.zeros((2, 2, 8))
        engine.primary_model_name = engine.model_cache_key
        engine.primary_sources = original
        engine.demix_demucs = lambda mix: preprocessed
        with patch("engines.demucs_runtime.acquire_demucs_model", return_value=object()):
            with self.assertRaisesRegex(
                ValueError, "pre-processing result produced 2_stem; expected 4_stem"
            ):
                infer_demucs_native(
                    engine,
                    prepare_mix=lambda audio: np.zeros((2, 8)),
                    process_secondary_model=lambda *args, **kwargs: {INST_STEM: np.zeros((2, 8))},
                )
        np.testing.assert_array_equal(original, np.ones((4, 2, 8)))
        np.testing.assert_array_equal(preprocessed, np.zeros((2, 2, 8)))

    def test_secondary_model_trace_prefers_carried_display_label(self) -> None:
        source = (_REPO / "engines" / "orchestration.py").read_text(encoding="utf-8")
        self.assertIn('getattr(secondary_model, "model_display_label", None)', source)
        self.assertNotIn("model=secondary_model.model_basename", source)


if __name__ == "__main__":
    unittest.main()
