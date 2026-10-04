"""Waveform loader: ordering, caching, cancellation and stale-result dropping."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from typing import Any, Callable
from unittest import mock

import numpy as np

from core.audio_decode import AudioDecodeError
from core.waveform import Peaks, WaveformCancelled
from ui.playback.session import ListeningSession
from ui.playback.waveforms import PeakCache, WaveformLoader


def _peaks(level: float) -> Peaks:
    return Peaks(1.0, np.full(4, -level, dtype=np.float32), np.full(4, level, dtype=np.float32))


class _Queue:
    """Stands in for ``idle_on_main``: runs callbacks only when flushed."""

    def __init__(self) -> None:
        self.pending: list[tuple[Callable[..., None], tuple[Any, ...]]] = []

    def __call__(self, func: Callable[..., None], *args: Any) -> None:
        self.pending.append((func, args))

    def flush(self) -> None:
        pending, self.pending = self.pending, []
        for func, args in pending:
            func(*args)


def _settle(loader: WaveformLoader) -> None:
    thread = loader._thread
    if thread is not None:
        thread.join(5)


class PeakCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "a.wav")
        with open(self.path, "wb") as handle:
            handle.write(b"x")

    def test_put_then_get(self) -> None:
        cache = PeakCache()
        peaks = _peaks(0.5)
        cache.put(self.path, peaks)
        self.assertIs(cache.get(self.path), peaks)
        self.assertEqual(len(cache), 1)

    def test_changed_file_is_a_miss(self) -> None:
        cache = PeakCache()
        cache.put(self.path, _peaks(0.5))
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        self.assertIsNone(cache.get(self.path))

    def test_missing_file_is_a_cache_miss(self) -> None:
        cache = PeakCache()
        missing = self.path + ".gone"
        cache.put(missing, _peaks(0.5))
        self.assertIsNone(cache.get(missing))
        self.assertEqual(len(cache), 0)

    def test_session_clear_clears_cache(self) -> None:
        session = ListeningSession()
        session.peak_cache.put(self.path, _peaks(0.5))
        session.clear()
        self.assertEqual(len(session.peak_cache), 0)


class WaveformLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = []
        for name in ("orig.wav", "vocals.wav", "inst.wav"):
            path = os.path.join(tmp.name, name)
            with open(path, "wb") as handle:
                handle.write(name.encode())
            self.paths.append(path)
        self.queue = _Queue()
        self.computed: list[str] = []
        self.delivered: list[tuple[int, Peaks | None]] = []

    def _compute(self, path: str, *, cancel: threading.Event | None = None) -> Peaks:
        self.computed.append(path)
        return _peaks(0.1 * (self.paths.index(path) + 1))

    def _loader(self, compute: Callable[..., Peaks] | None = None) -> WaveformLoader:
        return WaveformLoader(PeakCache(), compute=compute or self._compute, dispatch=self.queue)

    def _on_peaks(self, index: int, peaks: Peaks | None) -> None:
        self.delivered.append((index, peaks))

    def test_first_index_is_computed_first(self) -> None:
        loader = self._loader()
        loader.load(self.paths, 2, self._on_peaks)
        _settle(loader)
        self.queue.flush()
        self.assertEqual(self.computed, [self.paths[2], self.paths[0], self.paths[1]])
        self.assertEqual([i for i, _ in self.delivered], [2, 0, 1])

    def test_results_are_cached_and_reused(self) -> None:
        loader = self._loader()
        loader.load(self.paths, 1, self._on_peaks)
        _settle(loader)
        self.queue.flush()
        self.computed.clear()
        self.delivered.clear()
        loader.load(self.paths, 1, self._on_peaks)
        _settle(loader)
        self.queue.flush()
        self.assertEqual(self.computed, [])
        self.assertEqual(sorted(i for i, _ in self.delivered), [0, 1, 2])

    def test_cache_hits_still_arrive_through_dispatch(self) -> None:
        loader = self._loader()
        loader.cache.put(self.paths[0], _peaks(0.9))
        loader.load(self.paths[:1], 0, self._on_peaks)
        self.assertEqual(self.delivered, [])  # nothing runs off the main loop
        self.queue.flush()
        self.assertEqual(len(self.delivered), 1)

    def test_cancel_suppresses_delivery(self) -> None:
        gate = threading.Event()

        def blocking(path: str, *, cancel: threading.Event | None = None) -> Peaks:
            gate.wait(5)
            if cancel is not None and cancel.is_set():
                raise WaveformCancelled
            return _peaks(0.5)

        loader = self._loader(blocking)
        loader.load(self.paths, 0, self._on_peaks)
        loader.cancel()
        gate.set()
        _settle(loader)
        self.queue.flush()
        self.assertEqual(self.delivered, [])

    def test_stale_generation_is_dropped(self) -> None:
        loader = self._loader()
        loader.load(self.paths[:1], 0, self._on_peaks)
        _settle(loader)
        stale: list[int] = []
        loader.load(self.paths[1:], 0, lambda i, _p: stale.append(i))
        _settle(loader)
        self.queue.flush()
        self.assertEqual(self.delivered, [])  # the first load's result arrived too late
        self.assertEqual(sorted(stale), [0, 1])

    def test_compute_error_delivers_none_and_logs(self) -> None:
        def failing(path: str, *, cancel: threading.Event | None = None) -> Peaks:
            if path == self.paths[1]:
                raise AudioDecodeError("Cannot decode audio: bad")
            return _peaks(0.5)

        loader = self._loader(failing)
        with mock.patch("ui.playback.waveforms.log_event") as log:
            loader.load(self.paths, 0, self._on_peaks)
            _settle(loader)
        self.queue.flush()
        results = dict(self.delivered)
        self.assertIsNone(results[1])
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[2])
        log.assert_called_once()
        self.assertEqual(log.call_args.args[:2], ("playback", "waveform_error"))


if __name__ == "__main__":
    unittest.main()
