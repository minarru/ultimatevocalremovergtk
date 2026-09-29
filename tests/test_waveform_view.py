"""Waveform widget: time mapping, column reduction, seeking and drawing."""

from __future__ import annotations

import os
import unittest

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


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class WaveformViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
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
        self.assertEqual(np.flatnonzero(top).tolist(), [100])  # only the playhead reaches the top

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
