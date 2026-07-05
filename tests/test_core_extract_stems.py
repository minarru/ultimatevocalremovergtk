import os
import tempfile
import unittest

from core.job_runner import _extract_stems


class ExtractStemsTests(unittest.TestCase):
    def test_finds_shared_stem_tags(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = "1_track"
            open(os.path.join(tmp, f"{base}_modelA_(Vocals).wav"), "wb").close()
            open(os.path.join(tmp, f"{base}_modelB_(Vocals).wav"), "wb").close()
            open(os.path.join(tmp, f"{base}_modelA_(Instrumental).wav"), "wb").close()
            stems = _extract_stems(base, tmp)
            self.assertEqual(stems, ["Vocals"])

    def test_missing_directory_returns_empty(self):
        self.assertEqual(_extract_stems("missing", "/nonexistent/path"), [])


if __name__ == "__main__":
    unittest.main()
