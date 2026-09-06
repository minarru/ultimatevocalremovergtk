import os
import time
import unittest
from collections.abc import Callable


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class LogPanelLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        Adw.init()
        if not Gtk.init_check():
            raise unittest.SkipTest('GTK display unavailable')

    def settle(self, predicate: Callable[[], bool]) -> None:
        from gi.repository import GLib

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            if predicate():
                return
            time.sleep(0.01)
        self.fail('Layout did not settle')

    def test_empty_state_centered_and_wrapped_hint_clearance(self):
        from gi.repository import Gtk

        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        window = Gtk.Window()
        window.set_default_size(640, 560)
        window.set_child(panel)
        panel._log_revealer.set_reveal_child(True)
        window.present()
        try:
            self.settle(lambda: panel._log_stack.get_width() > 0)
            outer = panel._log_stack.get_child_by_name('empty')
            assert outer is not None
            inner = outer.get_first_child()
            assert inner is not None
            bounds = inner.compute_bounds(outer)[1]
            self.assertAlmostEqual(
                bounds.get_x() + bounds.get_width() / 2, outer.get_width() / 2, delta=1
            )
            self.assertAlmostEqual(
                bounds.get_y() + bounds.get_height() / 2, outer.get_height() / 2, delta=1
            )
            base = panel.options_overlay_clearance()
            reason = 'Choose an installed model before starting processing. ' * 3
            panel.set_start_blocked_reason(reason)
            self.settle(lambda: panel._start_blocked_reason.get_height() > 0)
            self.assertGreater(panel.options_overlay_clearance(), base)
            self.assertGreater(panel._start_blocked_reason.get_height(), 20)
            panel.set_start_blocked_reason(None)
            self.assertFalse(panel._start_blocked_reason.get_visible())
            self.assertEqual(panel.options_overlay_clearance(), base)
        finally:
            window.set_visible(False)
