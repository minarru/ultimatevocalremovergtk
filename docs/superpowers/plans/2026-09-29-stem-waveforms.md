# Per-Stem Waveforms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw each track's waveform in its row of the "Compare stems" dialog, on one shared time axis with a shared playhead, and let clicking or dragging a waveform seek (replacing the seek slider).

**Architecture:** A pure `core/waveform.py` reduces an audio file to fixed-resolution min/max peaks (streamed through SoundFile, falling back to `core.audio_decode.load_audio`). `ui/playback/waveforms.py` computes peaks on one daemon thread per dialog, caches them in a `PeakCache` owned by `ListeningSession`, and delivers them to the main loop with a generation check. `ui/widgets/waveform.py` is a cairo `Gtk.DrawingArea` that draws the peaks against the set's longest duration and turns clicks and drags into seeks. `CompareDialog` builds one waveform per row and routes engine position/duration to every waveform.

**Tech Stack:** Python 3.12+, numpy, soundfile, PyGObject GTK 4 / libadwaita, pycairo, Blueprint, stdlib `unittest`, basedpyright, ruff.

**Spec:** [docs/superpowers/specs/2026-09-28-stem-comparison-playback-design.md](../specs/2026-09-28-stem-comparison-playback-design.md), section "Addendum: per-stem waveforms". The plan implements that addendum; the rest of the spec is already built on this branch.

## Global Constraints

