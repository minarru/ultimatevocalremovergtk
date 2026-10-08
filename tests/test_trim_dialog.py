"""Sample trim dialog driven through a fake engine."""

from __future__ import annotations

import os
import unittest
from typing import TYPE_CHECKING, Mapping

from tests.playback_fakes import FakeEngine

if TYPE_CHECKING:
    from ui.playback.trim import TrimDialog


def _drag(dialog: TrimDialog, dx: float, width: float = 200.0) -> None:
    """Drag the only waveform's range by ``dx`` pixels on a 100 s axis."""
    waveform = dialog.view.waveforms[0]
    waveform.set_timeline(100.0)
    waveform.begin_range_drag()
    waveform.update_range_drag(dx, width)
    waveform.end_range_drag(0.0, width)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class TrimDialogTests(unittest.TestCase):
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
        self,
        *,
        inputs: tuple[str, ...] = ("/in/a.wav", "/in/b.wav"),
        starts: Mapping[str, float] | None = None,
        duration: float = 30,
    ) -> tuple[TrimDialog, FakeEngine]:
        from ui.playback.trim import TrimDialog

        engine = FakeEngine()
        self.applied: list[dict[str, float | None]] = []
        dialog = TrimDialog(
            inputs, engine, duration=duration, starts=starts or {}, on_apply=self.applied.append
        )
        return dialog, engine

    def _loads(self, engine: FakeEngine) -> list[tuple[object, ...]]:
        return [c for c in engine.calls if c[0] == "load"]

    def test_shows_the_input_from_its_stored_start(self) -> None:
        dialog, engine = self._dialog(starts={"/in/a.wav": 12.0})
        self.assertEqual(engine.calls[0][1], ("/in/a.wav",))
        self.assertEqual(engine.calls[0][3], 12.0)
        waveform = dialog.view.waveforms[0]
        self.assertEqual((waveform.range_start, waveform.range_length), (12.0, 30.0))

    def test_range_drag_records_an_edit_and_seeks(self) -> None:
        dialog, engine = self._dialog()
        _drag(dialog, 20)
        self.assertIn(("seek", 10.0), engine.calls)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": 10.0}])

    def test_apply_writes_only_edited_inputs(self) -> None:
        dialog, _ = self._dialog(starts={"/in/b.wav": 5.0})
        _drag(dialog, 20)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": 10.0}])

    def test_cancel_discards_edits(self) -> None:
        dialog, engine = self._dialog()
        _drag(dialog, 20)
        dialog.cancel_button.emit("clicked")
        self.assertEqual(self.applied, [])
        self.assertEqual(engine.calls[-1], ("unload",))

    def test_closing_discards_edits(self) -> None:
        dialog, _ = self._dialog()
        _drag(dialog, 20)
        dialog.surface.close()
        self.assertEqual(self.applied, [])

    def test_reset_removes_the_start(self) -> None:
        dialog, _ = self._dialog(starts={"/in/a.wav": 12.0})
        dialog.reset_button.emit("clicked")
        self.assertEqual(dialog.view.waveforms[0].range_start, 0.0)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": None}])

    def test_reset_is_insensitive_at_zero(self) -> None:
        dialog, _ = self._dialog()
        self.assertFalse(dialog.reset_button.get_sensitive())
        _drag(dialog, 20)
        self.assertTrue(dialog.reset_button.get_sensitive())

    def test_picker_switches_inputs_keeping_pending_edits(self) -> None:
        dialog, engine = self._dialog()
        _drag(dialog, 20)
        dialog.picker.dropdown.set_selected(1)
        self.assertEqual(self._loads(engine)[-1][1], ("/in/b.wav",))
        dialog.picker.dropdown.set_selected(0)
        self.assertEqual(self._loads(engine)[-1][3], 10.0)
        self.assertEqual(dialog.view.waveforms[0].range_start, 10.0)
        dialog.picker.dropdown.set_selected(1)
        _drag(dialog, 40)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": 10.0, "/in/b.wav": 20.0}])

    def test_a_start_past_the_end_is_pulled_back_with_the_file(self) -> None:
        dialog, engine = self._dialog(inputs=("/in/a.wav",), starts={"/in/a.wav": 40.0})
        engine._duration = 20.0
        engine.on_duration(20.0)
        self.assertEqual(dialog.view.waveforms[0].range_start, 0.0)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": None}])

    def test_set_duration_resizes_the_open_range(self) -> None:
        dialog, engine = self._dialog(starts={"/in/a.wav": 12.0})
        engine._position = 14.0
        dialog.set_duration(15)
        waveform = dialog.view.waveforms[0]
        self.assertEqual((waveform.range_start, waveform.range_length), (12.0, 15.0))
        self.assertNotIn("seek", [call[0] for call in engine.calls])
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{}])

    def test_a_longer_duration_pulls_the_start_back(self) -> None:
        dialog, engine = self._dialog(inputs=("/in/a.wav",), starts={"/in/a.wav": 15.0}, duration=5)
        engine._duration = 20.0
        engine._position = 18.0
        dialog.set_duration(30)
        self.assertEqual(dialog.view.waveforms[0].range_start, 0.0)
        self.assertEqual(engine.calls[-1], ("seek", 0.0))

    def test_short_input_range_covers_the_whole_file(self) -> None:
        dialog, engine = self._dialog(inputs=("/in/a.wav",))
        engine._duration = 20.0
        engine.on_duration(20.0)
        self.assertEqual((dialog.loop.range_start, dialog.loop.range_end), (0.0, 20.0))

    def test_trim_dialog_is_a_commit_surface(self) -> None:
        dialog, _ = self._dialog()
        header = dialog.surface._header
        self.assertFalse(header.get_show_end_title_buttons())
        self.assertEqual([w.get_visible() for w in dialog.surface.track_key_rows], [False, False])
        self.assertEqual(dialog.surface.dialog.get_title(), "Choose Sample Range")

    def test_single_input_names_the_file(self) -> None:
        dialog, _ = self._dialog(inputs=("/in/a.wav",))
        self.assertEqual(dialog.picker.window_title.get_subtitle(), "a.wav")
        self.assertEqual([t.get_label() for t in dialog.view.titles], ["a.wav"])


if __name__ == "__main__":
    unittest.main()
