"""Expander state for the input-files row."""

from __future__ import annotations

import unittest

from ui.widgets.file_chooser import expander_state


class ExpanderStateTests(unittest.TestCase):
    def test_single_file_never_expands(self):
        self.assertEqual(
            expander_state(1, was_expanded=True, preserve=True), (False, False)
        )

    def test_empty_selection_never_expands(self):
        self.assertEqual(
            expander_state(0, was_expanded=True, preserve=True), (False, False)
        )

    def test_new_multi_selection_starts_collapsed(self):
        self.assertEqual(
            expander_state(4, was_expanded=True, preserve=False), (True, False)
        )

    def test_removal_preserves_open_expander(self):
        self.assertEqual(
            expander_state(4, was_expanded=True, preserve=True), (True, True)
        )

    def test_removal_preserves_closed_expander(self):
        self.assertEqual(
            expander_state(4, was_expanded=False, preserve=True), (True, False)
        )

    def test_dropping_to_one_file_forces_collapse(self):
        self.assertEqual(
            expander_state(1, was_expanded=True, preserve=True), (False, False)
        )


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
