"""Download Center refresh failure and offline fallback behavior."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE
from core.model_scores import ARCH_FILTER_ALL, PURPOSE_VOCALS
from ui.download_center import DownloadCenterWindow


def _bare_refresh_window() -> DownloadCenterWindow:
    win = object.__new__(DownloadCenterWindow)
    win._refreshing = True
    win._catalogue_online = True
    win._catalogue_notice = ""
    win._available = {MDX_ARCH_TYPE: ["Existing Vocal Model"]}
    win._unsupported = {}
    win.refresh_button = mock.MagicMock()
    win._refresh_spinner = mock.MagicMock()
    win.status_label = mock.MagicMock()
    win.download_button = mock.MagicMock()
    win._rebuild_catalogue = mock.MagicMock()
    win._update_tab_counts = mock.MagicMock()
    win._update_status_from_catalogue = mock.MagicMock()
    win._update_download_button = mock.MagicMock()
    win._ensure_background_listeners = mock.MagicMock()
    win._schedule_stem_yaml_fetches = mock.MagicMock()
    win._set_catalogue_page_message = mock.MagicMock()
    win._toast = mock.MagicMock()
    win.manager = mock.MagicMock()
    win._pinned_snapshot = None
    win._pending_source_delta = False
    return win


class RefreshResilienceTests(unittest.TestCase):
    def test_offline_refresh_retains_the_previous_catalogue(self) -> None:
        win = _bare_refresh_window()

        win._refresh_done(False, {}, {})

        self.assertEqual(win._available, {MDX_ARCH_TYPE: ["Existing Vocal Model"]})
        self.assertIn("showing saved catalogue", win._catalogue_notice)
        cast(Any, win._rebuild_catalogue).assert_called_once_with()
        cast(Any, win._set_catalogue_page_message).assert_not_called()

    def test_refresh_exception_restores_controls_and_keeps_rows(self) -> None:
        win = _bare_refresh_window()

        win._refresh_failed("bad payload")

        self.assertFalse(win._refreshing)
        cast(Any, win.refresh_button.set_sensitive).assert_called_once_with(True)
        cast(Any, win._refresh_spinner.stop).assert_called_once_with()
        cast(Any, win._update_download_button).assert_called_once_with()
        cast(Any, win._toast).assert_called_once_with("Couldn't refresh catalogue: bad payload")

    def test_worker_marshals_unexpected_failures_to_refresh_failed(self) -> None:
        win = _bare_refresh_window()
        cast(Any, win).manager = mock.MagicMock()
        cast(Any, win.manager.refresh).side_effect = RuntimeError("broken merge")
        win.settings = SimpleNamespace(process=SimpleNamespace(auto_update_model_params=False))
        callbacks: list[tuple[object, tuple[object, ...]]] = []

        with (
            mock.patch(
                "ui.download_center.idle_on_main",
                side_effect=lambda callback, *args: callbacks.append((callback, args)),
            ),
            mock.patch("ui.errorlog.log_error"),
        ):
            win._refresh_worker()

        self.assertEqual(callbacks, [(win._refresh_failed, ("broken merge",))])


class MatchingCountTests(unittest.TestCase):
    def test_count_honors_purpose_and_includes_visible_unsupported_rows(self) -> None:
        win = object.__new__(DownloadCenterWindow)
        win._available = {MDX_ARCH_TYPE: ["Lead Vocal Model", "Karaoke Instrumental Model"]}
        win._unsupported = {MDX_ARCH_TYPE: [("Future Vocal Model", "needs a newer build")]}
        win._hide_unsupported = False
        win._purpose = PURPOSE_VOCALS
        win._arch_filter = ARCH_FILTER_ALL
        cast(Any, win).manager = SimpleNamespace(catalogue_meta={})

        self.assertEqual(win._matching_count(MDX_ARCH_TYPE, "model"), 2)

    def test_purpose_only_filter_reports_the_visible_count(self) -> None:
        win = object.__new__(DownloadCenterWindow)
        win._available = {MDX_ARCH_TYPE: ["Lead Vocal Model", "Karaoke Model"]}
        win._unsupported = {}
        win._hide_unsupported = False
        win._refreshing = False
        win._purpose = PURPOSE_VOCALS
        win._arch_filter = MDX_ARCH_TYPE
        win._catalogue_notice = ""
        win._row_checks = {}
        win._stack_pages = {}
        win.download_button = mock.MagicMock()
        win.status_label = mock.MagicMock()
        win.stack = mock.MagicMock()
        search = mock.MagicMock()
        search.get_text.return_value = ""
        win._search_entries = {MDX_ARCH_TYPE: search}
        win._search_entry = search
        cast(Any, win).manager = SimpleNamespace(catalogue_meta={})

        win._update_download_button()

        win.status_label.set_label.assert_called_once_with("1 vocals model in MDX-Net")


if __name__ == "__main__":
    unittest.main()
