"""Keyboard shortcut table consistency checks."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "shortcuts module imports GTK",
)
class ShortcutsConsistencyTests(unittest.TestCase):
    def test_every_section_action_has_accelerator(self):
        from ui.hints import KEYBOARD_ACCELERATORS
        from ui.shortcuts import _SECTIONS

        for section_title, items in _SECTIONS:
            for action_name, title in items:
                with self.subTest(section=section_title, action=action_name, title=title):
                    accels = KEYBOARD_ACCELERATORS.get(action_name) or []
                    self.assertTrue(
                        accels,
                        f"{action_name!r} is listed in shortcuts but has no accelerator",
                    )

    def test_model_options_is_documented(self):
        from ui.hints import KEYBOARD_ACCELERATORS
        from ui.shortcuts import _SECTIONS

        self.assertIn("win.model_options", KEYBOARD_ACCELERATORS)
        documented = {
            action for _section, items in _SECTIONS for action, _title in items
        }
        self.assertIn("win.model_options", documented)


if __name__ == "__main__":
    unittest.main()
