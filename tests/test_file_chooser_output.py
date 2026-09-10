"""Output-folder row subtitle presentation."""

import unittest


class OutputSubtitleTests(unittest.TestCase):
    def test_empty_path_is_not_an_error(self):
        from ui.widgets.file_chooser import output_subtitle

        subtitle, is_error = output_subtitle("", None)
        self.assertEqual(subtitle, "No folder selected")
        self.assertFalse(is_error)

    def test_valid_path_is_shown_plainly(self):
        from ui.widgets.file_chooser import output_subtitle

        subtitle, is_error = output_subtitle("/tmp/out", None)
        self.assertEqual(subtitle, "/tmp/out")
        self.assertFalse(is_error)

    def test_missing_folder_is_an_error(self):
        from ui.widgets.file_chooser import output_subtitle

        subtitle, is_error = output_subtitle(
            "/tmp/gone", "Output folder no longer exists — select a new folder"
        )
        self.assertTrue(is_error)
        self.assertIn("not found", subtitle)
        self.assertIn("/tmp/gone", subtitle)

    def test_read_only_folder_is_an_error(self):
        from ui.widgets.file_chooser import output_subtitle

        subtitle, is_error = output_subtitle(
            "/tmp/ro", "Output folder is not writable — choose another folder"
        )
        self.assertTrue(is_error)
        self.assertIn("not writable", subtitle)


if __name__ == "__main__":
    unittest.main()
