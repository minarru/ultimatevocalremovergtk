"""Verify Inputs keeps live row actions and worker delivery after layout loading."""

from __future__ import annotations

import os
import time
import types
import unittest
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
