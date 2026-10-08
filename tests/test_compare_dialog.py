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
class CompareDialogTests(unittest.TestCase):
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
        from ui.playback.dialog import CompareDialog

        engine = FakeEngine()
        closed: list[bool] = []
        self.loader = FakeLoader(engine.calls) if loader else None
        dialog = CompareDialog(
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

    def test_shortcuts_are_captured_before_focused_children(self) -> None:
        from gi.repository import Gtk

        # A focused radio or button would otherwise swallow Space before the dialog.
        dialog, _ = self._dialog(comparison_set("song", "Vocals"))
        self.assertEqual(dialog._keys.get_propagation_phase(), Gtk.PropagationPhase.CAPTURE)

    def test_engine_error_disables_transport_and_toasts(self) -> None:
        from ui.playback.dialog import CompareDialog

        toasts: list[str] = []
        engine = FakeEngine()
        dialog = CompareDialog([comparison_set("song", "Vocals")], engine, on_toast=toasts.append)
        engine.on_error("No audio sink")
        self.assertFalse(dialog.view.play_button.get_sensitive())
        self.assertEqual(toasts, ["Couldn't start playback. No audio sink"])

    def test_many_tracks_scroll_instead_of_growing(self) -> None:
        from gi.repository import Gtk

        # A 6-stem Demucs run plus the reference must still fit a 768 px screen.
        dialog, _ = self._dialog(comparison_set("song", *(f"Stem {n}" for n in range(1, 10))))
        content = dialog.dialog.get_child()
        assert content is not None
        minimum, _natural, _min_base, _nat_base = content.measure(Gtk.Orientation.VERTICAL, 560)
        self.assertLess(minimum, 600)

    def test_folder_button_hidden_without_output_dir(self) -> None:
        dialog, _ = self._dialog(comparison_set("song", "Vocals"))
        self.assertFalse(dialog.folder_button.get_visible())

    def test_closed_signal_unloads_and_notifies(self) -> None:
        dialog, engine = self._dialog(comparison_set("song", "Vocals"))
        dialog.dialog.emit("closed")
        self.assertEqual(engine.calls[-1], ("unload",))
        self.assertEqual(self.closed, [True])

    def test_pop_out_moves_content_into_a_window_without_unloading(self) -> None:
        dialog, engine = self._dialog(comparison_set("song", "Vocals"))
        self.assertTrue(dialog.popout_button.get_visible())
        engine.calls.clear()
        dialog.popout_button.emit("clicked")
        window = dialog.window
        self.assertIsNotNone(window)
        self.assertIsNone(dialog.dialog.get_child())
        self.assertIs(window.get_root(), window)
        self.assertIs(dialog.view.play_button.get_root(), window)
        self.assertFalse(dialog.popout_button.get_visible())
        self.assertNotIn(("unload",), engine.calls)
        self.assertEqual(self.closed, [])
        # The handed-over dialog no longer owns playback.
        dialog.dialog.emit("closed")
        self.assertEqual(self.closed, [])
        window.close()
        self.assertEqual(engine.calls[-1], ("unload",))
        self.assertEqual(self.closed, [True])

    def test_shortcuts_follow_the_popped_out_window(self) -> None:
        dialog, _ = self._dialog(comparison_set("song", "Vocals"))
        dialog.pop_out()
        self.assertIs(dialog._keys.get_widget(), dialog.window)
        assert dialog.window is not None
        dialog.window.close()

    def test_open_in_window_presents_a_window_directly(self) -> None:
        from ui.playback.dialog import CompareDialog

        engine = FakeEngine()
        dialog = CompareDialog([comparison_set("song", "Vocals")], engine, open_in_window=True)
        self.assertIsNone(dialog.window)
        dialog.present(None)
        window = dialog.window
        assert window is not None
        self.assertTrue(window.get_visible())
        # Presenting again raises the same window rather than building another.
        dialog.present(None)
        self.assertIs(dialog.window, window)
        dialog.close()
        self.assertEqual(engine.calls[-1], ("unload",))

    def test_toasts_stay_in_the_popped_out_window(self) -> None:
        from ui.playback.dialog import CompareDialog

        toasts: list[str] = []
        dialog = CompareDialog(
            [comparison_set("song", "Vocals")], FakeEngine(), on_toast=toasts.append
        )
        dialog.pop_out()
        dialog._toast("hello")
        self.assertEqual(toasts, [])
        assert dialog.window is not None
        dialog.window.close()


if __name__ == "__main__":
    unittest.main()
