"""Sample trim dialog driven through a fake engine."""

from __future__ import annotations

import os
import unittest
from typing import TYPE_CHECKING, Mapping

from tests.playback_fakes import FakeEngine

if TYPE_CHECKING:
    from ui.playback.trim import RangeEdit, TrimDialog


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
        lengths: Mapping[str, float] | None = None,
        duration: float = 30,
    ) -> tuple[TrimDialog, FakeEngine]:
        from ui.playback.trim import TrimDialog

        engine = FakeEngine()
        self.applied: list[dict[str, RangeEdit]] = []
        dialog = TrimDialog(
            inputs,
            engine,
            duration=duration,
            starts=starts or {},
            lengths=lengths,
            on_apply=self.applied.append,
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
        self.assertEqual(self.applied, [{"/in/a.wav": (10.0, None)}])

    def test_apply_writes_only_edited_inputs(self) -> None:
        dialog, _ = self._dialog(starts={"/in/b.wav": 5.0})
        _drag(dialog, 20)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (10.0, None)}])

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
        self.assertEqual(self.applied, [{"/in/a.wav": (None, None)}])

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
        self.assertEqual(self.applied, [{"/in/a.wav": (10.0, None), "/in/b.wav": (20.0, None)}])

    def test_a_start_past_the_end_is_pulled_back_with_the_file(self) -> None:
        dialog, engine = self._dialog(inputs=("/in/a.wav",), starts={"/in/a.wav": 40.0})
        engine._duration = 20.0
        engine.on_duration(20.0)
        self.assertEqual(dialog.view.waveforms[0].range_start, 0.0)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (None, None)}])

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

    def _press(self, dialog: TrimDialog, keyval: int, *, shift: bool = True) -> bool:
        from gi.repository import Gdk

        state = Gdk.ModifierType.SHIFT_MASK if shift else Gdk.ModifierType(0)
        return dialog.surface._on_key_pressed(dialog.surface.keys, keyval, 0, state)

    def test_range_label_reads_the_current_range(self) -> None:
        dialog, _ = self._dialog(starts={"/in/a.wav": 12.0})
        assert dialog.range_label is not None
        self.assertEqual(dialog.range_label.get_label(), "0:12 – 0:42 · 30 s")
        dialog.picker.dropdown.set_selected(1)
        self.assertEqual(dialog.range_label.get_label(), "0:00 – 0:30 · 30 s")
        _drag(dialog, 40)
        self.assertEqual(dialog.range_label.get_label(), "0:20 – 0:50 · 30 s")

    def test_range_label_of_a_short_input_ends_with_the_file(self) -> None:
        dialog, engine = self._dialog(inputs=("/in/a.wav",))
        engine._duration = 20.0
        engine.on_duration(20.0)
        assert dialog.range_label is not None
        self.assertEqual(dialog.range_label.get_label(), "0:00 – 0:20 · 20 s")

    def test_shift_arrows_move_the_range(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(starts={"/in/a.wav": 12.0})
        self.assertTrue(self._press(dialog, Gdk.KEY_Right))
        self.assertTrue(self._press(dialog, Gdk.KEY_Right))
        self.assertTrue(self._press(dialog, Gdk.KEY_Left))
        self.assertEqual(dialog.view.waveforms[0].range_start, 13.0)
        self.assertEqual(engine.calls[-1], ("seek", 13.0))
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (13.0, None)}])

    def test_shift_arrows_stop_at_the_ends_of_the_file(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(inputs=("/in/a.wav",), starts={"/in/a.wav": 69.5})
        engine._duration = 100.0
        engine.on_duration(100.0)
        self._press(dialog, Gdk.KEY_Right)
        self.assertEqual(dialog.view.waveforms[0].range_start, 70.0)
        seeks = len([c for c in engine.calls if c[0] == "seek"])
        self.assertTrue(self._press(dialog, Gdk.KEY_Right))
        self.assertEqual(len([c for c in engine.calls if c[0] == "seek"]), seeks)
        dialog.reset_button.emit("clicked")
        self.assertTrue(self._press(dialog, Gdk.KEY_Left))
        self.assertEqual(dialog.view.waveforms[0].range_start, 0.0)

    def test_plain_arrows_still_skip_within_the_range(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog()
        engine._position = 10.0
        self.assertTrue(self._press(dialog, Gdk.KEY_Right, shift=False))
        self.assertEqual(engine.calls[-1], ("seek", 15.0))
        self.assertEqual(dialog.view.waveforms[0].range_start, 0.0)

    def test_click_outside_the_range_moves_it(self) -> None:
        dialog, engine = self._dialog()
        waveform = dialog.view.waveforms[0]
        waveform.set_timeline(100.0)
        waveform.begin_range_drag()
        waveform.end_range_drag(100.0, 200.0)
        self.assertEqual(engine.calls[-1], ("seek", 50.0))
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (50.0, None)}])

    def test_shortcuts_list_the_range_keys(self) -> None:
        dialog, _ = self._dialog()
        self.assertEqual([w.get_visible() for w in dialog.surface.range_key_rows], [True] * 4)
        self.assertEqual([hint.get_visible() for hint in dialog.view.key_hints], [False])

    def _drag_handle(self, dialog: TrimDialog, x: float, dx: float) -> None:
        """Drag a trim handle starting at ``x`` by ``dx`` pixels on a 100 s, 200 px axis."""
        waveform = dialog.view.waveforms[0]
        waveform.set_timeline(100.0)
        waveform.begin_range_drag(x, 200.0)
        waveform.update_range_drag(dx, 200.0)
        waveform.end_range_drag(x + dx, 200.0)

    def test_dragging_the_end_handle_sets_this_inputs_length(self) -> None:
        dialog, engine = self._dialog()
        self._drag_handle(dialog, 64, 20)
        waveform = dialog.view.waveforms[0]
        self.assertEqual((waveform.range_start, waveform.range_length), (0.0, 40.0))
        self.assertEqual((dialog.loop.range_start, dialog.loop.range_end), (0.0, 40.0))
        self.assertEqual(engine.calls[-1], ("seek", 0.0))
        assert dialog.range_label is not None
        self.assertEqual(dialog.range_label.get_label(), "0:00 – 0:40 · 40 s")
        self.assertTrue(dialog.reset_button.get_sensitive())
        dialog.picker.dropdown.set_selected(1)
        self.assertEqual(dialog.view.waveforms[0].range_length, 30.0)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (None, 40.0)}])

    def test_dragging_the_start_handle_keeps_the_end(self) -> None:
        dialog, _ = self._dialog(starts={"/in/a.wav": 20.0})
        self._drag_handle(dialog, 36, -20)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (10.0, 40.0)}])

    def test_handle_drag_previews_the_range_text(self) -> None:
        dialog, _ = self._dialog()
        waveform = dialog.view.waveforms[0]
        waveform.set_timeline(100.0)
        waveform.begin_range_drag(64, 200.0)
        waveform.update_range_drag(30, 200.0)
        assert dialog.range_label is not None
        self.assertEqual(dialog.range_label.get_label(), "0:00 – 0:45 · 45 s")
        self.assertEqual(self.applied, [])

    def test_stored_length_is_shown_and_reset_restores_the_default(self) -> None:
        dialog, _ = self._dialog(starts={"/in/a.wav": 12.0}, lengths={"/in/a.wav": 45.0})
        waveform = dialog.view.waveforms[0]
        self.assertEqual((waveform.range_start, waveform.range_length), (12.0, 45.0))
        dialog.reset_button.emit("clicked")
        self.assertEqual((waveform.range_start, waveform.range_length), (0.0, 30.0))
        self.assertFalse(dialog.reset_button.get_sensitive())
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (None, None)}])

    def test_resizing_back_to_the_default_follows_preferences_again(self) -> None:
        dialog, _ = self._dialog(lengths={"/in/a.wav": 40.0})
        self._drag_handle(dialog, 84, -20)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (None, None)}])

    def test_shift_up_and_down_change_the_length(self) -> None:
        from gi.repository import Gdk

        dialog, _ = self._dialog(starts={"/in/a.wav": 12.0})
        self.assertTrue(self._press(dialog, Gdk.KEY_Up))
        self.assertTrue(self._press(dialog, Gdk.KEY_Up))
        self.assertTrue(self._press(dialog, Gdk.KEY_Down))
        self.assertEqual(dialog.view.waveforms[0].range_length, 31.0)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{"/in/a.wav": (12.0, 31.0)}])

    def test_length_keys_stop_at_the_limits_and_the_file(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(inputs=("/in/a.wav",), lengths={"/in/a.wav": 6.0})
        self._press(dialog, Gdk.KEY_Down)
        self._press(dialog, Gdk.KEY_Down)
        self.assertEqual(dialog.view.waveforms[0].range_length, 5.0)
        engine._duration = 50.0
        engine.on_duration(50.0)
        dialog._set_range(30.0, 20.0)
        for _ in range(40):
            self._press(dialog, Gdk.KEY_Up)
        waveform = dialog.view.waveforms[0]
        # Lengthening at the file end pulls the start back; the file caps the length.
        self.assertEqual((waveform.range_start, waveform.range_length), (0.0, 50.0))

    def test_length_keys_on_a_short_input_work_from_the_file_length(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(inputs=("/in/a.wav",))
        engine._duration = 20.0
        engine.on_duration(20.0)
        self._press(dialog, Gdk.KEY_Up)
        self.assertEqual(dialog.view.waveforms[0].range_length, 30.0)
        self._press(dialog, Gdk.KEY_Down)
        self.assertEqual(dialog.view.waveforms[0].range_length, 19.0)

    def test_preferences_length_leaves_a_custom_length_alone(self) -> None:
        dialog, _ = self._dialog(inputs=("/in/a.wav",), lengths={"/in/a.wav": 45.0})
        dialog.set_duration(15)
        self.assertEqual(dialog.view.waveforms[0].range_length, 45.0)
        dialog.apply_button.emit("clicked")
        self.assertEqual(self.applied, [{}])

    def test_single_input_names_the_file(self) -> None:
        dialog, _ = self._dialog(inputs=("/in/a.wav",))
        self.assertEqual(dialog.picker.window_title.get_subtitle(), "a.wav")
        self.assertEqual([t.get_label() for t in dialog.view.titles], ["a.wav"])


if __name__ == "__main__":
    unittest.main()
