"""The lazy-population dance, extracted from its two copies.

`MethodView` and `VocalSplitRow` both implemented: notify::expanded handler ->
bail if already populated or collapsed -> if a settings restore is in flight,
schedule one idle pass instead of populating inline -> populate -> latch. Two
copies drifted (only one had the collapsed early-out), so it lives in one place
now.
"""

from __future__ import annotations

import unittest
from typing import Any, List

from ui.widgets.lazy_populate import LazyPopulator


class _Harness:
    def __init__(self, *, expanded: bool = False) -> None:
        self.expanded = expanded
        self.populates = 0
        self.idle_calls: List[Any] = []
        self.populator = LazyPopulator(
            is_expanded=lambda: self.expanded,
            populate=self._populate,
            schedule_idle=self.idle_calls.append,
        )

    def _populate(self) -> None:
        self.populates += 1

    def run_idle(self) -> None:
        pending, self.idle_calls[:] = list(self.idle_calls), []
        for callback in pending:
            callback()


class EnsureTests(unittest.TestCase):
    def test_collapsed_does_not_populate(self) -> None:
        harness = _Harness(expanded=False)
        harness.populator.ensure()
        self.assertEqual(harness.populates, 0)

    def test_expanded_populates_once(self) -> None:
        harness = _Harness(expanded=True)
        harness.populator.ensure()
        harness.populator.ensure()
        self.assertEqual(harness.populates, 1)

    def test_ready_reports_the_latch(self) -> None:
        harness = _Harness(expanded=True)
        self.assertFalse(harness.populator.ready)
        harness.populator.ensure()
        self.assertTrue(harness.populator.ready)


class DeferTests(unittest.TestCase):
    def test_repeated_ensure_while_deferred_schedules_one_idle(self) -> None:
        harness = _Harness(expanded=True)
        with harness.populator.defer():
            for _ in range(5):
                harness.populator.ensure()
        self.assertEqual(len(harness.idle_calls), 1)
        self.assertEqual(harness.populates, 0, "deferred work must not run inline")

        harness.run_idle()
        self.assertEqual(harness.populates, 1)

    def test_defer_restores_the_previous_state(self) -> None:
        """Nested defers happen: a refresh can arrive during a settings restore."""
        harness = _Harness(expanded=True)
        with harness.populator.defer():
            with harness.populator.defer():
                pass
            harness.populator.ensure()
            self.assertEqual(harness.populates, 0, "still deferred after the inner exit")
        harness.populator.invalidate()
        harness.populator.ensure()
        self.assertEqual(harness.populates, 1, "inline again once the outer exits")

    def test_defer_restores_on_exception(self) -> None:
        harness = _Harness(expanded=True)
        with self.assertRaises(ValueError):
            with harness.populator.defer():
                raise ValueError("boom")
        harness.populator.ensure()
        self.assertEqual(harness.populates, 1)

    def test_a_deferred_pass_that_lands_collapsed_does_not_populate(self) -> None:
        """The user can collapse the row before the idle fires."""
        harness = _Harness(expanded=True)
        with harness.populator.defer():
            harness.populator.ensure()
        harness.expanded = False
        harness.run_idle()
        self.assertEqual(harness.populates, 0)


class InvalidateTests(unittest.TestCase):
    def test_invalidate_while_expanded_repopulates(self) -> None:
        harness = _Harness(expanded=True)
        harness.populator.ensure()
        harness.populator.invalidate()
        self.assertEqual(harness.populates, 2)

    def test_invalidate_while_collapsed_defers_to_the_next_expand(self) -> None:
        """The laziness pin: populating is the expensive half."""
        harness = _Harness(expanded=False)
        harness.populator.invalidate()
        self.assertEqual(harness.populates, 0)

        harness.expanded = True
        harness.populator.ensure()
        self.assertEqual(harness.populates, 1)

    def test_invalidate_repopulates_through_idle_when_asked(self) -> None:
        harness = _Harness(expanded=True)
        harness.populator.ensure()
        harness.populator.invalidate(defer=True)
        self.assertEqual(harness.populates, 1, "not inline")
        harness.run_idle()
        self.assertEqual(harness.populates, 2)


if __name__ == "__main__":
    unittest.main()
