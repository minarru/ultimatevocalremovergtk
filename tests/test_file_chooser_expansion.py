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


if __name__ == "__main__":
    unittest.main()
