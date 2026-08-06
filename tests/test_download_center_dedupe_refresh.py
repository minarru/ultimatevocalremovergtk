"""Download Center reaction to the post-warmup content dedupe.

The identity HEAD pass lands tens of seconds after the window has rendered, so
rows the dedupe removed have to leave the list without a full rebuild — a
rebuild would reset the user's scroll position mid-browse.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE


def _bare_window() -> Any:
    from ui.download_center import DownloadCenterWindow

    win = object.__new__(DownloadCenterWindow)
    win.manager = mock.MagicMock()
    win._catalogue_refresh_armed = False
    win._row_checks = {}
    win._row_actions = {}
    win._size_lookup_ids = {}
    win._list_boxes = {}
    win._available = {}
    win._unsupported = {}
    return win


def _seed_row(win: Any, arch: str, name: str, *, checked: bool = False) -> Any:
    action = mock.MagicMock(name=f"row:{name}")
    check = mock.MagicMock(name=f"check:{name}")
    check.get_active.return_value = checked
    win._row_actions[(arch, name)] = action
    win._row_checks[(arch, name)] = check
    win._size_lookup_ids[(arch, name)] = 1
    win._list_boxes.setdefault(arch, mock.MagicMock(name=f"listbox:{arch}"))
    return action


class CatalogueRefreshDebounceTests(unittest.TestCase):
    def test_repeated_notifies_arm_one_timeout(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        timeout_calls: list[tuple[int, Any]] = []

        with mock.patch(
            "gi.repository.GLib.timeout_add",
            side_effect=lambda ms, cb: (timeout_calls.append((ms, cb)), 1)[1],
        ), mock.patch(
            "ui.download_center.idle_on_main", side_effect=lambda fn: fn()
        ):
            for _ in range(5):
                DownloadCenterWindow._schedule_catalogue_row_refresh(win)

        self.assertTrue(win._catalogue_refresh_armed)
        self.assertEqual(len(timeout_calls), 1)
        self.assertEqual(timeout_calls[0][0], 250)

    def test_notify_hops_to_main_thread(self) -> None:
        """The manager fires this from the size-warmup thread."""
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        idle_calls: list[Any] = []

        with mock.patch(
            "ui.download_center.idle_on_main",
            side_effect=lambda fn, *a, **k: idle_calls.append(fn),
        ):
            DownloadCenterWindow._schedule_catalogue_row_refresh(win)

        self.assertEqual(idle_calls, [win._arm_catalogue_row_refresh])


class CatalogueRowRemovalTests(unittest.TestCase):
    def test_removes_only_rows_the_dedupe_dropped(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        kept = _seed_row(win, MDX_ARCH_TYPE, "Kept Model")
        dropped = _seed_row(win, MDX_ARCH_TYPE, "Rehosted Copy")
        other_tab = _seed_row(win, VR_ARCH_TYPE, "VR Model")

        win.manager.available_downloads.return_value = {
            MDX_ARCH_TYPE: ["Kept Model"],
            VR_ARCH_TYPE: ["VR Model"],
        }
        win.manager.unsupported_downloads.return_value = {}
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()

        DownloadCenterWindow._flush_catalogue_row_refresh(win)

        win._list_boxes[MDX_ARCH_TYPE].remove.assert_called_once_with(dropped)
        win._list_boxes[VR_ARCH_TYPE].remove.assert_not_called()
        self.assertNotIn((MDX_ARCH_TYPE, "Rehosted Copy"), win._row_actions)
        self.assertNotIn((MDX_ARCH_TYPE, "Rehosted Copy"), win._row_checks)
        self.assertNotIn((MDX_ARCH_TYPE, "Rehosted Copy"), win._size_lookup_ids)
        self.assertIn((MDX_ARCH_TYPE, "Kept Model"), win._row_actions)
        self.assertIn((VR_ARCH_TYPE, "VR Model"), win._row_actions)
        self.assertIsNotNone(kept)
        self.assertIsNotNone(other_tab)

    def test_keeps_unsupported_rows_that_are_not_in_available(self) -> None:
        """Unsupported rows live in a second dict — comparing against
        ``available`` alone would sweep every one of them off the list."""
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        _seed_row(win, MDX_ARCH_TYPE, "Kept Model")
        _seed_row(win, MDX_ARCH_TYPE, "Broken Model")

        win.manager.available_downloads.return_value = {MDX_ARCH_TYPE: ["Kept Model"]}
        win.manager.unsupported_downloads.return_value = {
            MDX_ARCH_TYPE: [("Broken Model", "needs a newer build")]
        }
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()

        DownloadCenterWindow._flush_catalogue_row_refresh(win)

        win._list_boxes[MDX_ARCH_TYPE].remove.assert_not_called()
        self.assertIn((MDX_ARCH_TYPE, "Broken Model"), win._row_actions)

    def test_refreshes_button_when_a_checked_row_disappears(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        _seed_row(win, MDX_ARCH_TYPE, "Kept Model", checked=True)
        _seed_row(win, MDX_ARCH_TYPE, "Rehosted Copy", checked=True)

        win.manager.available_downloads.return_value = {MDX_ARCH_TYPE: ["Kept Model"]}
        win.manager.unsupported_downloads.return_value = {}
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()

        DownloadCenterWindow._flush_catalogue_row_refresh(win)

        win._update_download_button.assert_called_once_with()
        win._update_tab_counts.assert_called_once_with()
        # The surviving checkbox keeps its state: nothing rebuilt it.
        self.assertTrue(win._row_checks[(MDX_ARCH_TYPE, "Kept Model")].get_active())

    def test_no_op_when_nothing_was_dropped(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        _seed_row(win, MDX_ARCH_TYPE, "Kept Model")

        win.manager.available_downloads.return_value = {MDX_ARCH_TYPE: ["Kept Model"]}
        win.manager.unsupported_downloads.return_value = {}
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()

        DownloadCenterWindow._flush_catalogue_row_refresh(win)

        win._list_boxes[MDX_ARCH_TYPE].remove.assert_not_called()
        win._update_download_button.assert_not_called()


class CatalogueListenerWiringTests(unittest.TestCase):
    def test_background_listeners_subscribe_to_the_manager(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()

        with mock.patch("core.catalogue_stem_cache.subscribe"), mock.patch(
            "core.catalogue_stem_cache.ensure_worker_started"
        ):
            DownloadCenterWindow._ensure_background_listeners(win)

        win.manager.subscribe_catalogue_changed.assert_called_once_with(
            win._schedule_catalogue_row_refresh
        )


if __name__ == "__main__":
    unittest.main()
