"""Compare stems dialog driven through a fake engine."""

from __future__ import annotations

import os
import unittest
from typing import Any, Callable, Sequence

from core.listening import REFERENCE_LABEL, ComparisonSet, Track


def _noop(*_a: object) -> None:
    return None


class FakeEngine:
    def __init__(self) -> None:
        self.on_position: Callable[[float], None] = _noop
        self.on_duration: Callable[[float], None] = _noop
        self.on_state: Callable[[bool], None] = _noop
        self.on_track_error: Callable[[int, str], None] = _noop
        self.on_error: Callable[[str], None] = _noop
        self.calls: list[tuple[Any, ...]] = []
        self._playing = False
        self._selected = 0
        self._loaded = False
        self._position = 0.0
        self._duration = 0.0

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def position(self) -> float:
        return self._position

    @property
    def selected(self) -> int:
        return self._selected

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0) -> None:
        self.calls.append(("load", tuple(t.path for t in tracks), selected, position))
        self._loaded = True
        self._selected = selected

    def play(self) -> None:
        self.calls.append(("play",))
        self._playing = True
        self.on_state(True)

    def pause(self) -> None:
        self.calls.append(("pause",))
        self._playing = False
        self.on_state(False)

    def toggle(self) -> None:
        self.pause() if self._playing else self.play()

    def seek(self, seconds: float) -> None:
        self.calls.append(("seek", seconds))
        self._position = seconds

    def select(self, index: int) -> None:
        self.calls.append(("select", index))
        self._selected = index

    def unload(self) -> None:
        self.calls.append(("unload",))
        self._loaded = False


def _set(name: str, *labels: str) -> ComparisonSet:
    src = f"/in/{name}.wav"
    tracks = [Track(REFERENCE_LABEL, src, None, True)]
    tracks += [Track(label, f"/out/{name} ({label}).wav") for label in labels]
    return ComparisonSet(src, tuple(tracks))


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class CompareDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def _dialog(self, *sets: ComparisonSet, output_dir: str = "") -> tuple[Any, FakeEngine]:
        from ui.playback.dialog import CompareDialog

        engine = FakeEngine()
        closed: list[bool] = []
        dialog = CompareDialog(
            list(sets), engine, output_dir=output_dir, on_closed=lambda: closed.append(True)
        )
        self.closed = closed
        return dialog, engine

    def test_loads_first_set_with_first_output_selected(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        self.assertEqual(
            engine.calls[0],
            (
                "load",
                ("/in/song.wav", "/out/song (Vocals).wav", "/out/song (Instrumental).wav"),
                1,
                0.0,
            ),
        )
        self.assertEqual(
            [r.get_title() for r in dialog.rows], [REFERENCE_LABEL, "Vocals", "Instrumental"]
        )

    def test_dropdown_hidden_for_single_input(self) -> None:
        dialog, _ = self._dialog(_set("song", "Vocals"))
        self.assertFalse(dialog.input_dropdown.get_visible())

    def test_dropdown_switch_reloads_and_keeps_position_paused(self) -> None:
        dialog, engine = self._dialog(_set("a", "Vocals"), _set("b", "Vocals", "Drums"))
        self.assertTrue(dialog.input_dropdown.get_visible())
        engine.play()
        engine._position = 12.0
        dialog.input_dropdown.set_selected(1)
        self.assertIn(("pause",), engine.calls)
        self.assertEqual(engine.calls[-1][0], "load")
        self.assertEqual(engine.calls[-1][1][0], "/in/b.wav")
        self.assertEqual(engine.calls[-1][3], 12.0)
        self.assertEqual(len(dialog.rows), 3)

    def test_row_activation_selects_track(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        dialog.rows[2].activate()
        self.assertEqual(engine.calls[-1], ("select", 2))

    def test_number_keys_select_and_space_toggles(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        self.assertTrue(dialog.handle_key(Gdk.KEY_1))
        self.assertEqual(engine.calls[-1], ("select", 0))
        self.assertTrue(dialog.handle_key(Gdk.KEY_space))
        self.assertEqual(engine.calls[-1], ("play",))
        self.assertFalse(dialog.handle_key(Gdk.KEY_9))

    def test_shortcuts_are_captured_before_focused_children(self) -> None:
        from gi.repository import Gtk

        # A focused radio or button would otherwise swallow Space before the dialog.
        dialog, _ = self._dialog(_set("song", "Vocals"))
        self.assertEqual(dialog._keys.get_propagation_phase(), Gtk.PropagationPhase.CAPTURE)

    def test_arrow_keys_seek_five_seconds(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(_set("song", "Vocals"))
        engine._position = 10.0
        dialog.handle_key(Gdk.KEY_Right)
        self.assertEqual(engine.calls[-1], ("seek", 15.0))
        dialog.handle_key(Gdk.KEY_Left)
        self.assertEqual(engine.calls[-1], ("seek", 10.0))

    def test_failed_track_row_is_insensitive(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        engine.on_track_error(2, "Could not determine type of stream")
        self.assertFalse(dialog.rows[2].get_sensitive())
        self.assertIn("Could not determine", dialog.rows[2].get_tooltip_text() or "")

    def test_radio_follows_engine_when_default_track_fails(self) -> None:
        from ui.playback.dialog import CompareDialog

        class FailingVocalsEngine(FakeEngine):
            def load(
                self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0
            ) -> None:
                super().load(tracks, selected=selected, position=position)
                self.on_track_error(1, "gone")
                self._selected = 0

        engine = FailingVocalsEngine()
        dialog = CompareDialog([_set("song", "Vocals", "Instrumental")], engine)
        self.assertEqual([c.get_active() for c in dialog._checks], [True, False, False])
        self.assertFalse(dialog.rows[1].get_sensitive())
        self.assertNotIn(("select", 0), engine.calls)

    def test_engine_error_disables_transport_and_toasts(self) -> None:
        from ui.playback.dialog import CompareDialog

        toasts: list[str] = []
        engine = FakeEngine()
        dialog = CompareDialog([_set("song", "Vocals")], engine, on_toast=toasts.append)
        engine.on_error("No audio sink")
        self.assertFalse(dialog.play_button.get_sensitive())
        self.assertEqual(toasts, ["Couldn't start playback. No audio sink"])

    def test_duration_and_position_update_labels_and_scale(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"))
        engine.on_duration(225.0)
        engine.on_position(83.0)
        self.assertEqual(dialog.seek_scale.get_adjustment().get_upper(), 225.0)
        self.assertEqual(dialog.seek_scale.get_value(), 83.0)

    def test_play_button_icon_follows_state(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"))
        engine.play()
        self.assertEqual(dialog.play_button.get_icon_name(), "media-playback-pause-symbolic")
        engine.pause()
        self.assertEqual(dialog.play_button.get_icon_name(), "media-playback-start-symbolic")

    def test_folder_button_hidden_without_output_dir(self) -> None:
        dialog, _ = self._dialog(_set("song", "Vocals"))
        self.assertFalse(dialog.folder_button.get_visible())

    def test_closed_signal_unloads_and_notifies(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"))
        dialog.dialog.emit("closed")
        self.assertEqual(engine.calls[-1], ("unload",))
        self.assertEqual(self.closed, [True])


if __name__ == "__main__":
    unittest.main()
