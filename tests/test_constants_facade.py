import unittest

from bundled.constants import DEFAULT_DATA, VOCAL_STEM, secondary_stem


class ConstantsFacadeTests(unittest.TestCase):
    def test_stem_and_secondary(self):
        self.assertEqual(VOCAL_STEM, "Vocals")
        self.assertEqual(secondary_stem("Vocals"), "Instrumental")

    def test_default_data_present(self):
        self.assertIsInstance(DEFAULT_DATA, dict)
        self.assertIn("save_format", DEFAULT_DATA)

    def test_star_import_exposes_core_names(self):
        ns: dict = {}
        exec("from bundled.constants import *", ns)
        self.assertEqual(ns.get("VOCAL_STEM"), "Vocals")
        self.assertIn("DEFAULT_DATA", ns)
        self.assertTrue(callable(ns.get("secondary_stem")))


if __name__ == "__main__":
    unittest.main()
