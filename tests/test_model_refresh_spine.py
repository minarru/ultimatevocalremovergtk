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

    def test_external_refresh_repaints_without_invalidating(self) -> None:
        """`_refresh_models` is repaint-only.

        Invalidation moved into core, ahead of the notification: downloads
        publish through the shared finalizer and catalogue refinements through
        the presentation event, so no UI path invalidates any more.
        """
        window = _window()

        with mock.patch.object(MainWindow, "_apply_model_refresh") as apply_refresh:
            MainWindow._refresh_models(window, source="download_center")

        window.context.repo.invalidate_models.assert_not_called()
        apply_refresh.assert_called_once_with(source="download_center")

    def test_applying_clears_the_deferred_marker(self) -> None:
        window = _window()
        window._deferred_model_refresh = "repo"

        MainWindow._apply_model_refresh(window)

        self.assertIsNone(window._deferred_model_refresh)


class RepositorySubscriptionTests(unittest.TestCase):
    def test_repository_flush_does_not_schedule_a_second_refresh(self) -> None:
        """The repaint must not re-enter the coalescer and loop forever."""
        window = _window()
        window._model_refresh_armed = False
        scheduled: list[Any] = []

        with mock.patch(
            "ui.window.idle_on_main", side_effect=lambda fn, *a, **k: scheduled.append(fn)
        ):
            MainWindow._on_models_changed(window)
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


class DualEventSubscriptionTests(unittest.TestCase):
    """One callback, one coalescer, two repository events.

    A presentation-only refinement (a friendlier catalogue label) and a full
    inventory change both have to repaint the pickers, but only the latter may
    stale a resolved plan. They therefore arrive as two events and must still
    collapse into one repaint.
    """

    def test_initialization_subscribes_the_same_callback_to_both(self) -> None:
        window = _window()

        MainWindow._subscribe_model_events(window)

        repo = window.context.repo
        repo.subscribe_models_changed.assert_called_once_with(
            window._on_models_changed
        )
        repo.subscribe_model_presentation_changed.assert_called_once_with(
            window._on_models_changed
        )

    def test_closing_unsubscribes_that_callback_from_both(self) -> None:
        window = _window()

        MainWindow._unsubscribe_model_events(window)

        repo = window.context.repo
        repo.unsubscribe_models_changed.assert_called_once_with(
            window._on_models_changed
        )
        repo.unsubscribe_model_presentation_changed.assert_called_once_with(
            window._on_models_changed
        )

    def test_either_event_schedules_one_idle_flush(self) -> None:
        for label in ("inventory", "presentation"):
            with self.subTest(event=label):
                window = _window()
                window._model_refresh_armed = False
                with mock.patch("ui.window.idle_on_main") as idle:
                    MainWindow._on_models_changed(window)
                idle.assert_called_once_with(window._flush_models_changed)

    def test_both_events_before_the_idle_callback_cause_one_repaint(self) -> None:
        window = _window()
        window._model_refresh_armed = False

        with mock.patch("ui.window.idle_on_main") as idle:
            MainWindow._on_models_changed(window)  # inventory event
            MainWindow._on_models_changed(window)  # presentation event

        idle.assert_called_once_with(window._flush_models_changed)

        with mock.patch.object(MainWindow, "_apply_model_refresh") as apply_refresh:
            MainWindow._flush_models_changed(window)

        apply_refresh.assert_called_once()

    def test_repaint_never_calls_either_invalidation(self) -> None:
        window = _window()

        MainWindow._apply_model_refresh(window)

        window.context.repo.invalidate_models.assert_not_called()
        window.context.repo.invalidate_model_presentation.assert_not_called()

    def test_refresh_models_is_repaint_only(self) -> None:
        """Invalidation happens in core before the notification, never here."""
        window = _window()

        MainWindow._refresh_models(window, source="download_center")

        window.context.repo.invalidate_models.assert_not_called()
        window.context.repo.invalidate_model_presentation.assert_not_called()

    def test_an_active_run_defers_and_coalesces_the_repaint(self) -> None:
        window = _window()
        controller = mock.MagicMock()
        controller.is_running.return_value = True
        window._run_controller = controller
        window._model_refresh_armed = False

        with mock.patch("ui.window.idle_on_main") as idle:
            MainWindow._on_models_changed(window)
            MainWindow._on_models_changed(window)
        idle.assert_called_once_with(window._flush_models_changed)

        with mock.patch.object(MainWindow, "_apply_model_refresh") as apply_refresh:
            MainWindow._flush_models_changed(window)

        apply_refresh.assert_not_called()
        self.assertEqual(window._deferred_model_refresh, "repository")
