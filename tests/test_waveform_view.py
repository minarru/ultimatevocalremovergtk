"""Waveform widget: time mapping, column reduction, seeking and drawing."""

from __future__ import annotations

import os
import unittest
from typing import Any

import numpy as np

from core.waveform import Peaks


def _ramp() -> Peaks:
    levels = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    return Peaks(2.0, -levels, levels)


class MappingTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        from ui.widgets.waveform import seconds_to_x, x_to_seconds

        self.assertAlmostEqual(x_to_seconds(50, 200, 100.0), 25.0)
        self.assertAlmostEqual(seconds_to_x(25.0, 200, 100.0), 50.0)

    def test_clamps_outside_the_axis(self) -> None:
        from ui.widgets.waveform import seconds_to_x, x_to_seconds

        self.assertEqual(x_to_seconds(-10, 200, 100.0), 0.0)
        self.assertEqual(x_to_seconds(250, 200, 100.0), 100.0)
        self.assertEqual(seconds_to_x(500.0, 200, 100.0), 200.0)

    def test_degenerate_inputs_are_empty(self) -> None:
        from ui.widgets.waveform import column_extents, seconds_to_x, x_to_seconds

        self.assertEqual(x_to_seconds(10, 0, 100.0), 0.0)
        self.assertEqual(x_to_seconds(10, 200, 0.0), 0.0)
        self.assertEqual(seconds_to_x(10.0, 200, 0.0), 0.0)
        for width, timeline in ((0, 2.0), (100, 0.0)):
            lows, highs = column_extents(_ramp(), width, timeline)
            self.assertEqual((lows.size, highs.size), (0, 0))


class ColumnExtentsTests(unittest.TestCase):
    def test_one_bucket_per_column(self) -> None:
        from ui.widgets.waveform import column_extents

        lows, highs = column_extents(_ramp(), 4, 2.0)
        np.testing.assert_allclose(highs, [0.1, 0.2, 0.3, 0.4])
        np.testing.assert_allclose(lows, [-0.1, -0.2, -0.3, -0.4])

    def test_downsampling_keeps_extremes(self) -> None:
        from ui.widgets.waveform import column_extents

        lows, highs = column_extents(_ramp(), 2, 2.0)
        np.testing.assert_allclose(highs, [0.2, 0.4])
        np.testing.assert_allclose(lows, [-0.2, -0.4])

    def test_upsampling_repeats_buckets(self) -> None:
        from ui.widgets.waveform import column_extents

        _lows, highs = column_extents(_ramp(), 8, 2.0)
        np.testing.assert_allclose(highs, [0.1, 0.1, 0.2, 0.2, 0.3, 0.3, 0.4, 0.4])

    def test_shorter_track_stops_early(self) -> None:
        from ui.widgets.waveform import column_extents

        # A 2 s track on a 4 s axis fills only the left half of the columns.
        lows, highs = column_extents(_ramp(), 4, 4.0)
        self.assertEqual(highs.size, 2)
        np.testing.assert_allclose(highs, [0.2, 0.4])
        self.assertEqual(lows.size, 2)


def _flat(level: float, buckets: int = 10, duration: float = 2.0) -> Peaks:
    levels = np.full(buckets, level, dtype=np.float32)
    return Peaks(duration, -levels, levels)


