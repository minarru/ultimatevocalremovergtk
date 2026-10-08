"""Header picker shared by the listening tools: a title for one input, a list for several."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class InputPickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def test_single_name_is_the_subtitle(self) -> None:
        from ui.playback.input_picker import InputPicker

        picker = InputPicker("Compare Stems", ["a.wav"], lambda _index: None)
        self.assertEqual(picker.window_title.get_title(), "Compare Stems")
        self.assertEqual(picker.window_title.get_subtitle(), "a.wav")
        self.assertTrue(picker.window_title.get_visible())
        self.assertFalse(picker.dropdown.get_visible())

    def test_several_names_use_the_dropdown(self) -> None:
        from gi.repository import Gtk

        from ui.playback.input_picker import InputPicker

        chosen: list[int] = []
        picker = InputPicker("Compare Stems", ["a.wav", "b.wav"], chosen.append)
        self.assertFalse(picker.window_title.get_visible())
        self.assertTrue(picker.dropdown.get_visible())
        model = picker.dropdown.get_model()
        assert isinstance(model, Gtk.StringList)
        labels = [model.get_string(i) for i in range(model.get_n_items())]
        self.assertEqual(labels, ["a.wav  1 of 2", "b.wav  2 of 2"])
        picker.dropdown.set_selected(1)
        self.assertEqual(chosen, [1])
        self.assertEqual(picker.selected, 1)


if __name__ == "__main__":
    unittest.main()
