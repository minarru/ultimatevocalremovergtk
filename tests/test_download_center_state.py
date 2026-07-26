"""Regression tests for Download Center selection/size-lookup state bugs.

Covers two fixes:
  * Sort changes rebuilt the catalogue and silently dropped every checked
    selection (unlike Purpose filtering, which only invalidates the filter).
  * The size-lookup stale-result guard used one window-wide counter instead
    of a per-row id, so checking a second model before the first's async
    lookup returned could permanently strand that row on "Looking up size…".
"""

from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import MagicMock, patch


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class DownloadCenterStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.download-center-state")
        cls._app.register()

    def _make_bare_window(self):
        from core.model_scores import PURPOSE_ALL, SORT_NAME
        from gi.repository import Adw, Gtk
        from ui.download_center import _NETWORKS, DownloadCenterWindow

        # Derived from _NETWORKS rather than hardcoded so adding a network tab
        # cannot silently break this fixture.
        arches = [arch for _label, arch in _NETWORKS]

        win = object.__new__(DownloadCenterWindow)
        win.manager = MagicMock()
        win._available = {}
        win._catalogue_online = True
        win._refreshing = False
        win._sort_mode = SORT_NAME
        win._purpose = PURPOSE_ALL
        win._row_checks = {}
        win._row_actions = {}
        win._size_lookup_ids = {}
        win._search_entries = {}
        win._list_boxes = {arch: Gtk.ListBox() for arch in arches}
        win._empty_pages = {arch: Adw.StatusPage() for arch in arches}
        win.download_button = Gtk.Button()
        win.status_label = Gtk.Label()
        win.stack = Gtk.Stack()
        win._stack_pages = {}
        return win

    def test_rebuild_catalogue_preserves_checked_selection(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE

        win = self._make_bare_window()
        win._available = {MDX_ARCH_TYPE: ["Model A", "Model B"]}
        win._rebuild_catalogue()

        key = (MDX_ARCH_TYPE, "Model A")
        win._row_checks[key].set_active(True)
        self.assertEqual(win._selected_entries(), [("Model A", MDX_ARCH_TYPE)])

        # Simulate changing the Sort dropdown: same available models, rebuilt
        # from scratch. The previously-checked model must still be checked.
        win._rebuild_catalogue()
        self.assertTrue(win._row_checks[key].get_active())
        self.assertEqual(win._selected_entries(), [("Model A", MDX_ARCH_TYPE)])

    def test_size_lookup_guard_is_per_row_not_global(self) -> None:
        from bundled.constants import MDX_ARCH_TYPE

        win = self._make_bare_window()
        win._available = {MDX_ARCH_TYPE: ["Model A", "Model B"]}
        win._rebuild_catalogue()

        key_a = (MDX_ARCH_TYPE, "Model A")
        key_b = (MDX_ARCH_TYPE, "Model B")

        a_started = threading.Event()
        a_release = threading.Event()

        def describe(name, arch):
            if name == "Model A":
                a_started.set()
                a_release.wait(timeout=5)
                return "12 MB"
            return "5 MB"

        win.manager.describe_selection_download_size.side_effect = describe

        apply_done = threading.Event()

        def fake_idle_on_main(func, *args, **kwargs):
            func(*args, **kwargs)
            apply_done.set()

        with patch("ui.download_center.idle_on_main", side_effect=fake_idle_on_main):
            win._lookup_row_size(key_a)
            a_started.wait(timeout=5)

            # Checking a second model while A's lookup is still in flight
            # used to bump a single shared counter and strand row A's
            # subtitle on "Looking up size…" forever.
            win._lookup_row_size(key_b)
            apply_done.wait(timeout=5)
            apply_done.clear()

            a_release.set()
            apply_done.wait(timeout=5)

        self.assertIn("12 MB", win._row_actions[key_a].get_subtitle() or "")
        self.assertIn("5 MB", win._row_actions[key_b].get_subtitle() or "")


if __name__ == "__main__":
    unittest.main()
