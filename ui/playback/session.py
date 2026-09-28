"""The latest run's comparison sets, in arrival order. No GTK."""

from __future__ import annotations

from core.listening import ComparisonSet


class ListeningSession:
    def __init__(self) -> None:
        self._sets: dict[str, ComparisonSet] = {}

    def clear(self) -> None:
        self._sets.clear()

    def add(self, cset: ComparisonSet) -> None:
        self._sets[cset.source] = cset

    def sets(self) -> tuple[ComparisonSet, ...]:
        return tuple(self._sets.values())

    def __len__(self) -> int:
        return len(self._sets)

    def __bool__(self) -> bool:
        return bool(self._sets)


__all__ = ["ListeningSession"]
