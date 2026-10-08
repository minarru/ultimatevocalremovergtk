"""Playback kept inside a range by a wrapper around the engine. No GTK."""

from __future__ import annotations

import unittest

from tests.playback_fakes import FakeEngine, comparison_set
from ui.playback.range_loop import RangeLoop


class EmittingEngine(FakeEngine):
    """Like the GStreamer engine: a seek is clamped to the track and reported at once."""

    def seek(self, seconds: float) -> None:
        target = max(0.0, seconds)
        if self._duration > 0:
            target = min(target, self._duration)
        super().seek(target)
        self.on_position(target)


class RangeLoopTests(unittest.TestCase):
    def _loop(self, start: float = 10.0, length: float = 30.0) -> tuple[RangeLoop, FakeEngine]:
        engine = FakeEngine()
        loop = RangeLoop(engine)
        loop.set_range(start, length)
        self.positions: list[float] = []
        loop.on_position = self.positions.append
        return loop, engine

    def test_seeks_are_clamped_to_the_range(self) -> None:
        loop, engine = self._loop()
        loop.seek(5.0)
        loop.seek(100.0)
        seeks = [c for c in engine.calls if c[0] == "seek"]
        self.assertEqual(seeks, [("seek", 10.0), ("seek", 40.0)])

    def test_load_position_is_clamped(self) -> None:
        loop, engine = self._loop()
        loop.load(comparison_set("song").tracks, selected=0, position=0.0)
        self.assertEqual(engine.calls[-1][3], 10.0)

    def test_passing_the_end_loops_to_the_start(self) -> None:
        loop, engine = self._loop()
        loop.play()
        engine.on_position(40.02)
        self.assertEqual(engine.calls[-1], ("seek", 10.0))
        self.assertNotIn(40.02, self.positions)

    def test_end_of_stream_with_unknown_duration_keeps_looping(self) -> None:
        loop, engine = self._loop()
        engine._duration = 0.0
        loop.play()
        engine._playing = False
        engine.on_state(False)
        engine.on_position(0.0)
        self.assertEqual(engine.calls[-2:], [("seek", 10.0), ("play",)])

    def test_end_of_file_inside_the_range_keeps_looping(self) -> None:
        loop, engine = self._loop()
        engine._duration = 35.0
        loop.play()
        engine._playing = False
        engine.on_state(False)  # end of stream: not a pause through the loop
        engine.on_position(35.0)
        # 10 + 30 runs past 35, so the window slides back and the full length still fits.
        self.assertEqual(engine.calls[-2:], [("seek", 5.0), ("play",)])

    def test_user_pause_at_the_end_does_not_resume(self) -> None:
        loop, engine = self._loop()
        loop.play()
        loop.pause()
        engine.on_position(40.0)
        self.assertEqual(engine.calls[-1], ("seek", 10.0))

    def test_playing_before_the_start_seeks_back_in(self) -> None:
        loop, engine = self._loop()
        loop.play()
        engine.on_position(2.0)
        self.assertEqual(engine.calls[-1], ("seek", 10.0))
        self.assertNotIn(2.0, self.positions)

    def test_without_a_range_everything_passes_through(self) -> None:
        loop, engine = self._loop(length=0.0)
        loop.seek(5.0)
        engine.on_position(99.0)
        self.assertEqual((engine.calls[-1], self.positions), (("seek", 5.0), [99.0]))

    def test_range_end_is_capped_at_the_track_length(self) -> None:
        loop, engine = self._loop(start=0.0)
        engine._duration = 20.0
        self.assertEqual(loop.range_end, 20.0)

    def test_load_position_ignores_the_previous_track_length(self) -> None:
        # Switching inputs: the engine still reports the old, shorter track.
        loop, engine = self._loop(start=240.0)
        engine._duration = 180.0
        loop.load(comparison_set("song").tracks, selected=0, position=240.0)
        self.assertEqual(engine.calls[-1][3], 240.0)

    def test_start_past_the_end_of_the_track_does_not_recurse(self) -> None:
        engine = EmittingEngine()
        engine._duration = 20.0
        loop = RangeLoop(engine)
        positions: list[float] = []
        loop.on_position = positions.append
        loop.set_range(25.0, 30.0)
        loop.play()
        engine.on_position(5.0)
        self.assertLess(len([c for c in engine.calls if c[0] == "seek"]), 3)
        self.assertEqual(loop.range_start, 0.0)

    def test_engine_callbacks_reach_the_listener(self) -> None:
        loop, _engine = self._loop()
        states: list[bool] = []
        loop.on_state = states.append
        loop.play()
        self.assertEqual(states, [True])
        self.assertTrue(loop.playing)


if __name__ == "__main__":
    unittest.main()
