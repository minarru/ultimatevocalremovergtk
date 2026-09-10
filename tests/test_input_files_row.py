"""The compact input row retains selection controls without an inline list."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "GTK needs a display")
class InputFilesRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def test_multiple_inputs_stay_a_summary_and_clear_notifies(self):
        from gi.repository import Adw

        from ui.widgets.file_chooser import InputFilesRow

        with tempfile.TemporaryDirectory() as folder:
            paths = [str(Path(folder) / name) for name in ("first.wav", "second.wav")]
            for path in paths:
                Path(path).touch()
            changed = Mock()
            row = InputFilesRow(changed)
            self.assertIsInstance(row, Adw.ActionRow)
            self.assertNotIsInstance(row, Adw.ExpanderRow)
            row.set_paths(paths, notify=False)
            self.assertEqual(row.paths, paths)
            self.assertEqual(row.get_subtitle(), "first.wav (and 1 more)")
            changed.assert_not_called()
            self.assertTrue(row._clear_button.get_sensitive())
            row._clear_button.emit("clicked")
            self.assertEqual(row.paths, [])
            self.assertEqual(row.get_subtitle(), "No files selected")
            self.assertFalse(row._clear_button.get_sensitive())
            changed.assert_called_once_with()
