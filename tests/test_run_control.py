import unittest

from uvr_gtk.run_control import _format_mmss


class FormatMmssTests(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(_format_mmss(0), "0:00")

    def test_under_one_minute(self):
        self.assertEqual(_format_mmss(42.9), "0:42")

    def test_over_one_minute(self):
        self.assertEqual(_format_mmss(125), "2:05")


if __name__ == "__main__":
    unittest.main()
