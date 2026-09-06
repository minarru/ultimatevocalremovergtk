"""Update view keeps worker results and its action connected after layout loading."""

from __future__ import annotations

import os
import time
import types
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "Update view requires a GTK display",
)
class UpdateViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, GLib
        except (ImportError, ValueError) as exc:
            raise unittest.SkipTest(f"GTK unavailable: {exc}") from exc
        cls.app = Adw.Application(application_id="org.uvr.test.update-view")
        cls.app.register()
        cls.main_context = GLib.MainContext.default()

    def test_check_button_delivers_worker_result_to_visible_controls(self) -> None:
        from ui.updates import UpdateView

        manager = types.SimpleNamespace(
            update_status=lambda: {"version": "1.2.3", "upstream_base": "5.6"},
            check_release=lambda: {
                "is_online": True,
                "is_current": False,
                "latest": "2.0.0",
                "upgrade_instructions": "Run the installer after updating.",
            },
        )
        view = UpdateView(None, types.SimpleNamespace(download_manager=manager))
        self.assertFalse(view.upgrade_row.get_visible())
        view.update_button.emit("clicked")
        self.assertFalse(view.update_button.get_sensitive())
        deadline = time.monotonic() + 5
        while not view.update_button.get_sensitive() and time.monotonic() < deadline:
            self.main_context.iteration(False)
            time.sleep(0.001)
        self.assertTrue(view.update_button.get_sensitive(), "Update worker never reached GTK")
        self.assertIn("2.0.0", view.status_row.get_subtitle() or "")
        self.assertTrue(view.upgrade_row.get_visible())
        self.assertEqual(view.upgrade_row.get_subtitle(), "Run the installer after updating.")
        self.assertEqual(view.update_button.get_label(), "View release notes")

    def test_offline_result_keeps_retry_action_available(self) -> None:
        from ui.updates import UpdateView

        manager = types.SimpleNamespace(update_status=lambda: {"version": None})
        view = UpdateView(None, types.SimpleNamespace(download_manager=manager))
        view._check_done({"is_online": False})
        self.assertEqual(view.status_row.get_subtitle(), "Could not check for updates (offline)")
        self.assertEqual(view.update_button.get_label(), "Check again")
        self.assertTrue(view.update_button.get_sensitive())
        self.assertFalse(view.upgrade_row.get_visible())
