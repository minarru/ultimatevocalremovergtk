"""Compare stems dialog driven through a fake engine."""

from __future__ import annotations

import os
import unittest
from typing import Any

from core.listening import ComparisonSet
from tests.playback_fakes import FakeEngine, FakeLoader, comparison_set


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class CompareStemsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def _dialog(
        self, *sets: ComparisonSet, output_dir: str = "", loader: bool = False
    ) -> tuple[Any, FakeEngine]:
        from ui.playback.compare_stems import CompareStemsDialog

        engine = FakeEngine()
        closed: list[bool] = []
        self.loader = FakeLoader(engine.calls) if loader else None
        dialog = CompareStemsDialog(
            list(sets),
            engine,
            waveforms=self.loader,
            output_dir=output_dir,
            on_closed=lambda: closed.append(True),
        )
        self.closed = closed
        return dialog, engine

    def test_single_input_names_the_song_in_the_header(self) -> None:
        dialog, _ = self._dialog(comparison_set("song", "Vocals"))
        self.assertTrue(dialog.window_title.get_visible())
        self.assertEqual(dialog.window_title.get_subtitle(), "song.wav")

    def test_several_inputs_put_the_picker_in_the_header(self) -> None:
        dialog, _ = self._dialog(comparison_set("a", "Vocals"), comparison_set("b", "Vocals"))
        self.assertTrue(dialog.input_dropdown.get_visible())
        self.assertFalse(dialog.window_title.get_visible())

    def test_dropdown_hidden_for_single_input(self) -> None:
        dialog, _ = self._dialog(comparison_set("song", "Vocals"))
        self.assertFalse(dialog.input_dropdown.get_visible())

    def test_dropdown_switch_reloads_and_keeps_position_paused(self) -> None:
        dialog, engine = self._dialog(
            comparison_set("a", "Vocals"), comparison_set("b", "Vocals", "Drums")
        )
        self.assertTrue(dialog.input_dropdown.get_visible())
        engine.play()
        engine._position = 12.0
        dialog.input_dropdown.set_selected(1)
        self.assertIn(("pause",), engine.calls)
        self.assertEqual(engine.calls[-1][0], "load")
        self.assertEqual(engine.calls[-1][1][0], "/in/b.wav")
        self.assertEqual(engine.calls[-1][3], 12.0)
        self.assertEqual(len(dialog.view.rows), 3)

    def test_many_tracks_scroll_instead_of_growing(self) -> None:
        from gi.repository import Gtk

        # A 6-stem Demucs run plus the reference must still fit a 768 px screen.
        dialog, _ = self._dialog(comparison_set("song", *(f"Stem {n}" for n in range(1, 10))))
        content = dialog.surface.dialog.get_child()
        assert content is not None
        minimum, _natural, _min_base, _nat_base = content.measure(Gtk.Orientation.VERTICAL, 560)
        self.assertLess(minimum, 600)

    def test_folder_button_hidden_without_output_dir(self) -> None:
        dialog, _ = self._dialog(comparison_set("song", "Vocals"))
        self.assertFalse(dialog.folder_button.get_visible())

    def test_closing_unloads_and_notifies(self) -> None:
        dialog, engine = self._dialog(comparison_set("song", "Vocals"))
        dialog.surface.dialog.emit("closed")
        self.assertEqual(engine.calls[-1], ("unload",))
        self.assertEqual(self.closed, [True])

    def test_switching_input_in_popped_out_window_rebuilds_rows(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(
            comparison_set("a", "Vocals"), comparison_set("b", "Vocals", "Drums")
        )
        dialog.surface.pop_out()
        dialog.input_dropdown.set_selected(1)
        self.assertIs(dialog.view.rows[2].get_root(), dialog.surface.window)
        self.assertTrue(dialog.view.handle_key(Gdk.KEY_3))
        self.assertEqual(engine.calls[-1], ("select", 2))
        dialog.close()

    def test_folder_opens_over_the_popped_out_window(self) -> None:
        from unittest import mock

        dialog, _ = self._dialog(comparison_set("song", "Vocals"), output_dir="/tmp")
        dialog.surface.pop_out()
        with mock.patch("ui.playback.compare_stems.open_folder_in_file_manager") as open_folder:
            dialog.folder_button.emit("clicked")
        self.assertIs(open_folder.call_args.args[0], dialog.surface.window)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
