"""Keep playback inside a fixed range by wrapping an engine. No GTK.

The wrapper looks like any :class:`~ui.playback.engine.PlaybackControls`, so a
``CompareView`` drives it unchanged. Seeks are clamped to the range, and a
position that reaches the range end jumps back to its start, also when the
track itself ends there.
"""

from __future__ import annotations

from typing import Callable, Sequence

from core.listening import Track

from .engine import PlaybackControls

# Positions arrive every ~100 ms; treat anything this close to the end as the end.
_LOOP_EPSILON = 0.05


def _noop(*_args: object) -> None:
    return None


class RangeLoop:
    def __init__(self, engine: PlaybackControls) -> None:
        self._engine = engine
        self._start = 0.0
        self._length = 0.0
        # A pause the user asked for, as opposed to the engine stopping at the end.
        self._pausing = False
        self._ended = False
        # Set while the loop's own seek reports its position back synchronously.
        self._looping = False
        self.on_position: Callable[[float], None] = _noop
        self.on_duration: Callable[[float], None] = _noop
        self.on_state: Callable[[bool], None] = _noop
        self.on_track_error: Callable[[int, str], None] = _noop
        self.on_error: Callable[[str], None] = _noop
        engine.on_position = self._on_position
        engine.on_duration = lambda seconds: self.on_duration(seconds)
        engine.on_state = self._on_state
        engine.on_track_error = lambda index, message: self.on_track_error(index, message)
        engine.on_error = lambda message: self.on_error(message)

    # -- range -----------------------------------------------------------------

    def set_range(self, start: float, length: float) -> None:
        """Loop over ``length`` seconds from ``start``; 0 or less removes the range."""
        self._length = max(0.0, length)
        self._start = max(0.0, start) if self._length else 0.0

    @property
    def range_start(self) -> float:
        """The start, pulled back so the range fits a track whose length is known."""
        duration = self._engine.duration
        if duration > 0 and self._length:
            return min(self._start, max(0.0, duration - self._length))
        return self._start

    @property
    def range_end(self) -> float:
        end = self.range_start + self._length
        duration = self._engine.duration
        return min(end, duration) if duration > 0 else end

    def _clamp(self, seconds: float) -> float:
        if not self._length:
            return seconds
        return min(max(seconds, self.range_start), self.range_end)

    # -- PlaybackControls ------------------------------------------------------

    @property
    def playing(self) -> bool:
        return self._engine.playing

    @property
    def duration(self) -> float:
        return self._engine.duration

    @property
    def position(self) -> float:
        return self._engine.position

    @property
    def selected(self) -> int:
        return self._engine.selected

    @property
    def loaded(self) -> bool:
        return self._engine.loaded

    def load(self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0) -> None:
        self._ended = False
        if self._length:
            # The engine still knows only the previous track's length here.
            position = min(max(position, self._start), self._start + self._length)
        self._engine.load(tracks, selected=selected, position=position)

    def play(self) -> None:
        self._ended = False
        self._engine.play()

    def pause(self) -> None:
        self._pausing = True
        try:
            self._engine.pause()
        finally:
            self._pausing = False

    def toggle(self) -> None:
        if self._engine.playing:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        self._engine.seek(self._clamp(seconds))

    def select(self, index: int) -> None:
        self._engine.select(index)

    def unload(self) -> None:
        self._engine.unload()

    # -- engine callbacks ------------------------------------------------------

    def _on_state(self, playing: bool) -> None:
        # The engine stops by itself only at the end of the track.
        self._ended = not playing and not self._pausing
        self.on_state(playing)

    def _on_position(self, seconds: float) -> None:
        if not self._length or self._looping:
            self.on_position(seconds)
            return
        start = self.range_start
        # A failed duration query reports 0 and parks the playhead at 0, so the
        # end-of-stream flag is the only signal that the track finished.
        unknown_end = self._ended and self._engine.duration <= 0
        if unknown_end or seconds >= self.range_end - _LOOP_EPSILON:
            resume = self._ended
            self._seek_to_start(start)
            if resume and not self._engine.playing:
                self.play()
            return
        if seconds < start - _LOOP_EPSILON and self._engine.playing:
            self._seek_to_start(start)
            return
        self.on_position(seconds)

    def _seek_to_start(self, start: float) -> None:
        # The engine reports the new position at once; that report is not a loop.
        self._looping = True
        try:
            self._engine.seek(start)
        finally:
            self._looping = False


__all__ = ["RangeLoop"]
