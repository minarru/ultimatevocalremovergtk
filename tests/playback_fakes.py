"""Fake playback engine and peak loader shared by the listening-tool tests."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from core.listening import REFERENCE_LABEL, ComparisonSet, Track
from core.waveform import Peaks


def _noop(*_a: object) -> None:
    return None


class FakeEngine:
    def __init__(self) -> None:
        self.on_position: Callable[[float], None] = _noop
        self.on_duration: Callable[[float], None] = _noop
        self.on_state: Callable[[bool], None] = _noop
        self.on_track_error: Callable[[int, str], None] = _noop
        self.on_error: Callable[[str], None] = _noop
        self.calls: list[tuple[Any, ...]] = []
        self._playing = False
        self._selected = 0
        self._loaded = False
        self._position = 0.0
        self._duration = 0.0

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def position(self) -> float:
        return self._position

    @property
    def selected(self) -> int:
        return self._selected

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0) -> None:
        self.calls.append(("load", tuple(t.path for t in tracks), selected, position))
        self._loaded = True
        self._selected = selected

    def play(self) -> None:
        self.calls.append(("play",))
        self._playing = True
        self.on_state(True)

    def pause(self) -> None:
        self.calls.append(("pause",))
        self._playing = False
        self.on_state(False)

    def toggle(self) -> None:
        self.pause() if self._playing else self.play()

    def seek(self, seconds: float) -> None:
        self.calls.append(("seek", seconds))
        self._position = seconds

    def select(self, index: int) -> None:
        self.calls.append(("select", index))
        self._selected = index

    def unload(self) -> None:
        self.calls.append(("unload",))
        self._loaded = False


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


def comparison_set(name: str, *labels: str) -> ComparisonSet:
    src = f"/in/{name}.wav"
    tracks = [Track(REFERENCE_LABEL, src, None, True)]
    tracks += [Track(label, f"/out/{name} ({label}).wav") for label in labels]
    return ComparisonSet(src, tuple(tracks))


__all__ = ["FakeEngine", "FakeLoader", "comparison_set"]
