import unittest

from ui.help_text import iter_help_strings, validate_help_text


class HelpTextStyleTests(unittest.TestCase):
    def test_all_tooltip_strings_follow_style_guide(self):
        violations: list[str] = []
        for name, text in iter_help_strings():
            violations.extend(validate_help_text(text, name=name))
        self.assertEqual(
            violations,
            [],
            "Help text style violations:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
