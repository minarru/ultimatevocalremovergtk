"""Changing Sort must reorder rows in place, not rebuild the catalogue.

_rebuild_catalogue reconstructs all ~469 Adw.ActionRows (67 ms measured) and
then has to re-apply every checked selection to undo its own destructiveness.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class DownloadCenterSortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.dc-sort")
        cls._app.register()

    def _window(self):
        from ui.download_center import DownloadCenterWindow

        return DownloadCenterWindow.__new__(DownloadCenterWindow)

    def test_sort_change_does_not_rebuild(self) -> None:
        from ui.download_center import SORT_OPTIONS

        window = self._window()
        window._sort_mode = SORT_OPTIONS[0][0]
        window.sort_row = mock.MagicMock()
        window._list_boxes = {}

        with mock.patch.object(
            type(window), "_rebuild_catalogue", autospec=True
        ) as rebuild, mock.patch.object(
            type(window), "_invalidate_all_sorts", autospec=True
        ) as invalidate, mock.patch(
            "ui.download_center.get_combo_value", return_value=SORT_OPTIONS[1][1]
        ):
            window._on_sort_changed()

        rebuild.assert_not_called()
        invalidate.assert_called_once()
        self.assertEqual(window._sort_mode, SORT_OPTIONS[1][0])

    def test_sdr_sort_key_orders_high_scores_first(self) -> None:
        from core.model_scores import SORT_SDR
        from gi.repository import Adw
        from ui.widget_state import stash

        window = self._window()
        window._sort_mode = SORT_SDR

        high = Adw.ActionRow()
        stash(high, "_uvr_sort_name", "high")
        stash(high, "_uvr_sdr", 12.0)
        stash(high, "_uvr_unsupported", False)

        low = Adw.ActionRow()
        stash(low, "_uvr_sort_name", "low")
        stash(low, "_uvr_sdr", 3.0)
        stash(low, "_uvr_unsupported", False)

        self.assertLess(window._compare_rows(high, low), 0)

    def test_unsupported_rows_sort_last(self) -> None:
        from core.model_scores import SORT_NAME
        from gi.repository import Adw
        from ui.widget_state import stash

        window = self._window()
        window._sort_mode = SORT_NAME

        supported = Adw.ActionRow()
        stash(supported, "_uvr_sort_name", "zzz")
        stash(supported, "_uvr_sdr", None)
        stash(supported, "_uvr_unsupported", False)

        unsupported = Adw.ActionRow()
        stash(unsupported, "_uvr_sort_name", "aaa")
        stash(unsupported, "_uvr_sdr", None)
        stash(unsupported, "_uvr_unsupported", True)

        self.assertLess(window._compare_rows(supported, unsupported), 0)


if __name__ == "__main__":
    unittest.main()
