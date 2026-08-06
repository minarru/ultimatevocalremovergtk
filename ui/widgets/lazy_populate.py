"""Shared lazy population for expander-hosted model lists.

Resolving a model list hashes checkpoints, so sections that hold one populate on
first expand rather than at construction. `MethodView` and `VocalSplitRow` each
grew their own copy of that dance -- ready latch, deferral flag, one-shot idle
guard -- and the copies drifted: only one checked that the row was still
expanded before populating.

Composition, not a mixin or a base class. `VocalSplitRow` *is* an
`Adw.ExpanderRow` (a GObject) while `MethodView` is a plain object; a mixin
across that boundary fights PyGObject-stubs for no benefit. Holding one of these
costs an attribute and keeps this module free of any GTK import, so it unit-tests
without a display.

(`VocalSplitRow`'s objection to reusing `MethodView`'s helpers is about the
per-view row registries that `load`/`save` iterate. It does not apply here --
this touches no registry, only a callable pair.)
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator, Optional

from ..dispatch import idle_on_main


class LazyPopulator:
    """Populate an expander's contents on demand, at most once per invalidation.

    ``is_expanded`` and ``populate`` are the host's two hooks; ``schedule_idle``
    exists so tests can drive the deferred path without a main loop.
    """

    def __init__(
        self,
        *,
        is_expanded: Callable[[], bool],
        populate: Callable[[], None],
        schedule_idle: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self._is_expanded = is_expanded
        self._populate = populate
        self._schedule_idle = schedule_idle or self._default_schedule_idle
        self._ready = False
        self._deferrals = 0
        self._idle_scheduled = False

    @staticmethod
    def _default_schedule_idle(callback: Callable[[], None]) -> None:
        idle_on_main(callback)

    @property
    def ready(self) -> bool:
        """True once the contents have been populated for the current list."""
        return self._ready

    @property
    def deferring(self) -> bool:
        return self._deferrals > 0

    def ensure(self) -> None:
        """Populate if this section is on screen and not already populated.

        Safe to wire straight to ``notify::expanded``: it is a no-op on the
        collapse half of the signal.
        """
        if self._ready or not self._is_expanded():
            return
        if self.deferring:
            # One pass per deferral window, however many notifies arrive.
            if not self._idle_scheduled:
                self._idle_scheduled = True
                self._schedule_idle(self._run_deferred)
            return
        self._populate_now()

    def invalidate(self, *, defer: bool = False) -> None:
        """Drop the contents, repopulating only if this section is on screen.

        A collapsed section stays lazy and picks the new list up on its next
        expand. ``defer=True`` pushes an on-screen repopulate to idle, for
        callers refreshing while something else is painting.
        """
        self._ready = False
        if not self._is_expanded():
            return
        if defer:
            with self.defer():
                self.ensure()
            return
        self.ensure()

    @contextmanager
    def defer(self) -> Iterator[None]:
        """Within this block, ``ensure`` schedules an idle pass instead.

        Counted rather than boolean: a model refresh can arrive while a settings
        restore is already deferring, and the inner exit must not re-enable
        inline population for the outer one.
        """
        self._deferrals += 1
        try:
            yield
        finally:
            self._deferrals -= 1

    def _run_deferred(self) -> None:
        self._idle_scheduled = False
        # Re-checked, not assumed: the user may have collapsed the section
        # between scheduling and now.
        if self._ready or not self._is_expanded():
            return
        self._populate_now()

    def _populate_now(self) -> None:
        self._ready = True
        self._populate()
