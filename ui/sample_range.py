"""Opens the sample trim dialog from the Sample mode row and applies its edits."""

from __future__ import annotations

import os
from typing import Callable, Sequence

from gi.repository import Gtk

from core.settings import Settings
from core.waveform import Peaks

from .playback.trim import RangeEdit, TrimDialog
from .playback.waveforms import PeakCache, PeakLoading


class SampleRangeController:
    """One trim dialog at a time, shared by every page with a Sample mode row."""

    def __init__(
        self,
        settings_getter: Callable[[], Settings],
        *,
        parent: Callable[[], Gtk.Window | None],
        save: Callable[[], str | None],
        toast: Callable[[str], None],
        on_applied: Callable[[], None],
    ) -> None:
        self._settings = settings_getter
        self._parent = parent
        self._save = save
        self._toast = toast
        self._on_applied = on_applied
        self._dialog: TrimDialog | None = None
        self._open_inputs: list[str] | None = None
        # Peaks outlive each dialog: computing them takes about as long as the
        # dialog's open animation, so a fresh cache drew the waveform after it.
        self._peaks = PeakCache()
        self._warmer: PeakLoading | None = None
        self._warmed: str | None = None

    def open(self, inputs: Sequence[str]) -> None:
        wanted = [os.path.abspath(path) for path in inputs]
        if self._dialog is not None and self._open_inputs != wanted:
            self.close()
        if self._dialog is None:
            from .playback.engine import PlaybackEngine
            from .playback.waveforms import WaveformLoader

            settings = self._settings()
            self._dialog = TrimDialog(
                list(inputs),
                PlaybackEngine(),
                duration=settings.process.sample_mode_duration,
                starts=settings.process.sample_starts,
                lengths=settings.process.sample_lengths,
                on_apply=self._apply,
                waveforms=WaveformLoader(self._peaks),
                open_in_window=settings.ui.listening_in_window,
                on_toast=self._toast,
                on_closed=self._on_closed,
            )
            self._open_inputs = wanted
        self._dialog.present(self._parent())

    def warm(self, inputs: Sequence[str]) -> None:
        """Compute the first input's peaks ahead, so the dialog opens with its waveform."""
        if self._dialog is not None or not inputs:
            return
        path = os.path.abspath(inputs[0])
        if path == self._warmed or not os.path.isfile(path) or self._peaks.get(path) is not None:
            return
        self._warmed = path
        if self._warmer is None:
            from .playback.waveforms import WaveformLoader

            self._warmer = WaveformLoader(self._peaks)
        self._warmer.load([path], 0, _ignore_peaks)

    def sync_duration(self) -> None:
        """Apply the current sample length to the open dialog."""
        if self._dialog is not None:
            self._dialog.set_duration(self._settings().process.sample_mode_duration)

    def close(self) -> None:
        dialog, self._dialog = self._dialog, None
        if dialog is not None:
            dialog.close()

    def _on_closed(self) -> None:
        self._dialog = None
        self._open_inputs = None

    def _apply(self, edits: dict[str, RangeEdit]) -> None:
        settings = self._settings()
        # The input list may have changed while the dialog was open.
        current = {os.path.abspath(path) for path in settings.process.input_paths}
        starts = dict(settings.process.sample_starts)
        lengths = dict(settings.process.sample_lengths)
        for path, (start, length) in edits.items():
            if path not in current:
                continue
            _store(starts, path, start)
            _store(lengths, path, length)
        settings.process.sample_starts = starts
        settings.process.sample_lengths = lengths
        error = self._save()
        if error:
            self._toast(error)
        self._on_applied()


def _ignore_peaks(_index: int, _peaks: Peaks | None) -> None:
    """Warming only fills the cache; the dialog draws from it."""


def _store(values: dict[str, float], path: str, seconds: float | None) -> None:
    if seconds is None:
        values.pop(path, None)
    else:
        values[path] = round(seconds, 3)


__all__ = ["SampleRangeController"]
