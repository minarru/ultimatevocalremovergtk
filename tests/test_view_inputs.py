"""Verify Inputs keeps live row actions and worker delivery after layout loading."""

from __future__ import annotations

import os
import time
import types
import unittest
from typing import Any, cast
from unittest.mock import Mock, patch


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "Verify Inputs requires a GTK display",
)
class ViewInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, GLib
        except (ImportError, ValueError) as exc:
            raise unittest.SkipTest(f"GTK unavailable: {exc}") from exc
        cls.app = Adw.Application(application_id="org.uvr.test.view-inputs")
        cls.app.register()
        cls.main_context = GLib.MainContext.default()

    def make_view(self):
        from core.settings import Settings
        from ui.inputs import ViewInputs

        settings = Settings()
        settings.process.input_paths = ["/tmp/good.wav", "/tmp/bad.wav"]
        context = types.SimpleNamespace(
            settings=settings,
            unreadable_input_paths=set(),
            try_save_settings=Mock(return_value=None),
            prune_unreadable_input_paths=Mock(),
            clear_unreadable_input_paths=Mock(),
            set_unreadable_input_paths=Mock(),
        )
        changed = Mock()
        view = ViewInputs(None, context, changed)
        self.addCleanup(view.window.close)
        return view, context, changed

    def test_remove_button_preserves_other_file_then_clear_reaches_empty_state(self) -> None:
        from gi.repository import Gtk

        view, context, changed = self.make_view()

        def descendants(widget: Gtk.Widget):
            yield widget
            child = widget.get_first_child()
            while child is not None:
                yield from descendants(child)
                child = child.get_next_sibling()

        remove = next(
            w
            for w in descendants(view._rows["/tmp/bad.wav"])
            if isinstance(w, Gtk.Button) and w.get_icon_name() == "user-trash-symbolic"
        )
        remove.emit("clicked")
        self.assertEqual(context.settings.process.input_paths, ["/tmp/good.wav"])
        changed.assert_called_once_with(["/tmp/good.wav"])
        self.assertNotIn("/tmp/bad.wav", view._rows)
        view.clear_button.emit("clicked")
        self.assertEqual(context.settings.process.input_paths, [])
        self.assertEqual(list(view._rows), ["__placeholder__"])
        self.assertFalse(view.verify_button.get_sensitive())
        self.assertFalse(view.clear_button.get_sensitive())
        self.assertTrue(view.add_button.get_sensitive())

    def test_verify_button_delivers_results_then_removes_only_unreadable(self) -> None:
        view, context, changed = self.make_view()
        with patch(
            "ui.inputs.inspect_audio",
            side_effect=lambda p: (p.endswith("good.wav"), "probe result"),
        ):
            view.verify_button.emit("clicked")
            self.assertFalse(view.add_button.get_sensitive())
            deadline = time.monotonic() + 5
            while view._verifying and time.monotonic() < deadline:
                self.main_context.iteration(False)
                time.sleep(0.001)
            self.assertFalse(view._verifying, "Verification worker never reached GTK")
        context.set_unreadable_input_paths.assert_called_once_with(["/tmp/bad.wav"])
        self.assertTrue(view.remove_unreadable_button.get_visible())
        self.assertIn("1 unreadable", view._files_group.get_title() or "")
        self.assertIn("probe result", view._rows["/tmp/bad.wav"].get_subtitle() or "")
        view.remove_unreadable_button.emit("clicked")
        self.assertEqual(context.settings.process.input_paths, ["/tmp/good.wav"])
        self.assertFalse(view.remove_unreadable_button.get_visible())
        self.assertTrue(view.verify_button.get_sensitive())
        changed.assert_called_with(["/tmp/good.wav"])

    def test_closed_verification_cannot_restore_old_input_selection(self) -> None:
        import threading

        from ui.context import AppContext
        from ui.window import MainWindow

        view, context, changed = self.make_view()
        window = MainWindow.__new__(MainWindow)
        window.context = cast(AppContext, context)
        window.settings = context.settings
        window.input_row = Mock()
        window._shared_session = Mock()
        window._refresh_start_readiness = Mock()
        view._on_inputs_changed = window._on_external_inputs_changed
        entered, release = threading.Event(), threading.Event()
        delivered = threading.Event()
        original_done = view._verify_done

        def delayed_probe(_path: str):
            entered.set()
            release.wait(timeout=5)
            return False, "unreadable"

        def done(*args: Any):
            original_done(*args)
            delivered.set()

        with (
            patch("ui.inputs.inspect_audio", side_effect=delayed_probe),
            patch.object(view, "_verify_done", side_effect=done),
        ):
            view.verify_button.emit("clicked")
            self.assertTrue(entered.wait(timeout=2))
            view._on_close_request()
            context.settings.process.input_paths = ["/tmp/new.wav"]
            release.set()
            deadline = time.monotonic() + 5
            while not delivered.is_set() and time.monotonic() < deadline:
                self.main_context.iteration(False)
                time.sleep(0.001)
            self.assertTrue(delivered.is_set())
        self.assertEqual(context.settings.process.input_paths, ["/tmp/new.wav"])
        context.set_unreadable_input_paths.assert_not_called()
        window.input_row.set_paths.assert_not_called()
        changed.assert_not_called()

    def test_late_file_picker_result_after_close_does_not_commit(self) -> None:
        view, context, changed = self.make_view()
        view._on_close_request()
        picker = Mock()
        picker.open_multiple_finish.return_value.get_n_items.return_value = 1
        picker.open_multiple_finish.return_value.get_item.return_value.get_path.return_value = (
            __file__
        )
        view._on_add_finished(picker, object())
        context.try_save_settings.assert_not_called()
        changed.assert_not_called()

    def test_cancelled_current_verification_preserves_unchecked_failures(self) -> None:
        view, context, changed = self.make_view()
        view._verifying = True
        view._verify_total = 2
        view._on_verify(view.verify_button)
        self.assertTrue(view._verify_stop.is_set())
        view._verify_done(
            [],
            cancelled=True,
            verified_paths=["/tmp/good.wav"],
            prior_unreadable=["/tmp/bad.wav"],
        )
        context.set_unreadable_input_paths.assert_called_once_with(["/tmp/bad.wav"])
        self.assertFalse(view._verifying)
        self.assertTrue(view.verify_button.get_sensitive())
        changed.assert_called_once_with(["/tmp/good.wav", "/tmp/bad.wav"])
