import unittest
from unittest.mock import MagicMock

from bundled.constants import VOCAL_STEM
from core.ensembler import _capture_separator_stem_arrays, _ensemble_stem_bucket


class EnsembleStemBucketTests(unittest.TestCase):
    def test_bucket_folds_yaml_and_demucs_casing(self):
        self.assertEqual(_ensemble_stem_bucket("vocals"), VOCAL_STEM)
        self.assertEqual(_ensemble_stem_bucket("Vocals"), VOCAL_STEM)
        self.assertEqual(_ensemble_stem_bucket("drums"), "Drums")

    def test_capture_preserves_case_variant_buffer_keys_for_planned_route_matching(self):
        sep = MagicMock()
        sep._ensemble_stem_buffers = {
            "vocals": [[0.1, 0.2]],
            "Vocals": [[0.3, 0.4]],
        }
        captured = _capture_separator_stem_arrays(sep)
        self.assertEqual(set(captured), {"vocals", VOCAL_STEM})
        self.assertEqual(captured["vocals"].tolist(), [[0.1, 0.2]])
        self.assertEqual(captured[VOCAL_STEM].tolist(), [[0.3, 0.4]])


if __name__ == "__main__":
    unittest.main()