- Backend code (`core/`) must not import GTK, GStreamer or anything under `ui/`. `core/waveform.py` imports numpy and soundfile lazily (inside functions), with numpy types under `TYPE_CHECKING`.
- Amplitude is never normalised: peaks are raw sample values clipped to [-1, 1], and every row is scaled so that ±1.0 reaches the row's top and bottom edges.
- Every waveform's x axis spans the set's longest duration (the engine's `on_duration`), falling back to the track's own duration until that is known.
- A waveform click or drag seeks via `engine.seek` and never switches the audible track. Track switching stays on the radio button, row activation and `1`–`9`.
- Worker-thread results reach GTK only through `ui.dispatch.idle_on_main` (injected as `dispatch`), and are dropped when their generation is no longer current.
- Colours come from `widget.get_color()`; the audible row's waveform carries libadwaita's `accent` style class. No `StyleManager.get_accent_color_rgba` (libadwaita 1.5 on Ubuntu 24.04 lacks it).
- Blueprint sources live in `resources/ui/*.blp`; rebuild with `./resources/compile_resources.sh`, lint with `blueprint-compiler lint`, verify with `./resources/compile_resources.sh --check`. Commit `ui/data/uvr.gresource` with the `.blp` (no generated `.ui` is tracked).
- Widget state through `ui/widget_state.py` if any is attached to GTK objects; no `row._uvr_x = …`. Never call `widget.destroy()` in tests.
- GTK tests use `@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), …)` and `gi.require_version` + `Adw.init()` in `setUpClass`. Non-GTK tests must not need a display.
- Run GTK tests with the isolated Xvfb flow from `docs/environment.md`:
  `env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m unittest <modules> -v`
- User-facing copy: sentence case. The footer hint stays exactly "Space play · 1–9 switch · ← → 5 s". The reference caption stays "Reference".
- Diagnostics via `core.debug_log.log_event("playback", "waveform_error", level="warning", path=…, error=…)`; never log per-block or per-tick events.
- Format every touched Python file with `.venv/bin/ruff format <file>` and check with `.venv/bin/ruff check <file>`. Before the final commit, run the full project `.venv/bin/python -m basedpyright`.
- Search with `rg`. Stage files explicitly by path; never `git add -A`, `git stash`, `git reset --hard`, `git checkout -- .` or `git clean`. The plan file is under an ignored directory: stage it with `git add -f`.
- Deviation from the spec, recorded here: the dialog always builds a `WaveformView` per row, even without a peak loader (it then shows the placeholder line). Without it, removing the slider would leave no mouse seeking. The spec said "With `None` no waveforms are built".

## Review Focus

1. **Buckets that straddle SoundFile block boundaries**: a long file is read in 65 536-frame blocks, and a bucket's min/max must merge across blocks rather than being overwritten by the second block. Pinned by `test_streamed_blocks_match_whole_file_reduction` in Task 1.
2. **A track shorter than the set** (sample-mode clip, trimmed output): its waveform must end at its own length on the shared axis, not stretch to the full width. Pinned by `test_shorter_track_stops_early` in Task 3.
3. **Formats SoundFile can't read** (`.m4a`, `.aac`, mono or multichannel): the FFmpeg fallback returns `(samples,)` for mono and `(channels, samples)` otherwise, and both must reduce correctly. Pinned by `test_fallback_mono_array_reduces` in Task 1.
4. **An output file deleted or replaced after the run**: `PeakCache.get` must not raise on a missing file, and a failed compute must deliver `None` (placeholder) without breaking the other rows. Pinned by `test_missing_file_is_a_cache_miss` and `test_compute_error_delivers_none_and_logs` in Task 2.
5. **Zero width or unknown duration at first draw** (widget not yet allocated, engine duration query failed): drawing and seeking must not divide by zero or raise. Pinned by `test_degenerate_inputs_are_empty` in Task 3 and `test_seek_without_timeline_is_ignored` in Task 3.

---

### Task 1: Core peak extraction

**Files:**
- Create: `core/waveform.py`
- Test: `tests/test_waveform.py`

**Interfaces:**
- Consumes: `core.audio_decode.load_audio(path) -> tuple[NDArray[np.float32], int]` (mono `(samples,)`, multichannel `(channels, samples)`), `core.audio_decode.AudioDecodeError`.
- Produces:
  - `core.waveform.DEFAULT_BUCKETS: int = 2048`
  - `core.waveform.Peaks` — frozen dataclass (`eq=False`) with `duration: float`, `mins: NDArray[np.float32]`, `maxs: NDArray[np.float32]` (equal length ≥ 1, values in [-1, 1]).
  - `core.waveform.WaveformCancelled(Exception)`
  - `core.waveform.compute_peaks(path: str, *, buckets: int = DEFAULT_BUCKETS, cancel: threading.Event | None = None) -> Peaks`; raises `AudioDecodeError` on unreadable/empty audio and `WaveformCancelled` when `cancel` is set.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_waveform.py`:

```python
"""Waveform peaks: absolute amplitude, channel folding, streaming and fallback."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
import soundfile as sf

from core.audio_decode import AudioDecodeError
from core.waveform import WaveformCancelled, compute_peaks

_RATE = 8000


def _sine(seconds: float, amplitude: float) -> np.ndarray:
    t = np.arange(int(_RATE * seconds)) / _RATE
    # 1 kHz at 8 kHz hits the crest exactly (every 8th sample).
    return (amplitude * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)


class ComputePeaksTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def _write(self, name: str, data: np.ndarray, subtype: str = "PCM_16") -> str:
        path = os.path.join(self.dir, name)
        sf.write(path, data, _RATE, subtype=subtype)
        return path

    def test_sine_keeps_absolute_amplitude(self) -> None:
        path = self._write("half.wav", _sine(1.0, 0.5))
        peaks = compute_peaks(path, buckets=100)
        self.assertEqual(len(peaks.mins), 100)
        self.assertEqual(len(peaks.maxs), 100)
        self.assertAlmostEqual(peaks.duration, 1.0)
        np.testing.assert_allclose(peaks.maxs, 0.5, atol=0.01)
        np.testing.assert_allclose(peaks.mins, -0.5, atol=0.01)

    def test_silence_is_zero(self) -> None:
        path = self._write("silence.wav", np.zeros(_RATE, dtype=np.float32))
        peaks = compute_peaks(path, buckets=50)
        np.testing.assert_array_equal(peaks.mins, 0.0)
        np.testing.assert_array_equal(peaks.maxs, 0.0)

    def test_stereo_folds_to_louder_channel(self) -> None:
        stereo = np.stack([np.zeros(_RATE, dtype=np.float32), _sine(1.0, 0.8)], axis=1)
        path = self._write("stereo.wav", stereo)
        peaks = compute_peaks(path, buckets=40)
        np.testing.assert_allclose(peaks.maxs, 0.8, atol=0.01)
        np.testing.assert_allclose(peaks.mins, -0.8, atol=0.01)

    def test_bucket_count_clamps_to_frames(self) -> None:
        path = self._write("tiny.wav", _sine(50 / _RATE, 0.3))
        peaks = compute_peaks(path, buckets=2048)
        self.assertEqual(len(peaks.mins), 50)

    def test_values_are_clipped_to_full_scale(self) -> None:
        loud = np.full(_RATE, 1.5, dtype=np.float32)
        path = self._write("loud.wav", loud, subtype="FLOAT")
        peaks = compute_peaks(path, buckets=10)
        np.testing.assert_array_equal(peaks.maxs, 1.0)

    def test_cancel_event_raises(self) -> None:
        path = self._write("cancel.wav", _sine(1.0, 0.5))
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(WaveformCancelled):
            compute_peaks(path, cancel=cancel)

    def test_corrupt_file_raises_decode_error(self) -> None:
        path = os.path.join(self.dir, "broken.wav")
        with open(path, "wb") as handle:
            handle.write(b"not audio at all")
        with self.assertRaises(AudioDecodeError):
            compute_peaks(path)

    def test_streamed_blocks_match_whole_file_reduction(self) -> None:
        rng = np.random.default_rng(7)
        data = (rng.random(10_000, dtype=np.float32) * 1.6 - 0.8).astype(np.float32)
        path = self._write("noise.wav", data, subtype="FLOAT")
        buckets = 7  # 10 000 / 7 frames per bucket: every bucket straddles a block edge
        with mock.patch("core.waveform._BLOCK_FRAMES", 1000):
            peaks = compute_peaks(path, buckets=buckets)
        index = (np.arange(data.size) * buckets) // data.size
        expected_min = np.array([data[index == b].min() for b in range(buckets)])
        expected_max = np.array([data[index == b].max() for b in range(buckets)])
        np.testing.assert_array_equal(peaks.mins, expected_min)
        np.testing.assert_array_equal(peaks.maxs, expected_max)

    def test_fallback_mono_array_reduces(self) -> None:
        mono = _sine(2.0, 0.25)
        with (
            mock.patch("soundfile.SoundFile", side_effect=RuntimeError("unsupported")),
            mock.patch("core.waveform.load_audio", return_value=(mono, _RATE)) as load,
        ):
            peaks = compute_peaks("/music/song.m4a", buckets=16)
        load.assert_called_once_with("/music/song.m4a")
        self.assertAlmostEqual(peaks.duration, 2.0)
        self.assertEqual(len(peaks.maxs), 16)
        np.testing.assert_allclose(peaks.maxs, 0.25, atol=0.01)

    def test_fallback_multichannel_array_reduces(self) -> None:
        channels = np.stack([_sine(1.0, 0.1), _sine(1.0, 0.6)])  # (channels, samples)
        with (
            mock.patch("soundfile.SoundFile", side_effect=RuntimeError("unsupported")),
            mock.patch("core.waveform.load_audio", return_value=(channels, _RATE)),
        ):
            peaks = compute_peaks("/music/song.aac", buckets=8)
        np.testing.assert_allclose(peaks.maxs, 0.6, atol=0.01)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_waveform -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'core.waveform'`.

- [ ] **Step 3: Implement `core/waveform.py`**

```python
"""Waveform peaks for the compare dialog: min/max envelopes at a fixed resolution.

Pure numpy over :mod:`core.audio_decode`; no GTK and no GStreamer. Values are raw
sample values clipped to full scale and never normalised, so every track of a
comparison shares one amplitude scale.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .audio_decode import AudioDecodeError, load_audio

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

DEFAULT_BUCKETS = 2048
_BLOCK_FRAMES = 65536


class WaveformCancelled(Exception):
    """The caller's cancel event was set while peaks were being computed."""


@dataclass(frozen=True, eq=False)
class Peaks:
    duration: float
    mins: NDArray[np.float32]
    maxs: NDArray[np.float32]


def _check(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise WaveformCancelled


class _Reducer:
    """Folds ``(frames, channels)`` blocks into ``buckets`` equal shares of ``frames``."""

    def __init__(self, frames: int, buckets: int) -> None:
        import numpy as np

        self.frames = frames
        self.buckets = max(1, min(buckets, frames))
        self.mins = np.full(self.buckets, np.inf, dtype=np.float32)
        self.maxs = np.full(self.buckets, -np.inf, dtype=np.float32)
        self.read = 0

    def feed(self, block: NDArray[np.float32]) -> None:
        import numpy as np

        count = block.shape[0]
        if count == 0:
            return
        lows = block.min(axis=1)
        highs = block.max(axis=1)
        index = (np.arange(self.read, self.read + count, dtype=np.int64) * self.buckets) // (
            self.frames
        )
        # A decoder that yields more frames than it declared folds them into the last bucket.
        np.minimum(index, self.buckets - 1, out=index)
        self.read += count
        starts = np.concatenate(([0], np.flatnonzero(np.diff(index)) + 1))
        ids = index[starts]
        # A bucket can straddle two blocks: merge with what the earlier block left.
        self.mins[ids] = np.minimum(self.mins[ids], np.minimum.reduceat(lows, starts))
        self.maxs[ids] = np.maximum(self.maxs[ids], np.maximum.reduceat(highs, starts))

    def result(self, rate: int) -> Peaks:
        import numpy as np

        # Buckets never reached (the file was shorter than declared) stay silent.
        mins = np.where(np.isfinite(self.mins), self.mins, 0.0)
        maxs = np.where(np.isfinite(self.maxs), self.maxs, 0.0)
        return Peaks(
            self.frames / rate,
            np.clip(mins, -1.0, 1.0).astype(np.float32),
            np.clip(maxs, -1.0, 1.0).astype(np.float32),
        )


def _stream_peaks(path: str, buckets: int, cancel: threading.Event | None) -> Peaks | None:
    """Block-wise SoundFile read; ``None`` when SoundFile cannot stream this file."""
    try:
        import soundfile as sf

        audio = sf.SoundFile(path)
    except Exception:
        return None
    with audio:
        frames = int(audio.frames)
        rate = int(audio.samplerate)
        if frames <= 0 or rate <= 0:
            return None
        reducer = _Reducer(frames, buckets)
        try:
            for block in audio.blocks(
                blocksize=_BLOCK_FRAMES, dtype="float32", always_2d=True
            ):
                _check(cancel)
                reducer.feed(block)
        except WaveformCancelled:
            raise
        except Exception:
            # A mid-file decode error: let the FFmpeg path try the whole file.
            return None
    if reducer.read == 0:
        return None
    return reducer.result(rate)


def compute_peaks(
    path: str, *, buckets: int = DEFAULT_BUCKETS, cancel: threading.Event | None = None
) -> Peaks:
    """Min/max envelope of ``path`` in at most ``buckets`` equal time slices."""
    if buckets <= 0:
        raise ValueError("buckets must be positive")
    _check(cancel)
    streamed = _stream_peaks(path, buckets, cancel)
    if streamed is not None:
        return streamed
    _check(cancel)
    data, rate = load_audio(path)
    _check(cancel)
    by_channel = data.reshape(1, -1) if data.ndim == 1 else data
    if by_channel.shape[1] == 0:
        raise AudioDecodeError("Cannot decode audio: Empty audio data")
    reducer = _Reducer(by_channel.shape[1], buckets)
    reducer.feed(by_channel.T)
    return reducer.result(rate)


__all__ = ["DEFAULT_BUCKETS", "Peaks", "WaveformCancelled", "compute_peaks"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_waveform -v`
Expected: all 10 tests PASS. If `test_corrupt_file_raises_decode_error` is slow, that is FFmpeg probing the file; it must still raise `AudioDecodeError`.

- [ ] **Step 5: Lint, format, type-check the new files**

Run:
```bash
.venv/bin/ruff format core/waveform.py tests/test_waveform.py
.venv/bin/ruff check core/waveform.py tests/test_waveform.py
.venv/bin/python -m basedpyright core/waveform.py tests/test_waveform.py
```
Expected: no errors. If basedpyright flags `np.minimum.reduceat` return types, narrow with `cast("NDArray[np.float32]", …)` rather than `Any`.

- [ ] **Step 6: Commit**

```bash
git add core/waveform.py tests/test_waveform.py
git commit -m "feat(core): waveform peaks for stem comparison

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Peak cache and background loader

**Files:**
- Create: `ui/playback/waveforms.py`
- Modify: `ui/playback/session.py` (own a `PeakCache`, clear it in `clear()`)
- Test: `tests/test_waveform_loader.py`

**Interfaces:**
- Consumes: `core.waveform.Peaks`, `core.waveform.WaveformCancelled`, `core.waveform.compute_peaks(path, *, buckets=…, cancel=…)` from Task 1; `ui.dispatch.idle_on_main(func, *args)`; `core.debug_log.log_event`.
- Produces:
  - `ui.playback.waveforms.PeakCache` with `get(path: str) -> Peaks | None`, `put(path: str, peaks: Peaks) -> None`, `clear() -> None`, `__len__() -> int`. Key is `(abspath, st_mtime_ns, st_size)`; a missing file is a miss and `put` on it is a no-op.
  - `ui.playback.waveforms.PeakCallback = Callable[[int, Peaks | None], None]`
  - `ui.playback.waveforms.PeakLoading` — Protocol with `load(paths: Sequence[str], first: int, on_peaks: PeakCallback) -> None` and `cancel() -> None`.
  - `ui.playback.waveforms.WaveformLoader(cache: PeakCache, *, compute: Callable[..., Peaks] = compute_peaks, dispatch: Callable[..., None] | None = None)` implementing `PeakLoading`, plus a read-only `cache` property. `dispatch=None` means `ui.dispatch.idle_on_main`, imported lazily.
  - `ListeningSession.peak_cache: PeakCache` (cleared by `ListeningSession.clear()`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_waveform_loader.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_waveform_loader -v`
Expected: ERROR — `ModuleNotFoundError: No module named 'ui.playback.waveforms'`.

- [ ] **Step 3: Implement `ui/playback/waveforms.py`**

```python
"""Waveform peaks for the compare dialog, computed off the main loop and cached.

GTK-free apart from main-loop delivery, which is injected (``ui.dispatch.idle_on_main``
by default), so this module tests without a display.
"""

from __future__ import annotations

import os
import threading
from typing import Callable, Protocol, Sequence

from core.debug_log import log_event
from core.waveform import Peaks, WaveformCancelled, compute_peaks

PeakCallback = Callable[[int, Peaks | None], None]


class PeakCache:
    """Peaks keyed on path plus modification time and size."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, int, int], Peaks] = {}

    @staticmethod
    def _key(path: str) -> tuple[str, int, int] | None:
        try:
            stat = os.stat(path)
        except OSError:
            return None
        return (os.path.abspath(path), stat.st_mtime_ns, stat.st_size)

    def get(self, path: str) -> Peaks | None:
        key = self._key(path)
        return None if key is None else self._entries.get(key)

    def put(self, path: str, peaks: Peaks) -> None:
        key = self._key(path)
        if key is not None:
            self._entries[key] = peaks

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


class PeakLoading(Protocol):
    def load(self, paths: Sequence[str], first: int, on_peaks: PeakCallback) -> None: ...
    def cancel(self) -> None: ...


def _idle_on_main(func: Callable[..., None], *args: object) -> None:
    from ..dispatch import idle_on_main

    idle_on_main(func, *args)


class WaveformLoader:
    """Computes one set's peaks on a single worker thread, audible track first."""

    def __init__(
        self,
        cache: PeakCache,
        *,
        compute: Callable[..., Peaks] = compute_peaks,
        dispatch: Callable[..., None] | None = None,
    ) -> None:
        self._cache = cache
        self._compute = compute
        self._dispatch = dispatch or _idle_on_main
        self._generation = 0
        self._cancel_event: threading.Event | None = None
        self._thread: threading.Thread | None = None

    @property
    def cache(self) -> PeakCache:
        return self._cache

    def load(self, paths: Sequence[str], first: int, on_peaks: PeakCallback) -> None:
        self.cancel()
        generation = self._generation
        order = list(range(len(paths)))
        if 0 <= first < len(paths):
            order.remove(first)
            order.insert(0, first)
        jobs: list[tuple[int, str]] = []
        for index in order:
            cached = self._cache.get(paths[index])
            if cached is not None:
                self._dispatch(self._deliver, generation, index, cached, on_peaks)
            else:
                jobs.append((index, paths[index]))
        if not jobs:
            return
        cancel = threading.Event()
        self._cancel_event = cancel
        self._thread = threading.Thread(
            target=self._work,
            args=(generation, jobs, on_peaks, cancel),
            name="uvr-waveforms",
            daemon=True,
        )
        self._thread.start()

    def cancel(self) -> None:
        self._generation += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._cancel_event = None

    def _work(
        self,
        generation: int,
        jobs: list[tuple[int, str]],
        on_peaks: PeakCallback,
        cancel: threading.Event,
    ) -> None:
        for index, path in jobs:
            if cancel.is_set():
                return
            try:
                peaks: Peaks | None = self._compute(path, cancel=cancel)
            except WaveformCancelled:
                return
            except Exception as exc:
                log_event("playback", "waveform_error", level="warning", path=path, error=str(exc))
                peaks = None
            if peaks is not None:
                self._cache.put(path, peaks)
            self._dispatch(self._deliver, generation, index, peaks, on_peaks)

    def _deliver(
        self, generation: int, index: int, peaks: Peaks | None, on_peaks: PeakCallback
    ) -> None:
        if generation == self._generation:
            on_peaks(index, peaks)


__all__ = ["PeakCache", "PeakCallback", "PeakLoading", "WaveformLoader"]
```

- [ ] **Step 4: Give `ListeningSession` a peak cache**

Replace `ui/playback/session.py` with:

```python
"""The latest run's comparison sets, in arrival order. No GTK."""

from __future__ import annotations

from core.listening import ComparisonSet

from .waveforms import PeakCache


class ListeningSession:
    def __init__(self) -> None:
        self._sets: dict[str, ComparisonSet] = {}
        self.peak_cache = PeakCache()

    def clear(self) -> None:
        self._sets.clear()
        self.peak_cache.clear()

    def add(self, cset: ComparisonSet) -> None:
        self._sets[cset.source] = cset

    def sets(self) -> tuple[ComparisonSet, ...]:
        return tuple(self._sets.values())

    def __len__(self) -> int:
        return len(self._sets)

    def __bool__(self) -> bool:
        return bool(self._sets)


__all__ = ["ListeningSession"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_waveform_loader tests.test_compare_run_integration -v`
Expected: all PASS (the integration tests confirm `ListeningSession` still behaves; they need no display for the session tests).

- [ ] **Step 6: Check that importing the session stays light**

`ui/run_control.py` imports `ui.playback.session` at startup, which now pulls in `core.waveform`. Confirm it adds no heavy module-level imports:

Run: `rg -n "^(import|from) (numpy|soundfile|librosa)" core/waveform.py ui/playback/waveforms.py ui/playback/session.py`
Expected: no matches (numpy/soundfile are imported inside functions or under `TYPE_CHECKING` only).

- [ ] **Step 7: Lint, format, type-check**

```bash
.venv/bin/ruff format ui/playback/waveforms.py ui/playback/session.py tests/test_waveform_loader.py
.venv/bin/ruff check ui/playback/waveforms.py ui/playback/session.py tests/test_waveform_loader.py
.venv/bin/python -m basedpyright ui/playback/waveforms.py ui/playback/session.py tests/test_waveform_loader.py
```
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add ui/playback/waveforms.py ui/playback/session.py tests/test_waveform_loader.py
git commit -m "feat(ui): load and cache waveform peaks off the main loop

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Waveform widget

**Files:**
- Create: `ui/widgets/waveform.py`
- Test: `tests/test_waveform_view.py`

**Interfaces:**
- Consumes: `core.waveform.Peaks` (Task 1).
- Produces:
  - `ui.widgets.waveform.WAVEFORM_HEIGHT: int = 40`
  - `x_to_seconds(x: float, width: float, duration: float) -> float` and `seconds_to_x(seconds: float, width: float, duration: float) -> float`: clamp to `[0, duration]` / `[0, width]`; return `0.0` when `width <= 0` or `duration <= 0`.
  - `column_extents(peaks: Peaks, width: int, timeline: float) -> tuple[NDArray[np.float32], NDArray[np.float32]]`: per-pixel-column (min, max); columns past the track's end are omitted.
  - `WaveformView(Gtk.DrawingArea)` with `on_seek: Callable[[float], None]`, `set_peaks(peaks: Peaks | None)`, `set_timeline(duration: float)`, `set_position(seconds: float)`, `set_active(active: bool)`, `seek_at(x: float, width: float)`, and read-only properties `peaks`, `timeline` (effective: the set timeline, else the peaks' own duration, else 0), `position`, `active`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_waveform_view.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_waveform_view -v`
Expected: ERROR/FAIL — `ModuleNotFoundError: No module named 'ui.widgets.waveform'` (the view tests skip without a display).

- [ ] **Step 3: Implement `ui/widgets/waveform.py`**

```python
"""Waveform strip for one track: shared time axis, playhead, click or drag to seek.

Heights use one absolute scale (±1.0 fills the row), so rows compare honestly.
Colours come from the widget's CSS colour; the audible row carries libadwaita's
``accent`` class, which turns that colour into the accent colour.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from gi.repository import Gtk

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from core.waveform import Peaks

WAVEFORM_HEIGHT = 40
_INACTIVE_ALPHA = 0.55
_UNPLAYED_ALPHA = 0.45
_PLACEHOLDER_ALPHA = 0.25


def x_to_seconds(x: float, width: float, duration: float) -> float:
    if width <= 0 or duration <= 0:
        return 0.0
    return min(max(x / width, 0.0), 1.0) * duration


def seconds_to_x(seconds: float, width: float, duration: float) -> float:
    if width <= 0 or duration <= 0:
        return 0.0
    return min(max(seconds / duration, 0.0), 1.0) * width


def column_extents(
    peaks: Peaks, width: int, timeline: float
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Per-pixel-column min and max on an axis ``timeline`` seconds long.

    Columns past the track's own end are omitted, so a shorter track stops early.
    """
    import numpy as np

    buckets = len(peaks.mins)
    if width <= 0 or buckets == 0 or timeline <= 0 or peaks.duration <= 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, empty
    per_column = timeline / width * buckets / peaks.duration
    starts = np.floor(np.arange(width) * per_column).astype(np.intp)
    starts = starts[starts < buckets]
    return np.minimum.reduceat(peaks.mins, starts), np.maximum.reduceat(peaks.maxs, starts)


def _noop(_seconds: float) -> None:
    return None


class WaveformView(Gtk.DrawingArea):
    def __init__(self) -> None:
        super().__init__()
        self.on_seek: Callable[[float], None] = _noop
        self._peaks: Peaks | None = None
        self._timeline = 0.0
        self._position = 0.0
        self._active = False
        self.set_content_height(WAVEFORM_HEIGHT)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.add_controller(drag)

    # -- state -----------------------------------------------------------------

    @property
    def peaks(self) -> Peaks | None:
        return self._peaks

    @property
    def timeline(self) -> float:
        if self._timeline > 0:
            return self._timeline
        return self._peaks.duration if self._peaks is not None else 0.0

    @property
    def position(self) -> float:
        return self._position

    @property
    def active(self) -> bool:
        return self._active

    def set_peaks(self, peaks: Peaks | None) -> None:
        self._peaks = peaks
        self.queue_draw()

    def set_timeline(self, duration: float) -> None:
        self._timeline = max(0.0, duration)
        self.queue_draw()

    def set_position(self, seconds: float) -> None:
        self._position = seconds
        self.queue_draw()

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self.add_css_class("accent")
        else:
            self.remove_css_class("accent")
        self.queue_draw()

    # -- seeking ---------------------------------------------------------------

    def seek_at(self, x: float, width: float) -> None:
        timeline = self.timeline
        if timeline > 0 and width > 0:
            self.on_seek(x_to_seconds(x, width, timeline))

    def _on_drag_begin(self, gesture: Gtk.GestureDrag, x: float, _y: float) -> None:
        # Claiming keeps the press from also activating the row (switching tracks).
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.seek_at(x, self.get_width())

    def _on_drag_update(self, gesture: Gtk.GestureDrag, dx: float, _dy: float) -> None:
        ok, x, _y = gesture.get_start_point()
        if ok:
            self.seek_at(x + dx, self.get_width())

    # -- drawing ---------------------------------------------------------------

    def _draw(self, _area: Gtk.DrawingArea, cr: Any, width: int, height: int, *_data: object) -> None:
        color = self.get_color()
        red, green, blue, alpha = color.red, color.green, color.blue, color.alpha
        middle = height / 2
        timeline = self.timeline
        peaks = self._peaks
        if peaks is None or timeline <= 0:
            cr.set_source_rgba(red, green, blue, alpha * _PLACEHOLDER_ALPHA)
            cr.rectangle(0, middle - 0.5, width, 1)
            cr.fill()
            return
        lows, highs = column_extents(peaks, width, timeline)
        columns = len(highs)
        played = min(int(seconds_to_x(self._position, width, timeline)), columns)
        strength = alpha * (1.0 if self._active else _INACTIVE_ALPHA)
        for first, last, share in ((0, played, 1.0), (played, columns, _UNPLAYED_ALPHA)):
            if first >= last:
                continue
            for column in range(first, last):
                high = float(highs[column])
                low = float(lows[column])
                cr.rectangle(column, middle - high * middle, 1, max((high - low) * middle, 1.0))
            cr.set_source_rgba(red, green, blue, strength * share)
            cr.fill()
        playhead = min(seconds_to_x(self._position, width, timeline), max(width - 1, 0))
        cr.set_source_rgba(red, green, blue, alpha)
        cr.rectangle(playhead, 0, 1, height)
        cr.fill()


__all__ = [
    "WAVEFORM_HEIGHT",
    "WaveformView",
    "column_extents",
    "seconds_to_x",
    "x_to_seconds",
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run the non-display tests: `.venv/bin/python -m unittest tests.test_waveform_view -v`
Expected: MappingTests and ColumnExtentsTests PASS; WaveformViewTests skipped when no display.

Then the view tests under Xvfb:
```bash
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m unittest tests.test_waveform_view -v
```
Expected: all 12 tests PASS.

- [ ] **Step 5: Lint, format, type-check**

```bash
.venv/bin/ruff format ui/widgets/waveform.py tests/test_waveform_view.py
.venv/bin/ruff check ui/widgets/waveform.py tests/test_waveform_view.py
.venv/bin/python -m basedpyright ui/widgets/waveform.py tests/test_waveform_view.py
```
Expected: no errors. The draw callback's `cr` stays `Any` as in `ui/widgets/progress_ring.py` (the stubs type `set_draw_func` as `Callable[..., None]`).

- [ ] **Step 6: Commit**

```bash
git add ui/widgets/waveform.py tests/test_waveform_view.py
git commit -m "feat(ui): waveform view with shared timeline and click-to-seek

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Waveforms in the compare dialog

**Files:**
- Modify: `ui/playback/dialog.py` (whole file shown below)
- Modify: `resources/ui/compare-stems-dialog.blp` (whole file shown below) and rebuild `ui/data/uvr.gresource`
- Modify: `ui/run_control.py:1031-1047` (`open_compare`)
- Modify: `tests/test_compare_dialog.py`, `tests/test_compare_run_integration.py`
- Modify: `docs/tracked-issues.md` (P4 row and "Last reviewed" line)

**Interfaces:**
- Consumes: `WaveformView` (Task 3); `PeakLoading`, `WaveformLoader`, `PeakCache` (Task 2); `ListeningSession.peak_cache` (Task 2); `core.waveform.Peaks` (Task 1); `PlaybackControls` (existing, `ui/playback/engine.py`).
- Produces: `CompareDialog(sets, engine, *, waveforms: PeakLoading | None = None, output_dir="", on_toast=None, on_closed=None)` with public `rows: list[Gtk.ListBoxRow]`, `titles: list[Gtk.Label]`, `waveforms: list[WaveformView]` (one per track, same order). `seek_scale` no longer exists.

- [ ] **Step 1: Update the dialog tests (failing)**

In `tests/test_compare_dialog.py`:

1. Add imports at the top (next to the existing ones):

```python
import numpy as np

from core.waveform import Peaks
```

2. After `class FakeEngine`, add a fake loader that logs into a shared call list:

```python
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
```

3. Replace the `_dialog` helper so it can pass a loader:

```python
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
```

4. In `test_loads_first_set_with_first_output_selected`, replace the titles assertion:

```python
        self.assertEqual(
            [t.get_label() for t in dialog.titles], [REFERENCE_LABEL, "Vocals", "Instrumental"]
        )
```

5. Replace `test_duration_and_position_update_labels_and_scale` with:

```python
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

    def test_switching_input_reloads_peaks(self) -> None:
        dialog, engine = self._dialog(_set("a", "Vocals"), _set("b", "Vocals", "Drums"), loader=True)
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
```

6. In `test_radio_follows_engine_when_default_track_fails`, add after the existing assertions:

```python
        self.assertEqual([w.active for w in dialog.waveforms], [True, False, False])
```

- [ ] **Step 2: Run the dialog tests to verify they fail**

```bash
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m unittest tests.test_compare_dialog -v
```
Expected: FAIL/ERROR — `TypeError: ... unexpected keyword argument 'waveforms'` and missing `titles` / `waveforms` attributes.

- [ ] **Step 3: Update the Blueprint**

Replace `resources/ui/compare-stems-dialog.blp` with:

```blueprint
using Gtk 4.0;
using Adw 1;

Adw.Dialog dialog {
  title: "Compare stems";
  content-width: 560;
  child: Adw.ToolbarView {
    [top]
    Adw.HeaderBar {}
    content: Gtk.Box {
      orientation: vertical;
      spacing: 12;
      margin-top: 6;
      margin-bottom: 12;
      margin-start: 12;
      margin-end: 12;
      Gtk.DropDown input_dropdown {
        visible: false;
      }
      Gtk.ListBox track_list {
        selection-mode: none;
        styles ["boxed-list"]
      }
      Gtk.Box {
        orientation: horizontal;
        spacing: 12;
        Gtk.Button play_button {
          icon-name: "media-playback-start-symbolic";
          valign: center;
          styles ["circular"]
        }
        Gtk.Label elapsed_label {
          label: "0:00";
          styles ["numeric", "dim-label"]
        }
        Gtk.Label total_label {
          label: "0:00";
          hexpand: true;
          xalign: 1;
          styles ["numeric", "dim-label"]
        }
      }
      Gtk.Box {
        orientation: horizontal;
        spacing: 12;
        Gtk.Label {
          label: "Space play · 1–9 switch · ← → 5 s";
          hexpand: true;
          xalign: 0;
          styles ["dim-label", "caption"]
        }
        Gtk.Button folder_button {
          label: "Open folder";
        }
      }
    };
  };
}
```

Then rebuild and check:

```bash
blueprint-compiler lint resources/ui/compare-stems-dialog.blp
./resources/compile_resources.sh
./resources/compile_resources.sh --check
```
Expected: lint prints no new diagnostics for the changed lines; compile succeeds; `--check` reports the bundle matches.

- [ ] **Step 4: Replace `ui/playback/dialog.py`**

```python
"""Compare stems dialog: one input's tracks, one audible at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

from gi.repository import Adw, Gdk, Gtk

from core.listening import ComparisonSet, Track

from ..dialogs.utils import present_modal_dialog
from ..files import open_folder_in_file_manager
from ..gtk_narrow import root_window
from ..template import load_builder, object_from_builder
from ..widgets.waveform import WaveformView
from .engine import PlaybackControls

if TYPE_CHECKING:
    from core.waveform import Peaks

    from .waveforms import PeakLoading

_SEEK_STEP = 5.0
_PLAY_ICON = "media-playback-start-symbolic"
_PAUSE_ICON = "media-playback-pause-symbolic"
_NUMBER_KEYS = {getattr(Gdk, f"KEY_{n}"): n - 1 for n in range(1, 10)}
_NUMBER_KEYS.update({getattr(Gdk, f"KEY_KP_{n}"): n - 1 for n in range(1, 10)})


def _mmss(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


class CompareDialog:
    def __init__(
        self,
        sets: Sequence[ComparisonSet],
        engine: PlaybackControls,
        *,
        waveforms: PeakLoading | None = None,
        output_dir: str = "",
        on_toast: Callable[[str], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self._sets = list(sets)
        self._engine = engine
        self._peak_loader = waveforms
        self._output_dir = output_dir
        self._on_toast = on_toast
        self._on_closed = on_closed
        self._parent: Gtk.Window | None = None
        self._building = False

        builder = load_builder("compare-stems-dialog")
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        self.input_dropdown = object_from_builder(builder, "input_dropdown", Gtk.DropDown)
        self._track_list = object_from_builder(builder, "track_list", Gtk.ListBox)
        self.play_button = object_from_builder(builder, "play_button", Gtk.Button)
        self._elapsed = object_from_builder(builder, "elapsed_label", Gtk.Label)
        self._total = object_from_builder(builder, "total_label", Gtk.Label)
        self.folder_button = object_from_builder(builder, "folder_button", Gtk.Button)
        self.rows: list[Gtk.ListBoxRow] = []
        self.titles: list[Gtk.Label] = []
        self.waveforms: list[WaveformView] = []
        self._checks: list[Gtk.CheckButton] = []

        self.play_button.update_property([Gtk.AccessibleProperty.LABEL], ["Play"])
        self.play_button.connect("clicked", lambda _b: self._engine.toggle())
        self._track_list.connect("row-activated", self._on_row_activated)
        self.folder_button.set_visible(bool(output_dir))
        self.folder_button.connect("clicked", self._on_open_folder)
        self.dialog.connect("closed", self._on_dialog_closed)

        # Capture phase: a focused radio or button would otherwise consume Space first.
        self._keys = Gtk.EventControllerKey()
        self._keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._keys.connect("key-pressed", lambda _c, keyval, _code, _state: self.handle_key(keyval))
        self.dialog.add_controller(self._keys)

        engine.on_position = self._on_position
        engine.on_duration = self._on_duration
        engine.on_state = self._on_state
        engine.on_track_error = self._on_track_error
        engine.on_error = self._on_engine_error

        if len(self._sets) > 1:
            total = len(self._sets)
            names = [f"{s.name}  {i} of {total}" for i, s in enumerate(self._sets, start=1)]
            self.input_dropdown.set_model(Gtk.StringList.new(names))
            self.input_dropdown.set_visible(True)
            self.input_dropdown.connect("notify::selected", self._on_input_changed)
        self._show_set(0, position=0.0)

    # -- public ----------------------------------------------------------------

    def present(self, parent: Gtk.Window | None) -> None:
        self._parent = parent
        present_modal_dialog(self.dialog, parent)

    def close(self) -> None:
        self._cancel_peaks()
        self.dialog.force_close()
        self._engine.unload()

    def handle_key(self, keyval: int) -> bool:
        if keyval == Gdk.KEY_space:
            self._engine.toggle()
            return True
        if keyval == Gdk.KEY_Left:
            self._engine.seek(self._engine.position - _SEEK_STEP)
            return True
        if keyval == Gdk.KEY_Right:
            self._engine.seek(self._engine.position + _SEEK_STEP)
            return True
        index = _NUMBER_KEYS.get(keyval)
        if index is not None and index < len(self.rows) and self.rows[index].get_sensitive():
            self._select(index)
            return True
        return False

    # -- building --------------------------------------------------------------

    def _show_set(self, index: int, *, position: float) -> None:
        cset = self._sets[index]
        self._cancel_peaks()
        self._building = True
        for row in self.rows:
            self._track_list.remove(row)
        self.rows = []
        self.titles = []
        self.waveforms = []
        self._checks = []
        group: Gtk.CheckButton | None = None
        for row_index, track in enumerate(cset.tracks):
            check = self._add_row(track, row_index, position)
            if group is None:
                group = check
            else:
                check.set_group(group)
        selected = 1 if len(cset.tracks) > 1 else 0
        self._checks[selected].set_active(True)
        self.play_button.set_sensitive(True)
        self._engine.load(cset.tracks, selected=selected, position=position)
        # The engine falls back to another track when the default one fails to load.
        actual = self._engine.selected
        if 0 <= actual < len(self._checks):
            self._checks[actual].set_active(True)
        self._building = False
        if self._peak_loader is not None:
            self._peak_loader.load(
                [track.path for track in cset.tracks], self._engine.selected, self._on_peaks
            )

    def _add_row(self, track: Track, index: int, position: float) -> Gtk.CheckButton:
        check = Gtk.CheckButton(valign=Gtk.Align.START)
        check.update_property([Gtk.AccessibleProperty.LABEL], [track.label])
        check.connect("toggled", self._on_check_toggled, index)

        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Label(label=track.label, xalign=0)
        details.append(title)
        if track.is_reference:
            caption = Gtk.Label(label="Reference", xalign=0)
            caption.add_css_class("dim-label")
            caption.add_css_class("caption")
            details.append(caption)
        waveform = WaveformView()
        waveform.set_margin_top(4)
        waveform.set_position(position)
        waveform.on_seek = lambda seconds: self._engine.seek(seconds)
        details.append(waveform)

        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        line.set_margin_top(8)
        line.set_margin_bottom(8)
        line.set_margin_start(12)
        line.set_margin_end(12)
        line.append(check)
        line.append(details)
        row = Gtk.ListBoxRow()
        row.set_child(line)
        self._track_list.append(row)

        self.rows.append(row)
        self.titles.append(title)
        self.waveforms.append(waveform)
        self._checks.append(check)
        return check

    def _select(self, index: int) -> None:
        if not self._checks[index].get_active():
            self._checks[index].set_active(True)
        else:
            self._engine.select(index)

    def _cancel_peaks(self) -> None:
        if self._peak_loader is not None:
            self._peak_loader.cancel()

    # -- signal handlers -------------------------------------------------------

    def _on_check_toggled(self, check: Gtk.CheckButton, index: int) -> None:
        if not check.get_active():
            return
        for row_index, waveform in enumerate(self.waveforms):
            waveform.set_active(row_index == index)
        # Rows are rebuilt before ``load``; the engine gets the selection from it.
        if not self._building:
            self._engine.select(index)

    def _on_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if row in self.rows and row.get_sensitive():
            self._select(self.rows.index(row))

    def _on_input_changed(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        position = self._engine.position
        if self._engine.playing:
            self._engine.pause()
        self._show_set(dropdown.get_selected(), position=position)

    def _on_open_folder(self, _button: Gtk.Button) -> None:
        window = self._parent or root_window(self.dialog)
        if window is None:
            return
        open_folder_in_file_manager(window, self._output_dir, on_error=self._toast)

    def _on_dialog_closed(self, _dialog: Adw.Dialog) -> None:
        self._cancel_peaks()
        self._engine.unload()
        if self._on_closed is not None:
            self._on_closed()

    def _on_peaks(self, index: int, peaks: Peaks | None) -> None:
        if 0 <= index < len(self.waveforms):
            self.waveforms[index].set_peaks(peaks)

    # -- engine callbacks ------------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        self._elapsed.set_label(_mmss(seconds))
        for waveform in self.waveforms:
            waveform.set_position(seconds)

    def _on_duration(self, seconds: float) -> None:
        self._total.set_label(_mmss(seconds))
        for waveform in self.waveforms:
            waveform.set_timeline(seconds)

    def _on_state(self, playing: bool) -> None:
        self.play_button.set_icon_name(_PAUSE_ICON if playing else _PLAY_ICON)
        self.play_button.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Pause" if playing else "Play"]
        )

    def _on_track_error(self, index: int, message: str) -> None:
        if 0 <= index < len(self.rows):
            self.rows[index].set_sensitive(False)
            self.rows[index].set_tooltip_text(message)

    def _on_engine_error(self, message: str) -> None:
        self.play_button.set_sensitive(False)
        self._toast(f"Couldn't start playback. {message}")

    def _toast(self, message: str) -> None:
        if self._on_toast is not None:
            self._on_toast(message)


__all__ = ["CompareDialog"]
```

Note the close order in `close()`: `force_close()` emits `closed`, whose handler cancels and unloads, and `close()` unloads again. Both calls are idempotent, which the existing `close()` already relied on.

- [ ] **Step 5: Run the dialog tests to verify they pass**

```bash
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m unittest tests.test_compare_dialog -v
```
Expected: all PASS, including the unchanged `test_row_activation_selects_track` (plain `Gtk.ListBoxRow.activate()` emits the list's `row-activated`).

- [ ] **Step 6: Wire the loader in `RunController.open_compare`**

In `ui/run_control.py`, change `open_compare` so the dialog gets a loader over the session cache:

```python
        from .playback.dialog import CompareDialog
        from .playback.engine import PlaybackEngine
        from .playback.waveforms import WaveformLoader

        self._compare_dialog = CompareDialog(
            self.listening.sets(),
            PlaybackEngine(),
            waveforms=WaveformLoader(self.listening.peak_cache),
            output_dir=self._run_output_dir,
            on_toast=self._host.toast,
            on_closed=self._on_compare_closed,
        )
```

In `tests/test_compare_run_integration.py`, extend `test_open_compare_presents_one_dialog` after the existing assertions:

```python
        loader = dialog_cls.call_args.kwargs["waveforms"]
        self.assertIs(loader.cache, controller.listening.peak_cache)
```

Run: `.venv/bin/python -m unittest tests.test_compare_run_integration -v`
Expected: all PASS.

- [ ] **Step 7: Update the tracked-issues row**

In `docs/tracked-issues.md`, P4 row: after `…one GStreamer \`audiomixer\` pipeline ([ui/playback/](../ui/playback/));` insert ` each track shows its waveform on one shared, non-normalised scale and timeline, and clicking a waveform seeks ([core/waveform.py](../core/waveform.py));`. Replace the line starting `*Last reviewed: 2026-09-28 — P4 added and closed by in-app stem comparison;` with `*Last reviewed: 2026-09-29 — P4 added and closed by in-app stem comparison, then extended with per-stem waveforms;` followed by the rest of the original sentence unchanged.

- [ ] **Step 8: Lint, format, type-check**

```bash
.venv/bin/ruff format ui/playback/dialog.py ui/run_control.py tests/test_compare_dialog.py tests/test_compare_run_integration.py
.venv/bin/ruff check ui/playback/dialog.py ui/run_control.py tests/test_compare_dialog.py tests/test_compare_run_integration.py
.venv/bin/python -m basedpyright ui/playback/dialog.py ui/run_control.py tests/test_compare_dialog.py tests/test_compare_run_integration.py
```
Expected: no errors. If `ruff format` touches unrelated lines in `ui/run_control.py`, that file was already formatted (the backlog is cleared) — investigate rather than commit unrelated churn.

- [ ] **Step 9: Commit**

```bash
git add resources/ui/compare-stems-dialog.blp ui/data/uvr.gresource ui/playback/dialog.py ui/run_control.py tests/test_compare_dialog.py tests/test_compare_run_integration.py docs/tracked-issues.md
git commit -m "feat(ui): per-stem waveforms replace the compare dialog's seek slider

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Whole-branch verification and a real-app look

**Files:**
- No new files. Fix-ups, if any, go in the file that owns the failure.

- [ ] **Step 1: Full test suite under Xvfb**

```bash
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m unittest discover -s tests -t . -v
```
Expected: `OK` (skips allowed). Any failure: fix in the owning task's file and re-run.

- [ ] **Step 2: Project-wide type check and resource check**

```bash
.venv/bin/python -m basedpyright
./resources/compile_resources.sh --check
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```
Expected: `0 errors`; bundle matches; ruff clean.

- [ ] **Step 3: Look at it in the real app**

Generate two stems and open the dialog directly (no model run needed):

```bash
PYTHONPATH=. .venv/bin/python - <<'EOF'
import os, tempfile
import numpy as np, soundfile as sf
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk
from core.listening import REFERENCE_LABEL, ComparisonSet, Track
from ui.playback.dialog import CompareDialog
from ui.playback.engine import PlaybackEngine
from ui.playback.waveforms import PeakCache, WaveformLoader

d = tempfile.mkdtemp()
t = np.arange(44100 * 8) / 44100
voc = 0.6 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 0.5 * t) > 0)
inst = 0.3 * np.sin(2 * np.pi * 110 * t) + 0.02 * np.sin(2 * np.pi * 220 * t)
paths = {}
for name, data in (("mix", voc + inst), ("vocals", voc), ("inst", inst[: 44100 * 6])):
    paths[name] = os.path.join(d, f"{name}.wav"); sf.write(paths[name], data.astype(np.float32), 44100)
cset = ComparisonSet(paths["mix"], (Track(REFERENCE_LABEL, paths["mix"], None, True),
    Track("Vocals", paths["vocals"]), Track("Instrumental", paths["inst"])))
app = Adw.Application(application_id="org.uvr.WaveformSmoke")
def activate(a):
    win = Adw.ApplicationWindow(application=a, default_width=900, default_height=600); win.present()
    CompareDialog([cset], PlaybackEngine(), waveforms=WaveformLoader(PeakCache())).present(win)
app.connect("activate", activate); app.run([])
EOF
```
Check by eye (in light and dark style): three waveforms; the Vocals row is accent-coloured; the Instrumental waveform ends at about 3/4 width (6 s of 8 s); the instrumental's quiet 220 Hz bleed is visibly lower than the vocals; clicking a waveform moves the playhead and time label without changing the selected radio; `1`–`3` switches the accent row; ←/→ still seek. Close the window when done. If playback is unavailable on the host the dialog still shows waveforms and seeking updates nothing — that is expected.

- [ ] **Step 4: Commit any fix-ups**

Only if Steps 1–3 required changes; stage the exact paths changed:

```bash
git add <exact paths>
git commit -m "fix(ui): <what the verification found>

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
