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

    def test_log_height_is_fixed_across_status_and_window_changes(self):
        from gi.repository import Adw

        from ui.widgets.log_panel import _LOG_BODY_HEIGHT, LogPanel

        panel = LogPanel()
        panel._available_size = (1000, 740)
        panel._update_geometry()
        expected = round(Adw.length_unit_to_px(Adw.LengthUnit.SP, _LOG_BODY_HEIGHT, panel.get_settings()))
        self.assertEqual(panel._log_height, expected)
        panel.set_progress_text("Waiting for the worker to finish", title="Stopping…")
        self.assertEqual(panel._log_height, expected)
        panel.set_run_result("Processing failed", error=True)
        self.assertEqual(panel._log_height, expected)
        panel._available_size = (1000, 900)
        panel._update_geometry()
        self.assertEqual(panel._log_height, expected)
        panel._available_size = (1000, 300)
        panel._update_geometry()
        self.assertLess(panel._log_height, expected)

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

    def test_choice_label_restores_progress_and_terminal_result_clears_it(self):
        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        panel.set_progress_text("File 2 of 3", title="Separating audio")
        panel.set_waiting_status("Stop this run?")
        self.assertEqual(panel._progress_label.get_text(), "Stop this run?")
        panel.set_waiting_status(None)
        self.assertEqual(panel._progress_label.get_text(), "Separating audio")
        self.assertEqual(panel._detail_label.get_text(), "File 2 of 3")
        panel.set_waiting_status("Waiting for your choice", "GPU memory exhausted")
        panel.set_run_result("Processing failed", error=True)
        self.assertEqual(panel._progress_label.get_text(), "Processing failed")

    def test_empty_log_labels_follow_preparing_clear_and_new_run(self):
        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        panel.set_preparing(True)
        self.assertEqual(panel._empty_title.get_text(), "Waiting for output")
        panel.console.append("Working\n")
        panel.clear_log()
        self.assertEqual(panel._empty_title.get_text(), "Log cleared")
        self.assertEqual(panel._empty_body.get_text(), "New messages will appear here.")
        panel.set_preparing(False)
        panel.set_preparing(True)
        self.assertEqual(panel._empty_title.get_text(), "Log cleared")
        panel.prepare_for_run()
        self.assertEqual(panel._empty_title.get_text(), "Waiting for output")

    def test_clear_stopped_log_restores_readiness(self):
        from ui.widgets.log_panel import LogPanel

        for reason in (None, "Choose a model"):
            with self.subTest(reason=reason):
                panel = LogPanel()
                panel.set_start_blocked_reason(reason)
                panel.console.append("Stopped by user\n")
                panel.set_run_result("Run stopped")
                panel.clear_log()
                self.assertEqual(panel._progress_label.get_text(), reason or "Ready to process")
                self.assertEqual(panel._empty_title.get_text(), "Log cleared")
                self.assertFalse(panel._progress_revealer.get_reveal_child())

    def test_clear_log_preserves_active_and_restart_required_status(self):
        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        panel.set_progress_text("Waiting for the worker to finish", title="Stopping…")
        panel.clear_log()
        self.assertEqual(panel._progress_label.get_text(), "Stopping…")
        panel.set_run_result("Unable to stop — restart required", error=True)
        panel.clear_log()
        self.assertEqual(panel._progress_label.get_text(), "Unable to stop — restart required")
        self.assertTrue(panel._progress_label.has_css_class("error"))

    def test_preflight_temporarily_hides_error_style_and_completed_progress(self):
        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        panel.set_run_result("Processing failed", error=True)
        panel.set_preparing(True)
        self.assertFalse(panel._progress_label.has_css_class("error"))
        panel.set_preparing(False)
        self.assertTrue(panel._progress_label.has_css_class("error"))
        panel.set_progress_fraction(1)
        panel.set_progress_text("Done")
        panel.set_preparing(True)
        self.assertFalse(panel._progress_revealer.get_reveal_child())
        panel.set_preparing(False)
        self.assertTrue(panel._progress_revealer.get_reveal_child())

    def test_clear_all_finished_outcomes_restores_readiness(self):
        from ui.widgets.log_panel import LogPanel

        for result in ("Run stopped", "Processing failed", "Separation complete"):
            panel = LogPanel()
            panel.set_start_blocked_reason("Choose a model")
            panel.set_run_result(result, error=result == "Processing failed")
            panel.clear_log()
            self.assertEqual(panel._progress_label.get_text(), "Choose a model")
            self.assertFalse(panel._progress_label.has_css_class("error"))

    def test_empty_run_keeps_waiting_page_until_output_arrives(self):
        from ui.widgets.log_panel import LogPanel

        panel = LogPanel()
        panel.set_progress_text("Loading engines…")
        panel.prepare_for_run()
        self.assertEqual(panel._log_stack.get_visible_child_name(), "empty")
        self.assertEqual(panel._empty_title.get_text(), "Waiting for output")
        panel.console.append("Loaded\n")
        self.assertEqual(panel._log_stack.get_visible_child_name(), "console")

    def test_completion_holds_for_five_seconds_then_rechecks_readiness(self):
        from unittest import mock

        from ui.widgets.log_panel import LogPanel

        refresh = mock.Mock()
        panel = LogPanel(on_completion_expired=refresh)
        panel.set_progress_fraction(1)
        panel.set_progress_text("Done")
        with mock.patch("ui.widgets.log_panel.GLib.timeout_add", return_value=123) as timeout:
            panel.mark_run_complete()
        self.assertEqual(timeout.call_args.args[0], 5000)
        panel.set_start_blocked_reason("Choose a model")
        self.assertEqual(panel._progress_label.get_text(), "Done")
        refresh.assert_not_called()
        timeout.call_args.args[1]()
        refresh.assert_called_once_with()
        self.assertEqual(panel._progress_label.get_text(), "Choose a model")
        self.assertFalse(panel._progress_revealer.get_reveal_child())

    def test_clear_or_new_run_cancels_completion_hold(self):
        from ui.widgets.log_panel import LogPanel

        for next_action in ("clear", "start"):
            panel = LogPanel()
            panel.set_progress_fraction(1)
            panel.set_progress_text("Done")
            panel.mark_run_complete()
            if next_action == "clear":
                panel.clear_log()
                expected = "Ready to process"
            else:
                panel.set_progress_text("Loading engines…")
                expected = "Loading engines…"
            self.assertIsNone(panel._done_collapse_id)
            panel._on_done_collapse()  # A late callback must not replace the new state.
            self.assertEqual(panel._progress_label.get_text(), expected)

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
        self.assertEqual(panel._progress_label.get_text(), "Ready to process")

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
                # The clamp spans the window at the card's height. Its transparent
                # sides must not become pointer targets in any expansion state.
                for x in (bounds.get_x() - 10, bounds.get_x() + bounds.get_width() + 10):
                    picked = overlay.pick(
                        x, bounds.get_y() + bounds.get_height() / 2, Gtk.PickFlags.DEFAULT
                    )
                    self.assertTrue(
                        picked is background or (picked is not None and picked.is_ancestor(background)),
                        f"Transparent side picked {type(picked).__name__}",
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
