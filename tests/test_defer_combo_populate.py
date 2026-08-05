"""Load-time auto-expand must not hash model combos synchronously (F1)."""

from __future__ import annotations

import unittest
from unittest import mock

from ui.views.base import MethodView


class DeferComboPopulateTests(unittest.TestCase):
    def test_ensure_defers_to_idle_while_restoring(self) -> None:
        view = MethodView.__new__(MethodView)
        view._model_combos_populated = False
        view._defer_combo_populate = True
        view._combo_populate_idle_scheduled = False
        calls: list = []

        def fake_idle(func, *args, **kwargs):
            calls.append(("idle", func))

        with mock.patch("ui.dispatch.idle_on_main", side_effect=fake_idle):
            view._ensure_model_combos_populated()
            # Second notify while still deferred must not schedule again.
            view._ensure_model_combos_populated()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "idle")
        self.assertTrue(view._combo_populate_idle_scheduled)

    def test_ensure_runs_inline_when_not_deferring(self) -> None:
        view = MethodView.__new__(MethodView)
        view._model_combos_populated = False
        view._defer_combo_populate = False
        view._combo_populate_idle_scheduled = False
        ran = {"n": 0}

        def populate_now() -> None:
            ran["n"] += 1
            view._model_combos_populated = True

        view._populate_model_combos_now = populate_now  # type: ignore[method-assign]
        with mock.patch("ui.dispatch.idle_on_main") as idle:
            view._ensure_model_combos_populated()
        idle.assert_not_called()
        self.assertEqual(ran["n"], 1)


if __name__ == "__main__":
    unittest.main()
