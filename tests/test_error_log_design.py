"""Error Log updates preserve reading position and expose a floating tail action."""

import os
import time
import unittest
from collections.abc import Callable


@unittest.skipUnless(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"), "Needs GTK")
class ErrorLogDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from tests.private_gtk import require_private_gtk

        require_private_gtk()

    def setUp(self):
        from ui import errorlog

        errorlog.set_error_log("")
        self.window = errorlog.open_error_log(None)
        self.addCleanup(self.window.close)
        self.view = errorlog._ERROR_LOG_VIEW
        assert self.view is not None

    def wait_for(self, predicate: Callable[[], bool]):
        from gi.repository import GLib

        deadline = time.monotonic() + 5
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "Error Log did not settle")
            GLib.MainContext.default().iteration(False)
            time.sleep(0.005)

    def test_empty_state_and_clear_action(self):
        from ui import errorlog

        view = self.view
        assert view is not None
        self.assertFalse(self.window.get_modal())
        self.assertEqual(view.pages.get_visible_child_name(), "empty")
        self.assertFalse(view.copy_button.get_sensitive())
        self.assertFalse(view.clear_action.get_enabled())
        errorlog.set_error_log("RuntimeError: example")
        self.wait_for(lambda: view.copy_button.get_sensitive())
        self.assertEqual(view.pages.get_visible_child_name(), "log")
        view.clear_action.activate(None)
        self.wait_for(lambda: not view.copy_button.get_sensitive())
        self.assertEqual(view.pages.get_visible_child_name(), "empty")
        self.assertFalse(view.jump_revealer.get_reveal_child())

    def test_appends_preserve_reading_position_and_jump_resumes_following(self):
        from gi.repository import Gtk

        from core.error_log import append_error_log
        from ui import errorlog

        view = self.view
        assert view is not None
        errorlog.set_error_log("\n".join(f"Error line {i}" for i in range(300)))
        adj = view.scroll.get_vadjustment()
        self.wait_for(lambda: adj.get_upper() > adj.get_page_size() + 100)
        self.wait_for(lambda: adj.get_value() >= adj.get_upper() - adj.get_page_size() - 2)
        adj.set_value(100)
        self.assertTrue(view.jump_revealer.get_reveal_child())
        self.wait_for(view.jump_revealer.get_child_revealed)
        self.assertEqual(view.jump_revealer.get_halign(), Gtk.Align.CENTER)
        self.assertEqual(view.jump_revealer.get_valign(), Gtk.Align.END)
        self.assertEqual(view.jump_button.get_icon_name(), "uvr-go-bottom-symbolic")
        upper = adj.get_upper()
        append_error_log("\n".join("More details" for _ in range(100)))
        self.wait_for(lambda: adj.get_upper() > upper)
        self.assertAlmostEqual(adj.get_value(), 100, delta=2)
        view.jump_button.emit("clicked")
        self.wait_for(lambda: not view.jump_revealer.get_child_revealed())
        upper = adj.get_upper()
        append_error_log("\n".join("Latest details" for _ in range(100)))
        self.wait_for(lambda: adj.get_upper() > upper)
        self.wait_for(lambda: adj.get_value() >= adj.get_upper() - adj.get_page_size() - 2)
