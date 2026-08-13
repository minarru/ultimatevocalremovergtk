"""Every model-list widget must be reachable from one refresh.

`_apply_model_refresh` iterated `self._views`, which holds only the three
MethodViews. The ensemble page and both VocalSplitRow instances were
structurally unreachable -- a registry is the fix that stays correct when a
fourth consumer is added.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from ui.window import MainWindow


def _window() -> Any:
    """A bare MainWindow: __init__ builds the entire GTK tree."""
    window: Any = MainWindow.__new__(MainWindow)
    window.context = mock.MagicMock()
    window._run_controller = None
    window._deferred_model_refresh = None
    window._update_sep_banner = mock.MagicMock()
    window._views = [mock.MagicMock(name=f"view{i}") for i in range(3)]
    window._ensemble_page = mock.MagicMock(name="ensemble")
    window._audio_tools_page = mock.MagicMock(name="audio_tools")
    window.vocal_split_row = mock.MagicMock(name="vocal_split_row")
    for view in window._views:
        view.list_models.return_value = []
    return window


class ConsumerRegistryTests(unittest.TestCase):
    def test_every_consumer_is_refreshed(self) -> None:
        window = _window()

        MainWindow._apply_model_refresh(window)

        for view in window._views:
            view.refresh_models.assert_called_once_with()
        window._ensemble_page.refresh_models.assert_called_once_with()
        window._audio_tools_page.refresh_models.assert_called_once_with()
        window.vocal_split_row.refresh_models.assert_called_once_with()

    def test_repaint_does_not_reinvalidate_the_repository(self) -> None:
        """A repository notification must not schedule itself forever."""
        window = _window()

        MainWindow._apply_model_refresh(window)

        window.context.repo.invalidate_models.assert_not_called()
        window._views[0].refresh_models.assert_called_once_with()

    def test_a_missing_consumer_does_not_abort_the_rest(self) -> None:
        """Refresh can fire before the window finishes building."""
        window = _window()
        del window._ensemble_page

        MainWindow._apply_model_refresh(window)

        window.vocal_split_row.refresh_models.assert_called_once_with()


class RunDeferralTests(unittest.TestCase):
    def test_refresh_during_a_run_is_deferred(self) -> None:
        window = _window()
        window._run_controller = mock.MagicMock()
        window._run_controller.is_running.return_value = True

        with mock.patch.object(MainWindow, "_apply_model_refresh") as apply_refresh:
            MainWindow._refresh_models(window, source="repository")

        apply_refresh.assert_not_called()
        self.assertEqual(window._deferred_model_refresh, "repository")

    def test_refresh_outside_a_run_applies_immediately(self) -> None:
        window = _window()
        window._run_controller = mock.MagicMock()
        window._run_controller.is_running.return_value = False

        with mock.patch.object(MainWindow, "_apply_model_refresh") as apply_refresh:
            MainWindow._refresh_models(window, source="repository")

        apply_refresh.assert_called_once_with(source="repository")

    def test_external_refresh_invalidates_and_waits_for_repository_notification(self) -> None:
        window = _window()

        with mock.patch.object(MainWindow, "_apply_model_refresh") as apply_refresh:
            MainWindow._refresh_models(window, source="download_center")

        window.context.repo.invalidate_models.assert_called_once_with()
        apply_refresh.assert_not_called()

    def test_applying_clears_the_deferred_marker(self) -> None:
        window = _window()
        window._deferred_model_refresh = "repo"

        MainWindow._apply_model_refresh(window)

        self.assertIsNone(window._deferred_model_refresh)


class RepositorySubscriptionTests(unittest.TestCase):
    def test_repository_flush_does_not_schedule_a_second_refresh(self) -> None:
        window = _window()
        window._model_refresh_armed = False
        scheduled: list[Any] = []
        window.context.repo.invalidate_models.side_effect = lambda: MainWindow._on_models_changed(
            window
        )

        with mock.patch(
            "ui.window.idle_on_main", side_effect=lambda fn, *a, **k: scheduled.append(fn)
        ):
            MainWindow._refresh_models(window, source="download_center")
            self.assertEqual(len(scheduled), 1)
            scheduled.pop()()

        self.assertEqual(scheduled, [])
        for view in window._views:
            view.refresh_models.assert_called_once_with()

    def test_notification_coalesces_into_one_refresh(self) -> None:
        """A download batch invalidates more than once; the user should not
        pay for several full refreshes."""
        window = _window()
        window._model_refresh_armed = False
        scheduled: list[Any] = []

        with mock.patch(
            "ui.window.idle_on_main", side_effect=lambda fn, *a, **k: scheduled.append(fn)
        ):
            for _ in range(4):
                MainWindow._on_models_changed(window)

        self.assertEqual(len(scheduled), 1)

    def test_flushing_rearms_for_the_next_notification(self) -> None:
        window = _window()
        window._model_refresh_armed = False
        scheduled: list[Any] = []

        with mock.patch(
            "ui.window.idle_on_main", side_effect=lambda fn, *a, **k: scheduled.append(fn)
        ):
            MainWindow._on_models_changed(window)
            with mock.patch.object(MainWindow, "_refresh_models"):
                scheduled[0]()
            MainWindow._on_models_changed(window)

        self.assertEqual(len(scheduled), 2)

    def test_flush_routes_through_the_run_deferral(self) -> None:
        """Not straight to _apply_model_refresh, or a refresh could land
        mid-separation."""
        window = _window()
        window._model_refresh_armed = True

        with mock.patch.object(MainWindow, "_refresh_models") as refresh:
            MainWindow._flush_models_changed(window)

        refresh.assert_called_once_with(source="repository")
        self.assertFalse(window._model_refresh_armed)


if __name__ == "__main__":
    unittest.main()
