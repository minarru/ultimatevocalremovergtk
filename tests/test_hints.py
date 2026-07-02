import unittest

from uvr_gtk.hints import format_hint


class FormatHintTests(unittest.TestCase):
    def test_strips_trailing_period(self):
        self.assertEqual(format_hint("Save output."), "Save output")

    def test_keeps_etc_suffix(self):
        self.assertEqual(format_hint("Use wav, flac, etc."), "Use wav, flac, etc.")

    def test_collapses_blank_lines(self):
        self.assertEqual(format_hint("Line one\n\n\nLine two"), "Line one\n\nLine two")

    def test_bullet_lines_preserved(self):
        self.assertEqual(format_hint("• First\n• Second"), "• First\n• Second")


if __name__ == "__main__":
    unittest.main()
