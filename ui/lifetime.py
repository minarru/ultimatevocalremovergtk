"""Main-loop delivery lifetime with explicit timer and subscription disposal."""

from __future__ import annotations

from typing import Callable, Protocol


class TimerScheduler(Protocol):
    def timeout_add(self, delay: int, callback: Callable[[], bool], /) -> int: ...
    def source_remove(self, ident: int, /) -> object: ...


class UiLifetime:
    def __init__(self) -> None:
        self.disposed = False
        self.generation = 0
        self._disposers: list[Callable[[], object]] = []
        self._timers: dict[int, TimerScheduler] = {}

    def own(self, dispose: Callable[[], object]) -> None:
        if self.disposed:
            dispose()
        else:
            self._disposers.append(dispose)

    def timeout(self, scheduler: TimerScheduler, delay: int, callback: Callable[[], bool]) -> None:
        if self.disposed:
            return
        generation = self.generation
        ident = 0

        def deliver() -> bool:
            if self.disposed or generation != self.generation:
                self._timers.pop(ident, None)
                return False
            repeat = callback()
            if not repeat:
                self._timers.pop(ident, None)
            return repeat

        ident = scheduler.timeout_add(delay, deliver)
        self._timers[ident] = scheduler

    def dispose(self) -> None:
        if self.disposed:
            return
        self.disposed = True
        self.generation += 1
        timers, self._timers = self._timers, {}
        for ident, scheduler in timers.items():
            scheduler.source_remove(ident)
        disposers, self._disposers = self._disposers, []
        for dispose in reversed(disposers):
            dispose()
