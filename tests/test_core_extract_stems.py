import os
import tempfile
import unittest

from core.ensembler import _extract_stems


class ExtractStemsTests(unittest.TestCase):
    def test_finds_shared_stem_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = "1-track"
            open(os.path.join(tmp, f"{base} modelA (Vocals).wav"), "wb").close()
            open(os.path.join(tmp, f"{base} modelB (Vocals).wav"), "wb").close()
            open(os.path.join(tmp, f"{base} modelA (Instrumental).wav"), "wb").close()
            stems = _extract_stems(base, tmp)
            self.assertEqual(stems, ["Vocals"])

    def test_merges_case_variants_of_same_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = "1-track"
            open(os.path.join(tmp, f"{base} huge_scnet (vocals).wav"), "wb").close()
            open(os.path.join(tmp, f"{base} hdemucs (Vocals).wav"), "wb").close()
            open(os.path.join(tmp, f"{base} huge_scnet (drums).wav"), "wb").close()
            open(os.path.join(tmp, f"{base} hdemucs (Drums).wav"), "wb").close()
            stems = set(_extract_stems(base, tmp))
            self.assertEqual(stems, {"Vocals", "Drums"})

    def test_missing_directory_returns_empty(self):
        self.assertEqual(_extract_stems("missing", "/nonexistent/path"), [])


if __name__ == "__main__":
    unittest.main()