class BarLevelsTests(unittest.TestCase):
    def test_one_bar_per_pitch(self) -> None:
        from ui.widgets.waveform import BAR_PITCH, bar_levels

        levels = bar_levels(_ramp(), 4 * BAR_PITCH, 2.0)
        np.testing.assert_allclose(levels, [0.1, 0.2, 0.3, 0.4], rtol=1e-6)

    def test_last_bar_needs_no_trailing_gap(self) -> None:
        from ui.widgets.waveform import BAR_GAP, BAR_PITCH, bar_levels

        self.assertEqual(bar_levels(_ramp(), 4 * BAR_PITCH - BAR_GAP, 2.0).size, 4)
        self.assertEqual(bar_levels(_ramp(), 4 * BAR_PITCH - BAR_GAP - 1, 2.0).size, 3)

    def test_bars_mirror_the_larger_side(self) -> None:
        from ui.widgets.waveform import BAR_PITCH, bar_levels

        peaks = Peaks(
            1.0, np.array([-0.5, -0.1], dtype=np.float32), np.array([0.2, 0.3], dtype=np.float32)
        )
        np.testing.assert_allclose(bar_levels(peaks, 2 * BAR_PITCH, 1.0), [0.5, 0.3], rtol=1e-6)

    def test_bars_sit_on_the_shared_axis(self) -> None:
        from ui.widgets.waveform import BAR_PITCH, bar_levels

        # A 2 s track on a 4 s axis fills only the left half of the bars.
        self.assertEqual(bar_levels(_ramp(), 4 * BAR_PITCH, 4.0).size, 2)

    def test_degenerate_inputs_are_empty(self) -> None:
        from ui.widgets.waveform import bar_levels

        for width, timeline in ((0, 2.0), (1, 2.0), (100, 0.0)):
            self.assertEqual(bar_levels(_ramp(), width, timeline).size, 0)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class WaveformViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def test_is_a_labelled_unfocusable_image(self) -> None:
        from unittest import mock

        from gi.repository import Gtk

        from ui.widgets.waveform import WaveformView

        # GTK has no getter for accessible properties, so spy on the setter.
        with mock.patch.object(WaveformView, "update_property") as update:
            view = WaveformView("Vocals")
        update.assert_any_call([Gtk.AccessibleProperty.LABEL], ["Vocals waveform"])
        self.assertEqual(view.get_accessible_role(), Gtk.AccessibleRole.IMG)
        self.assertFalse(view.get_focusable())

    def test_seek_at_maps_x_on_the_timeline(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        seeks: list[float] = []
        view.on_seek = seeks.append
        view.set_timeline(100.0)
        view.seek_at(50, 200)
        self.assertEqual(seeks, [25.0])

    def test_timeline_falls_back_to_own_duration(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        self.assertEqual(view.timeline, 0.0)
        view.set_peaks(_ramp())
        self.assertEqual(view.timeline, 2.0)
        view.set_timeline(10.0)
        self.assertEqual(view.timeline, 10.0)

    def _ranged(self, timeline: float, start: float, length: float) -> Any:
        from ui.widgets.waveform import WaveformView

        view = WaveformView("Song")
        view.set_timeline(timeline)
        view.set_range(start, length)
        self.seeks: list[float] = []
        self.moved: list[float] = []
        view.on_seek = self.seeks.append
        view.on_range_moved = self.moved.append
        return view

    def test_range_drag_moves_the_start(self) -> None:
        view = self._ranged(100.0, 10.0, 30.0)
        view.begin_range_drag()
        view.update_range_drag(50, 200)
        self.assertEqual(view.range_start, 35.0)
        view.end_range_drag(150, 200)
        self.assertEqual((self.moved, self.seeks), ([35.0], []))

    def test_range_drag_is_clamped_to_the_track(self) -> None:
        view = self._ranged(100.0, 10.0, 30.0)
        view.begin_range_drag()
        view.update_range_drag(1000, 200)
        self.assertEqual(view.range_start, 70.0)
        view.update_range_drag(-1000, 200)
        self.assertEqual(view.range_start, 0.0)

    def test_click_in_range_mode_seeks_within_the_range(self) -> None:
        view = self._ranged(100.0, 10.0, 30.0)
        view.begin_range_drag()
        view.update_range_drag(1, 200)
        view.end_range_drag(50, 200)
        self.assertEqual((self.seeks, self.moved), ([25.0], []))

    def test_click_outside_the_range_starts_it_there(self) -> None:
        view = self._ranged(100.0, 10.0, 30.0)
        view.begin_range_drag()
        view.end_range_drag(100, 200)
        self.assertEqual((self.seeks, self.moved), ([], [50.0]))
        self.assertEqual(view.range_start, 50.0)

    def test_click_near_the_end_keeps_the_range_on_the_track(self) -> None:
        view = self._ranged(100.0, 10.0, 30.0)
        view.begin_range_drag()
        view.end_range_drag(190, 200)
        self.assertEqual((self.seeks, self.moved), ([], [70.0]))

    def test_cursor_offers_a_grab_only_when_the_range_can_move(self) -> None:
        def cursor(view: Any) -> str | None:
            current = view.get_cursor()
            return current.get_name() if current is not None else None

        view = self._ranged(100.0, 10.0, 30.0)
        self.assertEqual(cursor(view), "grab")
        view.begin_range_drag()
        self.assertEqual(cursor(view), "grabbing")
        view.end_range_drag(50, 200)
        self.assertEqual(cursor(view), "grab")
        self.assertIsNone(cursor(self._ranged(20.0, 0.0, 30.0)))
        self.assertIsNone(cursor(self._ranged(100.0, 0.0, 0.0)))

    def test_short_track_range_cannot_move(self) -> None:
        view = self._ranged(20.0, 0.0, 30.0)
        view.begin_range_drag()
        view.update_range_drag(50, 200)
        self.assertEqual(view.range_start, 0.0)

    def test_zero_length_turns_the_range_off(self) -> None:
        view = self._ranged(100.0, 10.0, 0.0)
        self.assertEqual(view.range_length, 0.0)

    def test_seek_without_timeline_is_ignored(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        seeks: list[float] = []
        view.on_seek = seeks.append
        view.seek_at(50, 200)
        view.seek_at(50, 0)
        self.assertEqual(seeks, [])

    def test_active_toggles_accent_class(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_active(True)
        self.assertTrue(view.active)
        self.assertIn("accent", view.get_css_classes())
        view.set_active(False)
        self.assertNotIn("accent", view.get_css_classes())

    def test_rows_without_peaks_still_draw_the_playhead(self) -> None:
        import cairo

        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_timeline(10.0)
        view.set_position(5.0)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 40)
        view._draw(view, cairo.Context(surface), 200, 40)
        surface.flush()
        pixels = np.ndarray((40, 200, 4), dtype=np.uint8, buffer=surface.get_data())
        top = pixels[0, :, 3]
        # Only the 2 px playhead, centred on x = 100, reaches the top.
        self.assertEqual(np.flatnonzero(top).tolist(), [99, 100])

    def test_repeated_draws_reuse_column_extents(self) -> None:
        from unittest import mock

        import cairo

        from ui.widgets import waveform
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_peaks(_ramp())
        with mock.patch.object(
            waveform, "column_extents", wraps=waveform.column_extents
        ) as extents:
            for width, position in ((200, 0.5), (200, 1.0), (300, 1.0)):
                view.set_position(position)
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, 40)
                view._draw(view, cairo.Context(surface), width, 40)
        # The playhead moved between the first two draws; only the width change recomputes.
        self.assertEqual(extents.call_count, 2)

    def test_subpixel_position_change_skips_redraw(self) -> None:
        from unittest import mock

        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_timeline(100.0)
        view.get_width = lambda: 200  # 2 px per second once allocated
        view.queue_draw = mock.Mock()
        view.set_position(10.0)
        self.assertEqual(view.queue_draw.call_count, 1)
        view.set_position(10.2)  # still pixel 20
        self.assertEqual(view.queue_draw.call_count, 1)
        self.assertEqual(view.position, 10.2)
        view.set_position(10.6)  # pixel 21
        self.assertEqual(view.queue_draw.call_count, 2)

    def _render(self, view: Any, width: int = 30, height: int = 40) -> Any:
        import cairo

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        view._draw(view, cairo.Context(surface), width, height)
        surface.flush()
        return np.ndarray((height, width, 4), dtype=np.uint8, buffer=surface.get_data())

    def test_bars_are_separated_by_gaps(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_peaks(_flat(0.5))
        view.set_position(2.0)  # playhead parked at the right edge
        alpha = self._render(view)[20, :, 3]
        self.assertTrue(alpha[0] and alpha[1] and alpha[3] and alpha[4])
        self.assertEqual((int(alpha[2]), int(alpha[5])), (0, 0))

    def test_bars_are_mirrored_about_the_midline(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_peaks(_flat(0.5))
        view.set_position(2.0)
        column = self._render(view)[:, 0, 3]
        np.testing.assert_array_equal(column[:20], column[20:][::-1])
        self.assertGreater(int(column[12]), 0)  # half of the 20 px half-height
        self.assertEqual(int(column[5]), 0)

    def test_silent_bars_stay_visible(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_peaks(_flat(0.0))
        view.set_position(2.0)
        self.assertGreater(int(self._render(view)[20, 0, 3]), 0)

    def test_range_dims_bars_outside_and_handles_the_edges(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_peaks(_flat(0.5, buckets=90, duration=90.0))
        view.set_timeline(90.0)
        view.set_range(30.0, 30.0)
        view.set_active(True)
        view.set_position(0.0)
        pixels = self._render(view, 90, 40)
        outside = int(pixels[20, 4, 3])
        inside = int(pixels[20, 31, 3])
        self.assertGreater(inside, 0)
        self.assertLess(outside, inside * 0.7)
        # The selection is the bright region, so the top of it stays clear.
        self.assertEqual(int(pixels[0, 45, 3]), 0)
        self.assertGreater(int(pixels[0, 30, 3]), 0)
        self.assertGreater(int(pixels[0, 59, 3]), 0)

    def test_played_bars_are_stronger_than_unplayed(self) -> None:
        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        view.set_peaks(_flat(0.5))
        view.set_active(True)
        view.set_position(1.0)  # playhead at x = 15
        alpha = self._render(view)[20, :, 3]
        self.assertGreater(int(alpha[0]), int(alpha[24]))
        self.assertGreater(int(alpha[24]), 0)

    def test_draws_peaks_and_placeholder(self) -> None:
        import cairo

        from ui.widgets.waveform import WaveformView

        view = WaveformView()
        for peaks in (None, _ramp()):
            view.set_peaks(peaks)
            view.set_position(1.0)
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 40)
            view._draw(view, cairo.Context(surface), 200, 40)
            surface.flush()
            pixels = np.ndarray((40, 200, 4), dtype=np.uint8, buffer=surface.get_data())
            self.assertGreater(int(pixels[20, :, 3].max()), 0)  # something on the midline


if __name__ == "__main__":
    unittest.main()
