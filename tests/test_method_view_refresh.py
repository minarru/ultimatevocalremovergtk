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
    view._model_combos_populated = True
    view._defer_combo_populate = False
    view._combo_populate_idle_scheduled = False
    view._model_combos = []
    if secondary is not None:
        view.secondary_expander = _Expander(secondary)
    if preproc is not None:
        view.preproc_expander = _Expander(preproc)
    return view


class RepopulateVisibleCombosTests(unittest.TestCase):
    def test_open_secondary_expander_repopulates(self) -> None:
        view = _view(secondary=True)
        with mock.patch.object(MethodView, "_ensure_model_combos_populated") as ensure:
            MethodView._repopulate_model_combos_if_visible(view)
        ensure.assert_called_once_with()

    def test_open_preproc_expander_repopulates(self) -> None:
        view = _view(secondary=False, preproc=True)
        with mock.patch.object(MethodView, "_ensure_model_combos_populated") as ensure:
            MethodView._repopulate_model_combos_if_visible(view)
        ensure.assert_called_once_with()

    def test_collapsed_expanders_do_not_repopulate(self) -> None:
        """Laziness pin: populating resolves model lists, which hashes
        checkpoints. A section nobody can see must not pay for it."""
        view = _view(secondary=False, preproc=False)
        with mock.patch.object(MethodView, "_ensure_model_combos_populated") as ensure:
            MethodView._repopulate_model_combos_if_visible(view)
        ensure.assert_not_called()

    def test_view_without_expanders_is_a_noop(self) -> None:
        """VR/MDX views have no pre-process expander; some have neither."""
        view = _view()
        with mock.patch.object(MethodView, "_ensure_model_combos_populated") as ensure:
            MethodView._repopulate_model_combos_if_visible(view)
        ensure.assert_not_called()

    def test_repopulation_is_deferred_to_idle(self) -> None:
        """It runs as the download toast paints; keep it off the main loop."""
        view = _view(secondary=True)
        view._model_combos_populated = False
        calls: list[Any] = []

        with mock.patch("ui.dispatch.idle_on_main", side_effect=lambda fn, *a, **k: calls.append(fn)):
            MethodView._repopulate_model_combos_if_visible(view)

        self.assertEqual(len(calls), 1)
        self.assertTrue(view._combo_populate_idle_scheduled)
        # The deferral flag must be restored, or every later expand defers too.
        self.assertFalse(view._defer_combo_populate)


class RefreshModelsTests(unittest.TestCase):
    def _refreshable_view(self, *, secondary: bool) -> Any:
        view = _view(secondary=secondary)
        view._loading = False
        view.populate_models = mock.MagicMock()
        view.update_stem_labels = mock.MagicMock()
        return view

    def test_refresh_models_repopulates_an_open_expander(self) -> None:
        view = self._refreshable_view(secondary=True)
        with mock.patch.object(MethodView, "_ensure_model_combos_populated") as ensure:
            MethodView.refresh_models(view)
        view.populate_models.assert_called_once_with()
        ensure.assert_called_once_with()

    def test_refresh_models_still_invalidates_a_collapsed_expander(self) -> None:
        view = self._refreshable_view(secondary=False)
        view._model_combos = [{"row": object(), "key": "k", "provider": list, "ready": True}]
        with mock.patch.object(MethodView, "_ensure_model_combos_populated") as ensure:
            MethodView.refresh_models(view)
        ensure.assert_not_called()
        self.assertFalse(view._model_combos_populated)
        self.assertFalse(view._model_combos[0]["ready"])

    def test_change_defaults_repopulates_an_open_expander(self) -> None:
        view = self._refreshable_view(secondary=True)
        view.context = mock.MagicMock()
        view._window_root = mock.MagicMock(return_value=None)
        with mock.patch(
            "ui.dialogs.model_params.show_change_defaults_dialog"
        ), mock.patch.object(MethodView, "_ensure_model_combos_populated") as ensure:
            MethodView._on_change_defaults(view, object())
        ensure.assert_called_once_with()
        self.assertFalse(view._model_combos_populated)


if __name__ == "__main__":
    unittest.main()
