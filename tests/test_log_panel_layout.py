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

    def test_revealer_transitions_update_window_clearance_once(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from gi.repository import Adw

        from core.access_policy import access_policy
        from core.settings import Settings
        from ui.window import MainWindow

        app = Adw.Application(application_id="org.uvr.test.log-clearance")
        app.register()
        scratch = self.enterContext(tempfile.TemporaryDirectory())
        settings = Settings.defaults()
        settings.path = str(Path(scratch) / "settings.json")
        with (
            access_policy(allow_network=False, allow_metadata_writes=False),
            patch("ui.context.Settings.load", return_value=settings),
        ):
            window = MainWindow(application=app)
        panel = window.log_panel
        self.addCleanup(window.set_application, None)
        self.addCleanup(window._unsubscribe_model_events)
        self.addCleanup(panel.set_start_blocked_reason, None)
        self.addCleanup(window.set_visible, False)
        panel.set_start_blocked_reason(None)
        window.present()
        self.settle(window.get_mapped)
        for expanded in (True, False):
            with (
                self.subTest(log_expanded=expanded),
                patch.object(
                    window,
                    "_sync_options_bottom_clearance",
                    wraps=window._sync_options_bottom_clearance,
                ) as sync,
            ):
                panel.set_expanded(expanded)
                self.settle(
                    lambda expanded=expanded: panel._log_revealer.get_child_revealed() == expanded
                )
                sync.assert_called_once_with()
        for visible in (True, False):
            with (
                self.subTest(progress_visible=visible),
                patch.object(
                    window,
                    "_sync_options_bottom_clearance",
                    wraps=window._sync_options_bottom_clearance,
                ) as sync,
            ):
                panel.set_progress_text("Working" if visible else "")
                self.settle(
                    lambda visible=visible: panel._progress_revealer.get_child_revealed() == visible
                )
                sync.assert_called_once_with()
