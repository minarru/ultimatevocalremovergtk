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
