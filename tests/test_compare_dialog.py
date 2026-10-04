"""Compare stems dialog driven through a fake engine."""

from __future__ import annotations

import os
import unittest
from typing import Any, Callable, Sequence

import numpy as np

from core.listening import REFERENCE_LABEL, ComparisonSet, Track
from core.waveform import Peaks


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


class FakeLoader:
    def __init__(self, calls: list[tuple[Any, ...]]) -> None:
        self.calls = calls
        self.on_peaks: Callable[[int, Peaks | None], None] | None = None

    def load(
        self, paths: Sequence[str], first: int, on_peaks: Callable[[int, Peaks | None], None]
    ) -> None:
        self.calls.append(("peaks.load", tuple(paths), first))
        self.on_peaks = on_peaks

    def cancel(self) -> None:
        self.calls.append(("peaks.cancel",))


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
            [t.get_label() for t in dialog.titles], [REFERENCE_LABEL, "Vocals", "Instrumental"]
        )

    def test_single_input_names_the_song_in_the_header(self) -> None:
        dialog, _ = self._dialog(_set("song", "Vocals"))
        self.assertTrue(dialog.window_title.get_visible())
        self.assertEqual(dialog.window_title.get_subtitle(), "song.wav")

    def test_several_inputs_put_the_picker_in_the_header(self) -> None:
        dialog, _ = self._dialog(_set("a", "Vocals"), _set("b", "Vocals"))
        self.assertTrue(dialog.input_dropdown.get_visible())
        self.assertFalse(dialog.window_title.get_visible())

    def test_skip_buttons_seek_five_seconds(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"))
        engine._position = 10.0
        dialog.forward_button.emit("clicked")
        self.assertEqual(engine.calls[-1], ("seek", 15.0))
        dialog.back_button.emit("clicked")
        self.assertEqual(engine.calls[-1], ("seek", 10.0))

    def test_audible_row_is_highlighted(self) -> None:
        from gi.repository import Gdk

        dialog, _ = self._dialog(_set("song", "Vocals", "Instrumental"))
        active = [r.has_css_class("uvr-compare-active") for r in dialog.rows]
        self.assertEqual(active, [False, True, False])
        dialog.handle_key(Gdk.KEY_3)
        active = [r.has_css_class("uvr-compare-active") for r in dialog.rows]
        self.assertEqual(active, [False, False, True])

    def test_rows_show_their_number_key(self) -> None:
        dialog, _ = self._dialog(_set("song", *(f"Stem {n}" for n in range(1, 10))))
        self.assertEqual(len(dialog.rows), 10)
        # Only 1–9 have keys; the tenth row gets no hint.
        self.assertEqual([h.get_label() for h in dialog.key_hints], [str(n) for n in range(1, 10)])

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
        # What GTK emits when a row is clicked or activated by keyboard; calling
        # ``activate()`` on a row of an unpresented dialog trips a focus assertion.
        dialog._track_list.emit("row-activated", dialog.rows[2])
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
        self.assertEqual([w.active for w in dialog.waveforms], [True, False, False])

    def test_engine_error_disables_transport_and_toasts(self) -> None:
        from ui.playback.dialog import CompareDialog

        toasts: list[str] = []
        engine = FakeEngine()
        dialog = CompareDialog([_set("song", "Vocals")], engine, on_toast=toasts.append)
        engine.on_error("No audio sink")
        self.assertFalse(dialog.play_button.get_sensitive())
        self.assertEqual(toasts, ["Couldn't start playback. No audio sink"])

    def test_duration_and_position_update_labels_and_waveforms(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"))
        engine.on_duration(225.0)
        engine.on_position(83.0)
        self.assertEqual(dialog._total.get_label(), "3:45")
        self.assertEqual(dialog._elapsed.get_label(), "1:23")
        self.assertEqual([w.timeline for w in dialog.waveforms], [225.0, 225.0])
        self.assertEqual([w.position for w in dialog.waveforms], [83.0, 83.0])

    def test_seek_slider_is_gone(self) -> None:
        dialog, _ = self._dialog(_set("song", "Vocals"))
        self.assertFalse(hasattr(dialog, "seek_scale"))

    def test_many_tracks_scroll_instead_of_growing(self) -> None:
        from gi.repository import Gtk

        # A 6-stem Demucs run plus the reference must still fit a 768 px screen.
        dialog, _ = self._dialog(_set("song", *(f"Stem {n}" for n in range(1, 10))))
        content = dialog.dialog.get_child()
        assert content is not None
        minimum, _natural, _min_base, _nat_base = content.measure(Gtk.Orientation.VERTICAL, 560)
        self.assertLess(minimum, 600)

    def test_waveforms_are_named_after_their_tracks(self) -> None:
        from unittest import mock

        from gi.repository import Gtk

        from ui.widgets.waveform import WaveformView

        with mock.patch.object(WaveformView, "update_property") as update:
            self._dialog(_set("song", "Vocals"))
        labels = [
            c.args[1][0]
            for c in update.call_args_list
            if c.args[0] == [Gtk.AccessibleProperty.LABEL]
        ]
        self.assertEqual(labels, [f"{REFERENCE_LABEL} waveform", "Vocals waveform"])

    def test_one_waveform_per_row(self) -> None:
        dialog, _ = self._dialog(_set("song", "Vocals", "Instrumental"))
        self.assertEqual(len(dialog.waveforms), len(dialog.rows))

    def test_waveform_seek_seeks_without_switching(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        engine.calls.clear()
        dialog.waveforms[0].set_timeline(100.0)
        dialog.waveforms[0].seek_at(50, 200)
        self.assertEqual(engine.calls, [("seek", 25.0)])

    def test_active_waveform_follows_selection(self) -> None:
        from gi.repository import Gdk

        dialog, _ = self._dialog(_set("song", "Vocals", "Instrumental"))
        self.assertEqual([w.active for w in dialog.waveforms], [False, True, False])
        dialog.handle_key(Gdk.KEY_3)
        self.assertEqual([w.active for w in dialog.waveforms], [False, False, True])

    def test_peaks_load_for_the_set_audible_first(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"), loader=True)
        load = [c for c in engine.calls if c[0] == "peaks.load"]
        self.assertEqual(
            load,
            [
                (
                    "peaks.load",
                    ("/in/song.wav", "/out/song (Vocals).wav", "/out/song (Instrumental).wav"),
                    1,
                )
            ],
        )
        peaks = Peaks(1.0, np.zeros(4, dtype=np.float32), np.zeros(4, dtype=np.float32))
        assert self.loader is not None and self.loader.on_peaks is not None
        self.loader.on_peaks(2, peaks)
        self.assertIs(dialog.waveforms[2].peaks, peaks)
        self.assertIsNone(dialog.waveforms[1].peaks)

    def _deliver(self, index: int, duration: float) -> None:
        peaks = Peaks(duration, np.zeros(4, dtype=np.float32), np.zeros(4, dtype=np.float32))
        assert self.loader is not None and self.loader.on_peaks is not None
        self.loader.on_peaks(index, peaks)

    def test_timeline_falls_back_to_longest_peaks(self) -> None:
        dialog, _ = self._dialog(_set("song", "Vocals", "Instrumental"), loader=True)
        self._deliver(2, 6.0)
        self._deliver(0, 8.0)
        self._deliver(1, 7.0)
        self.assertEqual([w.timeline for w in dialog.waveforms], [8.0, 8.0, 8.0])
        self.assertEqual(dialog._total.get_label(), "0:08")

    def test_engine_duration_wins_over_peaks(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"), loader=True)
        engine.on_duration(9.5)
        self._deliver(0, 8.0)
        self.assertEqual([w.timeline for w in dialog.waveforms], [9.5, 9.5])

    def test_failed_engine_duration_keeps_peak_timeline(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"), loader=True)
        self._deliver(0, 8.0)
        engine.on_duration(0.0)
        self.assertEqual([w.timeline for w in dialog.waveforms], [8.0, 8.0])
        self.assertEqual(dialog._total.get_label(), "0:08")

    def test_switching_input_resets_timeline(self) -> None:
        dialog, engine = self._dialog(_set("a", "Vocals"), _set("b", "Vocals"), loader=True)
        engine.on_duration(9.5)
        self._deliver(0, 9.5)
        dialog.input_dropdown.set_selected(1)
        self._deliver(1, 3.0)
        self.assertEqual([w.timeline for w in dialog.waveforms], [3.0, 3.0])

    def test_switching_input_reloads_peaks(self) -> None:
        dialog, engine = self._dialog(
            _set("a", "Vocals"), _set("b", "Vocals", "Drums"), loader=True
        )
        dialog.input_dropdown.set_selected(1)
        loads = [c for c in engine.calls if c[0] == "peaks.load"]
        self.assertEqual(len(loads), 2)
        self.assertEqual(loads[-1][1][0], "/in/b.wav")
        self.assertEqual(len(dialog.waveforms), 3)

    def test_close_cancels_peaks_before_unload(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"), loader=True)
        engine.calls.clear()
        dialog.dialog.emit("closed")
        self.assertEqual(engine.calls, [("peaks.cancel",), ("unload",)])

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
