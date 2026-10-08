"""Opens the sample trim dialog from the Sample mode row and applies its edits."""

from __future__ import annotations

import os
from typing import Callable, Sequence

from gi.repository import Gtk

from core.settings import Settings

from .playback.trim import TrimDialog


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

    def open(self, inputs: Sequence[str]) -> None:
        if self._dialog is None:
            from .playback.engine import PlaybackEngine
            from .playback.waveforms import PeakCache, WaveformLoader

            settings = self._settings()
            self._dialog = TrimDialog(
                list(inputs),
                PlaybackEngine(),
                duration=settings.process.sample_mode_duration,
                starts=settings.process.sample_starts,
                on_apply=self._apply,
                waveforms=WaveformLoader(PeakCache()),
                open_in_window=settings.ui.listening_in_window,
                on_toast=self._toast,
                on_closed=self._on_closed,
            )
        self._dialog.present(self._parent())

    def close(self) -> None:
        dialog, self._dialog = self._dialog, None
        if dialog is not None:
            dialog.close()

    def _on_closed(self) -> None:
        self._dialog = None

    def _apply(self, edits: dict[str, float | None]) -> None:
        settings = self._settings()
        # The input list may have changed while the dialog was open.
        current = {os.path.abspath(path) for path in settings.process.input_paths}
        starts = dict(settings.process.sample_starts)
        for path, start in edits.items():
            if path not in current:
                continue
            if start is None:
                starts.pop(path, None)
            else:
                starts[path] = round(start, 3)
        settings.process.sample_starts = starts
        error = self._save()
        if error:
            self._toast(error)
        self._on_applied()


__all__ = ["SampleRangeController"]
