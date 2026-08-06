"""An expander that is already open must repopulate on refresh.

`refresh_models` only cleared the latches; repopulation hung entirely off
`notify::expanded`, and GObject emits that only when the property actually
changes. So an expander the user had already opened when a download landed kept
showing the old model list until it was collapsed and reopened.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from ui.views.base import MethodView
from ui.widgets.lazy_populate import LazyPopulator


class _Expander:
    """Stands in for an Adw.ExpanderRow; only get_expanded() is consulted."""

    def __init__(self, expanded: bool) -> None:
        self._expanded = expanded

    def get_expanded(self) -> bool:
        return self._expanded


def _view(*, secondary: bool | None = None, preproc: bool | None = None) -> Any:
    # Bare instance: MethodView.__init__ builds real GTK rows. Typed Any so the
    # expander stubs below can stand in for Adw.ExpanderRow.
    view: Any = MethodView.__new__(MethodView)
    view._model_combos = []
    view._populating_models = False
    view.populates = 0
    if secondary is not None:
        view.secondary_expander = _Expander(secondary)
    if preproc is not None:
        view.preproc_expander = _Expander(preproc)

    def populate() -> None:
        view.populates += 1

    view._populator = LazyPopulator(
        is_expanded=lambda: MethodView._model_combo_section_open(view),
        populate=populate,
    )
    return view


class SectionOpenTests(unittest.TestCase):
    def test_either_expander_counts_as_open(self) -> None:
        """One latch covers both, so opening one populates the other's combos."""
        self.assertTrue(MethodView._model_combo_section_open(_view(secondary=True)))
        self.assertTrue(
            MethodView._model_combo_section_open(_view(secondary=False, preproc=True))
        )

    def test_all_collapsed_is_closed(self) -> None:
        view = _view(secondary=False, preproc=False)
        self.assertFalse(MethodView._model_combo_section_open(view))

    def test_view_without_expanders_is_closed(self) -> None:
        """VR/MDX views have no pre-process expander; some have neither."""
        self.assertFalse(MethodView._model_combo_section_open(_view()))


class RefreshModelsTests(unittest.TestCase):
    def _refreshable_view(self, **kwargs: Any) -> Any:
        view = _view(**kwargs)
        view._loading = False
        view.populate_models = mock.MagicMock()
        view.update_stem_labels = mock.MagicMock()
        return view

    def test_refresh_repopulates_an_open_expander(self) -> None:
        view = self._refreshable_view(secondary=True)
        view._populator.ensure()
        self.assertEqual(view.populates, 1)

        with mock.patch(
            "ui.widgets.lazy_populate.idle_on_main", side_effect=lambda fn, *a, **k: fn()
        ):
            MethodView.refresh_models(view)

        view.populate_models.assert_called_once_with()
        self.assertEqual(view.populates, 2, "an open expander must re-resolve")

    def test_refresh_defers_the_repopulate_to_idle(self) -> None:
        """It runs as the download toast paints; keep it off the main loop."""
        view = self._refreshable_view(secondary=True)
        view._populator.ensure()
        scheduled: list[Any] = []

        with mock.patch(
            "ui.widgets.lazy_populate.idle_on_main",
            side_effect=lambda fn, *a, **k: scheduled.append(fn),
        ):
            MethodView.refresh_models(view)

        self.assertEqual(len(scheduled), 1)
        self.assertEqual(view.populates, 1, "not inline")
        scheduled[0]()
        self.assertEqual(view.populates, 2)

    def test_refresh_leaves_a_collapsed_expander_unpopulated(self) -> None:
        """Laziness pin: populating resolves model lists, which hashes
        checkpoints. A section nobody can see must not pay for it."""
        view = self._refreshable_view(secondary=False)
        view._model_combos = [
            {"row": object(), "key": "k", "provider": list, "ready": True}
        ]

        MethodView.refresh_models(view)

        self.assertEqual(view.populates, 0)
        self.assertFalse(view._populator.ready)
        self.assertFalse(view._model_combos[0]["ready"])

    def test_change_defaults_repopulates_an_open_expander(self) -> None:
        view = self._refreshable_view(secondary=True)
        view._populator.ensure()
        view.context = mock.MagicMock()
        view._window_root = mock.MagicMock(return_value=None)

        with mock.patch(
            "ui.dialogs.model_params.show_change_defaults_dialog"
        ), mock.patch(
            "ui.widgets.lazy_populate.idle_on_main", side_effect=lambda fn, *a, **k: fn()
        ):
            MethodView._on_change_defaults(view, object())

        self.assertEqual(view.populates, 2)


if __name__ == "__main__":
    unittest.main()
