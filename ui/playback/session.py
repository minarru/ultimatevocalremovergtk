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
