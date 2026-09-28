"""GStreamer playback engine: lockstep mixing, instant selection, error isolation."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from typing import Any, Callable

import numpy as np
import soundfile as sf

from core.listening import Track
from ui.playback.engine import playback_unavailable_reason

_REASON = playback_unavailable_reason()


def _spin_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    from gi.repository import GLib

    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _fakesink() -> Any:
    from gi.repository import Gst

    sink = Gst.ElementFactory.make("fakesink")
    assert sink is not None
    sink.set_property("sync", True)
    return sink


def _tone(path: str, seconds: float, rate: int = 44100, channels: int = 1) -> None:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False, dtype=np.float32)
    mono = 0.2 * np.sin(2 * np.pi * 440 * t)
    data = mono if channels == 1 else np.stack([mono] * channels, axis=1)
    sf.write(path, data, rate)


@unittest.skipIf(_REASON is not None, f"GStreamer playback unavailable: {_REASON}")
class PlaybackEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        from ui.playback.engine import PlaybackEngine

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.a = os.path.join(self.dir, "a.wav")
        self.b = os.path.join(self.dir, "b.wav")
        _tone(self.a, 1.0)
        _tone(self.b, 2.0)
        self.engine = PlaybackEngine(sink_factory=_fakesink)
        self.addCleanup(self.engine.unload)
        self.durations: list[float] = []
        self.positions: list[float] = []
        self.states: list[bool] = []
        self.track_errors: list[tuple[int, str]] = []
        self.errors: list[str] = []
        self.engine.on_duration = self.durations.append
        self.engine.on_position = self.positions.append
        self.engine.on_state = self.states.append
        self.engine.on_track_error = lambda i, m: self.track_errors.append((i, m))
        self.engine.on_error = self.errors.append

    def _load(self, *paths: str, selected: int = 0, position: float = 0.0) -> None:
        tracks = [Track(os.path.basename(p), p) for p in paths]
        self.engine.load(tracks, selected=selected, position=position)
        self.assertTrue(_spin_until(lambda: bool(self.durations)), "no duration reported")

    def test_duration_is_longest_track(self) -> None:
        self._load(self.a, self.b)
        self.assertAlmostEqual(self.durations[-1], 2.0, delta=0.05)

    def test_play_advances_position_and_pause_reports_state(self) -> None:
        self._load(self.a, self.b)
        self.engine.play()
        self.assertTrue(_spin_until(lambda: self.engine.position > 0.2))
        self.engine.pause()
        self.assertEqual(self.states, [True, False])
        self.assertFalse(self.engine.playing)

    def test_seek_moves_the_shared_position(self) -> None:
        self._load(self.a, self.b)
        self.engine.seek(1.5)
        self.assertTrue(_spin_until(lambda: abs(self.engine.position - 1.5) < 0.05))

    def test_seek_before_preroll_is_applied(self) -> None:
        tracks = [Track("a", self.a), Track("b", self.b)]
        self.engine.load(tracks, selected=0, position=1.2)
        self.assertTrue(_spin_until(lambda: abs(self.engine.position - 1.2) < 0.05))

    def test_select_sets_exactly_one_audible_branch_without_state_change(self) -> None:
        self._load(self.a, self.b)
        self.engine.play()
        _spin_until(lambda: self.engine.position > 0.1)
        self.engine.select(1)
        self.assertEqual(self.engine.selected, 1)
        self.assertEqual(self.engine._volumes_for_test(), {0: 0.0, 1: 1.0})
        self.assertEqual(self.states, [True])

    def test_missing_file_reports_track_error_and_others_play(self) -> None:
        missing = os.path.join(self.dir, "gone.wav")
        self._load(self.a, missing, self.b)
        self.assertEqual([i for i, _ in self.track_errors], [1])
        self.assertAlmostEqual(self.durations[-1], 2.0, delta=0.05)
        self.engine.play()
        self.assertTrue(_spin_until(lambda: self.engine.position > 0.1))
        self.assertEqual(self.errors, [])

    def test_corrupt_file_reports_track_error(self) -> None:
        bad = os.path.join(self.dir, "bad.wav")
        with open(bad, "wb") as handle:
            handle.write(b"RIFFnot-really-audio" * 8)
        self._load(bad, self.a)
        self.assertEqual([i for i, _ in self.track_errors], [0])

    def test_select_of_failed_track_is_ignored(self) -> None:
        missing = os.path.join(self.dir, "gone.wav")
        self._load(self.a, missing)
        self.engine.select(1)
        self.assertEqual(self.engine.selected, 0)

    def test_no_playable_tracks_reports_error(self) -> None:
        self.engine.load([Track("x", os.path.join(self.dir, "none.wav"))])
        self.assertTrue(_spin_until(lambda: bool(self.errors)))
        self.assertFalse(self.engine.loaded)

    def test_end_of_stream_pauses_and_play_restarts(self) -> None:
        self._load(self.a)
        self.engine.seek(0.9)
        self.engine.play()
        self.assertTrue(_spin_until(lambda: self.states[-1:] == [False], timeout=3.0))
        self.engine.play()
        self.assertTrue(_spin_until(lambda: 0.0 <= self.engine.position < 0.5))

    def test_different_rates_and_channels_mix(self) -> None:
        stereo48 = os.path.join(self.dir, "stereo.flac")
        _tone(stereo48, 1.5, rate=48000, channels=2)
        self._load(self.a, stereo48)
        self.assertAlmostEqual(self.durations[-1], 1.5, delta=0.05)
        self.assertEqual(self.track_errors, [])

    def test_unicode_path_with_spaces_plays(self) -> None:
        odd = os.path.join(self.dir, "Björk – Jóga (Vocals).wav")
        _tone(odd, 0.5)
        self._load(odd)
        self.assertEqual(self.track_errors, [])

    def test_unload_reaches_null_and_is_idempotent(self) -> None:
        self._load(self.a)
        self.engine.unload()
        self.engine.unload()
        self.assertFalse(self.engine.loaded)


class AvailabilityTests(unittest.TestCase):
    def test_import_does_not_load_gstreamer(self) -> None:
        import subprocess
        import sys

        code = "import sys, ui.playback.engine; print('gi.repository.Gst' in sys.modules)"
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout.strip()
        self.assertEqual(out, "False")

    @unittest.skipIf(_REASON is not None, f"GStreamer playback unavailable: {_REASON}")
    def test_engine_initialises_gstreamer_itself(self) -> None:
        import subprocess
        import sys

        code = (
            "import os, tempfile, numpy as np, soundfile as sf\n"
            "from core.listening import Track\n"
            "from ui.playback.engine import PlaybackEngine\n"
            "d = tempfile.mkdtemp(); p = os.path.join(d, 't.wav')\n"
            "sf.write(p, np.zeros(4410, dtype='float32'), 44100)\n"
            "def sink():\n"
            "    from gi.repository import Gst\n"
            "    return Gst.ElementFactory.make('fakesink')\n"
            "e = PlaybackEngine(sink_factory=sink); errs = []\n"
            "e.on_track_error = lambda i, m: errs.append(m); e.on_error = errs.append\n"
            "e.load([Track('t', p)]); print(e.loaded, errs); e.unload()\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout.strip()
        self.assertEqual(out, "True []")

    def test_reason_is_cached(self) -> None:
        self.assertIs(playback_unavailable_reason(), playback_unavailable_reason())


if __name__ == "__main__":
    unittest.main()
