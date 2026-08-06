"""Load-time auto-expand must not hash model combos synchronously (F1).

The mechanics now live in `ui.widgets.lazy_populate.LazyPopulator` and are
covered directly in tests/test_lazy_populate.py. What remains here is the wiring:
that MethodView really routes through the helper.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from ui.views.base import MethodView
from ui.widgets.lazy_populate import LazyPopulator


def _view(*, expanded: bool) -> Any:
    view: Any = MethodView.__new__(MethodView)
    view._model_combos = []
    view._populating_models = False
    view._populator = LazyPopulator(
        is_expanded=lambda: expanded,
        populate=view._populate_model_combos_now,
    )
    return view


class DeferComboPopulateTests(unittest.TestCase):
    def test_ensure_defers_to_idle_while_restoring(self) -> None:
        view = _view(expanded=True)
        calls: list[Any] = []

        with mock.patch(
            "ui.widgets.lazy_populate.idle_on_main",
            side_effect=lambda func, *a, **k: calls.append(func),
        ):
            with view._populator.defer():
                view._ensure_model_combos_populated()
                # Second notify while still deferred must not schedule again.
                view._ensure_model_combos_populated()

        self.assertEqual(len(calls), 1)
        self.assertFalse(view._populator.ready)

    def test_ensure_runs_inline_when_not_deferring(self) -> None:
        view = _view(expanded=True)
        ran = {"n": 0}

        def populate_now() -> None:
            ran["n"] += 1

        view._populator = LazyPopulator(
            is_expanded=lambda: True, populate=populate_now
        )
        with mock.patch("ui.widgets.lazy_populate.idle_on_main") as idle:
            view._ensure_model_combos_populated()
        idle.assert_not_called()
        self.assertEqual(ran["n"], 1)

    def test_collapsed_section_populates_nothing(self) -> None:
        """MethodView used to lack this early-out, so a *collapse* notify
        populated the combos it was closing."""
        ran = {"n": 0}
        view: Any = MethodView.__new__(MethodView)
        view._populator = LazyPopulator(
            is_expanded=lambda: False,
            populate=lambda: ran.__setitem__("n", ran["n"] + 1),
        )
        view._ensure_model_combos_populated()
        self.assertEqual(ran["n"], 0)


if __name__ == "__main__":
    unittest.main()
