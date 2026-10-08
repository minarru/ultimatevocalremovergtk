"""The shared compare track list driven through a fake engine."""

from __future__ import annotations

import os
import unittest
from typing import TYPE_CHECKING, Any, Callable, Sequence

import numpy as np

from core.listening import REFERENCE_LABEL, Track
from core.waveform import Peaks
from tests.playback_fakes import FakeEngine, FakeLoader, comparison_set

if TYPE_CHECKING:
    from gi.repository import Gtk

    from ui.playback.view import CompareView


def _buttons_in(widget: Gtk.Widget) -> list[Gtk.Widget]:
    from gi.repository import Gtk

    from tests.gtk_layout_helpers import iter_descendants

    return [w for w in iter_descendants(widget) if isinstance(w, Gtk.Button)]


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class CompareViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def _view(
        self,
        *,
        loader: bool = False,
        row_suffix: Callable[[int, Track], Any] | None = None,
        engine: FakeEngine | None = None,
    ) -> tuple[CompareView, FakeEngine]:
        from ui.playback.view import CompareView

        engine = engine or FakeEngine()
        self.loader = FakeLoader(engine.calls) if loader else None
        view = CompareView(engine, peaks=self.loader, row_suffix=row_suffix)
        return view, engine

    def _shown(self, *labels: str, loader: bool = False) -> tuple[CompareView, FakeEngine]:
        view, engine = self._view(loader=loader)
        view.show_tracks(comparison_set("song", *labels).tracks)
        return view, engine

    def _deliver(self, index: int, duration: float) -> None:
        peaks = Peaks(duration, np.zeros(4, dtype=np.float32), np.zeros(4, dtype=np.float32))
        assert self.loader is not None and self.loader.on_peaks is not None
        self.loader.on_peaks(index, peaks)

    def test_loads_tracks_with_first_output_selected(self) -> None:
        view, engine = self._shown("Vocals", "Instrumental")
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
            [t.get_label() for t in view.titles], [REFERENCE_LABEL, "Vocals", "Instrumental"]
        )

    def test_selected_overrides_the_default_track(self) -> None:
        view, engine = self._view()
        view.show_tracks(comparison_set("song", "Vocals", "Instrumental").tracks, selected=2)
        self.assertEqual(engine.calls[-1][2], 2)
        self.assertEqual([c.get_active() for c in view.checks], [False, False, True])

    def test_row_suffix_is_added_and_rebuilt(self) -> None:
        from gi.repository import Gtk

        made: list[int] = []

        def suffix(index: int, _track: Track) -> Gtk.Widget | None:
            made.append(index)
            return Gtk.Button(label="Keep") if index else None

        view, _ = self._view(row_suffix=suffix)
        tracks = comparison_set("song", "Vocals").tracks
        view.show_tracks(tracks)
        view.show_tracks(tracks)
        self.assertEqual(made, [0, 1, 0, 1])
        self.assertEqual(len(_buttons_in(view.rows[0])), 0)
        self.assertEqual(len(_buttons_in(view.rows[1])), 1)

    def test_late_peaks_after_shutdown_are_ignored(self) -> None:
        view, _ = self._shown("Vocals", loader=True)
        view.shutdown()
        self._deliver(0, 8.0)
        self.assertIsNone(view.waveforms[0].peaks)

    def test_empty_tracks_leave_transport_insensitive(self) -> None:
        view, engine = self._view()
        view.show_tracks(())
        self.assertEqual(view.rows, [])
        self.assertFalse(view.play_button.get_sensitive())
        self.assertNotIn("load", [c[0] for c in engine.calls])

    def test_skip_buttons_seek_five_seconds(self) -> None:
        view, engine = self._shown("Vocals")
        engine._position = 10.0
        view.forward_button.emit("clicked")
        self.assertEqual(engine.calls[-1], ("seek", 15.0))
        view.back_button.emit("clicked")
        self.assertEqual(engine.calls[-1], ("seek", 10.0))

    def test_audible_row_is_highlighted(self) -> None:
        from gi.repository import Gdk

        view, _ = self._shown("Vocals", "Instrumental")
        active = [r.has_css_class("uvr-compare-active") for r in view.rows]
        self.assertEqual(active, [False, True, False])
        view.handle_key(Gdk.KEY_3)
        active = [r.has_css_class("uvr-compare-active") for r in view.rows]
        self.assertEqual(active, [False, False, True])

    def test_rows_show_their_number_key(self) -> None:
        view, _ = self._shown(*(f"Stem {n}" for n in range(1, 10)))
        self.assertEqual(len(view.rows), 10)
        # Only 1–9 have keys; the tenth row gets no hint.
        self.assertEqual([h.get_label() for h in view.key_hints], [str(n) for n in range(1, 10)])

    def test_row_activation_selects_track(self) -> None:
        view, engine = self._shown("Vocals", "Instrumental")
        # What GTK emits when a row is clicked or activated by keyboard; calling
        # ``activate()`` on a row of an unpresented dialog trips a focus assertion.
        view.track_list.emit("row-activated", view.rows[2])
        self.assertEqual(engine.calls[-1], ("select", 2))

    def test_number_keys_select_and_space_toggles(self) -> None:
        from gi.repository import Gdk

        view, engine = self._shown("Vocals", "Instrumental")
        self.assertTrue(view.handle_key(Gdk.KEY_1))
        self.assertEqual(engine.calls[-1], ("select", 0))
        self.assertTrue(view.handle_key(Gdk.KEY_space))
        self.assertEqual(engine.calls[-1], ("play",))
        self.assertFalse(view.handle_key(Gdk.KEY_9))

    def test_arrow_keys_seek_five_seconds(self) -> None:
        from gi.repository import Gdk

        view, engine = self._shown("Vocals")
        engine._position = 10.0
        view.handle_key(Gdk.KEY_Right)
        self.assertEqual(engine.calls[-1], ("seek", 15.0))
        view.handle_key(Gdk.KEY_Left)
        self.assertEqual(engine.calls[-1], ("seek", 10.0))

    def test_failed_track_row_is_insensitive(self) -> None:
        view, engine = self._shown("Vocals", "Instrumental")
        engine.on_track_error(2, "Could not determine type of stream")
        self.assertFalse(view.rows[2].get_sensitive())
        self.assertIn("Could not determine", view.rows[2].get_tooltip_text() or "")

    def test_radio_follows_engine_when_default_track_fails(self) -> None:
        class FailingVocalsEngine(FakeEngine):
            def load(
                self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0
            ) -> None:
                super().load(tracks, selected=selected, position=position)
                self.on_track_error(1, "gone")
                self._selected = 0

        view, engine = self._view(engine=FailingVocalsEngine())
        view.show_tracks(comparison_set("song", "Vocals", "Instrumental").tracks)
        self.assertEqual([c.get_active() for c in view.checks], [True, False, False])
        self.assertFalse(view.rows[1].get_sensitive())
        self.assertNotIn(("select", 0), engine.calls)
        self.assertEqual([w.active for w in view.waveforms], [True, False, False])

    def test_engine_error_disables_transport_and_reports(self) -> None:
        view, engine = self._shown("Vocals")
        errors: list[str] = []
        view.on_error = errors.append
        engine.on_error("No audio sink")
        self.assertFalse(view.play_button.get_sensitive())
        self.assertEqual(errors, ["Couldn't start playback. No audio sink"])

    def test_duration_and_position_update_labels_and_waveforms(self) -> None:
        view, engine = self._shown("Vocals")
        engine.on_duration(225.0)
        engine.on_position(83.0)
        self.assertEqual(view.total_label.get_label(), "3:45")
        self.assertEqual(view.elapsed_label.get_label(), "1:23")
        self.assertEqual([w.timeline for w in view.waveforms], [225.0, 225.0])
        self.assertEqual([w.position for w in view.waveforms], [83.0, 83.0])

    def test_seek_slider_is_gone(self) -> None:
        view, _ = self._shown("Vocals")
        self.assertFalse(hasattr(view, "seek_scale"))

    def test_waveforms_are_named_after_their_tracks(self) -> None:
        from unittest import mock

        from gi.repository import Gtk

        from ui.widgets.waveform import WaveformView

        with mock.patch.object(WaveformView, "update_property") as update:
            self._shown("Vocals")
        labels = [
            c.args[1][0]
            for c in update.call_args_list
            if c.args[0] == [Gtk.AccessibleProperty.LABEL]
        ]
        self.assertEqual(labels, [f"{REFERENCE_LABEL} waveform", "Vocals waveform"])

    def test_one_waveform_per_row(self) -> None:
        view, _ = self._shown("Vocals", "Instrumental")
        self.assertEqual(len(view.waveforms), len(view.rows))

    def test_waveform_seek_seeks_without_switching(self) -> None:
        view, engine = self._shown("Vocals", "Instrumental")
        engine.calls.clear()
        view.waveforms[0].set_timeline(100.0)
        view.waveforms[0].seek_at(50, 200)
        self.assertEqual(engine.calls, [("seek", 25.0)])

    def test_active_waveform_follows_selection(self) -> None:
        from gi.repository import Gdk

        view, _ = self._shown("Vocals", "Instrumental")
        self.assertEqual([w.active for w in view.waveforms], [False, True, False])
        view.handle_key(Gdk.KEY_3)
        self.assertEqual([w.active for w in view.waveforms], [False, False, True])

    def test_peaks_load_for_the_tracks_audible_first(self) -> None:
        view, engine = self._shown("Vocals", "Instrumental", loader=True)
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
        self.assertIs(view.waveforms[2].peaks, peaks)
        self.assertIsNone(view.waveforms[1].peaks)

    def test_timeline_falls_back_to_longest_peaks(self) -> None:
        view, _ = self._shown("Vocals", "Instrumental", loader=True)
        self._deliver(2, 6.0)
        self._deliver(0, 8.0)
        self._deliver(1, 7.0)
        self.assertEqual([w.timeline for w in view.waveforms], [8.0, 8.0, 8.0])
        self.assertEqual(view.total_label.get_label(), "0:08")

    def test_engine_duration_wins_over_peaks(self) -> None:
        view, engine = self._shown("Vocals", loader=True)
        engine.on_duration(9.5)
        self._deliver(0, 8.0)
        self.assertEqual([w.timeline for w in view.waveforms], [9.5, 9.5])

    def test_failed_engine_duration_keeps_peak_timeline(self) -> None:
        view, engine = self._shown("Vocals", loader=True)
        self._deliver(0, 8.0)
        engine.on_duration(0.0)
        self.assertEqual([w.timeline for w in view.waveforms], [8.0, 8.0])
        self.assertEqual(view.total_label.get_label(), "0:08")

    def test_show_tracks_again_resets_timeline(self) -> None:
        view, engine = self._shown("Vocals", loader=True)
        engine.on_duration(9.5)
        self._deliver(0, 9.5)
        view.show_tracks(comparison_set("b", "Vocals").tracks)
        self._deliver(1, 3.0)
        self.assertEqual([w.timeline for w in view.waveforms], [3.0, 3.0])

    def test_show_tracks_again_reloads_peaks(self) -> None:
        view, engine = self._shown("Vocals", loader=True)
        view.show_tracks(comparison_set("b", "Vocals", "Drums").tracks)
        loads = [c for c in engine.calls if c[0] == "peaks.load"]
        self.assertEqual(len(loads), 2)
        self.assertEqual(loads[-1][1][0], "/in/b.wav")
        self.assertEqual(len(view.waveforms), 3)

    def test_shutdown_cancels_peaks_before_unload(self) -> None:
        view, engine = self._shown("Vocals", loader=True)
        engine.calls.clear()
        view.shutdown()
        self.assertEqual(engine.calls, [("peaks.cancel",), ("unload",)])

    def test_play_button_icon_follows_state(self) -> None:
        view, engine = self._shown("Vocals")
        engine.play()
        self.assertEqual(view.play_button.get_icon_name(), "media-playback-pause-symbolic")
        engine.pause()
        self.assertEqual(view.play_button.get_icon_name(), "media-playback-start-symbolic")


if __name__ == "__main__":
    unittest.main()
