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

    def test_empty_state_centered(self):
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
            empty = panel._log_stack.get_child_by_name('empty')
            assert empty is not None
            bounds = empty.compute_bounds(panel._log_stack)[1]
            self.assertAlmostEqual(
                bounds.get_x() + bounds.get_width() / 2,
                panel._log_stack.get_width() / 2,
                delta=1,
            )
            self.assertAlmostEqual(
                bounds.get_y() + bounds.get_height() / 2,
                panel._log_stack.get_height() / 2,
                delta=1,
            )
        finally:
            window.set_visible(False)

    def test_expanded_width_depends_on_content_and_not_progress_text(self):
        from gi.repository import Gtk

        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        window = Gtk.Window(default_width=1000, default_height=740)
        window.set_child(panel)
        window.present()
        self.addCleanup(window.set_visible, False)
        self.settle(lambda: panel.get_mapped() and panel.get_width() > 0)
        panel.set_expanded(True)
        self.settle(panel._log_revealer.get_child_revealed)
        empty_width = panel._log_stack.get_width()
        empty_height = panel._log_stack.get_height()
        panel.console.append("A long audio processing message " * 12 + "\n")
        self.settle(
            lambda: (
                panel._panel_clamp.get_maximum_size() == 560
                and panel._log_stack.get_width() > empty_width + 100
            )
        )
        populated_width = panel._log_stack.get_width()
        self.assertAlmostEqual(panel._log_stack.get_height(), empty_height, delta=1)
        panel.set_progress_text("Ensemble — Combining backing vocals and instrumental · 2 of 4")
        self.settle(lambda: panel._progress_revealer.get_child_revealed())
        self.assertAlmostEqual(panel._log_stack.get_width(), populated_width, delta=1)
        panel.clear_log()
        self.settle(lambda: abs(panel._log_stack.get_width() - empty_width) <= 1)

    def test_preflight_status_does_not_erase_previous_result(self):
        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        panel.set_run_result("Separation complete")
        panel.set_preparing(True)
        self.assertEqual(panel._progress_label.get_text(), "Preparing…")
        self.assertFalse(panel._progress_revealer.get_reveal_child())
        panel.set_preparing(False)
        self.assertEqual(panel._progress_label.get_text(), "Separation complete")

    def test_terminal_status_hides_progress_and_survives_settling(self):
        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        panel.set_progress_text("Working")
        panel.set_progress_fraction(0.42)
        panel.set_run_result("Processing failed", error=True)
        self.assertFalse(panel._progress_revealer.get_reveal_child())
        self.assertFalse(panel._percentage.get_visible())
        self.assertEqual(panel._progress_label.get_text(), "Processing failed")
        panel.set_progress_fraction(1)
        panel.set_progress_text("Done")
        panel.mark_run_complete()
        panel._cancel_done_collapse()
        panel._on_done_collapse()
        self.assertFalse(panel._progress_revealer.get_reveal_child())
        self.assertIn("complete", panel._progress_label.get_text().lower())

    def test_manual_scroll_survives_new_output_and_reopening(self):
        from gi.repository import Gtk

        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        window = Gtk.Window(default_width=1000, default_height=740)
        window.set_child(panel)
        window.present()
        self.addCleanup(window.set_visible, False)
        panel.set_expanded(True)
        panel.console.append("A processing log message\n" * 100)
        adj = panel.console.get_vadjustment()
        self.settle(lambda: adj.get_value() > 100)
        adj.set_value(100)
        panel.console.append("New output\n")
        panel.set_expanded(False)
        self.settle(lambda: not panel._log_revealer.get_child_revealed())
        panel.set_expanded(True)
        self.settle(panel._log_revealer.get_child_revealed)
        self.assertAlmostEqual(adj.get_value(), 100, delta=1)
        adj.set_value(adj.get_upper() - adj.get_page_size())
        panel.console.append("Follow again\n")
        self.settle(lambda: abs(adj.get_value() - (adj.get_upper() - adj.get_page_size())) < 1)

    def test_clearance_covers_panel_and_wrapping_stays_fixed_during_animation(self):
        from gi.repository import Adw, GLib, Gtk

        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        window = Gtk.Window(default_width=1000, default_height=740, child=panel)
        window.present()
        self.addCleanup(window.set_visible, False)
        panel.console.append(
            "A long processing message that can wrap at the final expanded width. " * 20
        )
        panel.set_expanded(True)
        self.settle(
            lambda: panel._log_revealer.get_child_revealed() and panel.console.get_width() > 0
        )
        surface = panel._panel_clamp.get_child()
        assert surface is not None
        self.assertGreaterEqual(panel.options_overlay_clearance(), surface.get_height() + 12)
        text_width = panel.console.get_width()
        line_y = panel.console._view.get_iter_location(panel.console._buffer.get_end_iter()).y
        samples = []

        def sample():
            samples.append(
                (
                    panel.console.get_width(),
                    panel.console._view.get_iter_location(panel.console._buffer.get_end_iter()).y,
                )
            )
            return GLib.SOURCE_CONTINUE

        source = GLib.timeout_add(16, sample)
        panel.set_expanded(False)
        try:
            self.settle(
                lambda: (
                    panel._width_animation is not None
                    and panel._width_animation.get_state() == Adw.AnimationState.FINISHED
                )
            )
        finally:
            GLib.source_remove(source)
        self.assertTrue(samples)
        self.assertTrue(all(width == text_width and y == line_y for width, y in samples))

    def test_overlay_keeps_options_outside_panel_clickable(self):
        from gi.repository import Gtk

        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        background = Gtk.Button(label="Options")
        overlay = Gtk.Overlay(child=background)
        overlay.add_overlay(panel)
        window = Gtk.Window(default_width=1000, default_height=740, child=overlay)
        window.present()
        self.addCleanup(window.set_visible, False)
        self.settle(lambda: panel.get_width() == 1000)
        picked = overlay.pick(100, 100, Gtk.PickFlags.DEFAULT)
        self.assertTrue(
            picked is background or (picked is not None and picked.is_ancestor(background))
        )

    def test_panel_receives_mouse_hits_and_blocks_clicks_through_its_body(self):
        from gi.repository import Adw, Gtk

        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        background = Gtk.Button(label="Options")
        overlay = Gtk.Overlay(child=background)
        overlay.add_overlay(panel)
        window = Gtk.Window(default_width=1000, default_height=740, child=overlay)
        window.present()
        self.addCleanup(window.set_visible, False)
        self.settle(lambda: panel.get_width() == 1000)

        def pick_center(widget: Gtk.Widget) -> Gtk.Widget | None:
            valid, bounds = widget.compute_bounds(overlay)
            self.assertTrue(valid)
            return overlay.pick(
                bounds.get_x() + bounds.get_width() / 2,
                bounds.get_y() + bounds.get_height() / 2,
                Gtk.PickFlags.DEFAULT,
            )

        for expanded, populated in ((False, False), (True, False), (True, True)):
            with self.subTest(expanded=expanded, populated=populated):
                if populated:
                    panel.console.append("Processing audio\n" * 30)
                panel.set_expanded(expanded)
                self.settle(
                    lambda expanded=expanded: (
                        panel._log_revealer.get_child_revealed() == expanded
                        and (
                            panel._width_animation is None
                            or panel._width_animation.get_state() == Adw.AnimationState.FINISHED
                        )
                    )
                )
                for button in (panel.expand_button, panel.start_button):
                    picked = pick_center(button)
                    self.assertTrue(
                        picked is button or (picked is not None and picked.is_ancestor(button))
                    )
                if populated:
                    for button in (panel.log_copy_button, panel.log_clear_button):
                        picked = pick_center(button)
                        self.assertTrue(
                            picked is button or (picked is not None and picked.is_ancestor(button))
                        )
                surface = panel._panel_clamp.get_child()
                assert surface is not None
                bounds = surface.compute_bounds(overlay)[1]
                # Empty padding and status text must also shield the controls behind.
                for x, y in (
                    (bounds.get_x() + bounds.get_width() / 2, bounds.get_y() + 5),
                    (bounds.get_x() + 8, bounds.get_y() + 40),
                ):
                    picked = overlay.pick(x, y, Gtk.PickFlags.DEFAULT)
                    self.assertTrue(
                        picked is panel or (picked is not None and picked.is_ancestor(panel))
                    )
                picked = pick_center(panel._progress_label)
                self.assertTrue(
                    picked is panel or (picked is not None and picked.is_ancestor(panel))
                )
                if expanded:
                    picked = pick_center(panel._log_stack)
                    self.assertTrue(
                        picked is panel or (picked is not None and picked.is_ancestor(panel))
                    )
                picked = overlay.pick(100, 100, Gtk.PickFlags.DEFAULT)
                self.assertTrue(
                    picked is background or (picked is not None and picked.is_ancestor(background))
                )

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
        self.addCleanup(window.set_visible, False)
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
