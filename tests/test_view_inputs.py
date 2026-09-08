"""Verify Inputs keeps live row actions and worker delivery after layout loading."""

from __future__ import annotations

import os
import time
import types
import unittest
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock, patch

if TYPE_CHECKING:
    from gi.repository import Gtk


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

    def make_view(self, parent: Gtk.Window | None = None):
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
        from ui.context import AppContext

        context._input_verification_generation = 0
        context.begin_input_verification = types.MethodType(
            AppContext.begin_input_verification, context
        )
        context.apply_input_verification = types.MethodType(
            AppContext.apply_input_verification, context
        )
        context.set_unreadable_input_paths.side_effect = lambda paths: setattr(
            context, 'unreadable_input_paths', set(paths)
        )
        changed = Mock()
        view = ViewInputs(parent, context, changed, on_verification_changed=Mock())
        def cleanup() -> None:
            if view._lifetime.disposed:
                return
            if view.dialog.get_root() is not None:
                view.dialog.close()
            else:
                view._on_closed()

        self.addCleanup(cleanup)
        return view, context, changed

    def test_dialog_is_attached_and_file_picker_uses_its_host_window(self):
        from gi.repository import Adw

        parent = Adw.Window(default_width=900, default_height=700)
        self.addCleanup(parent.close)
        parent.present()
        view, _context, _changed = self.make_view(parent)
        view.present()
        self.assertIsInstance(view.dialog, Adw.Dialog)
        self.assertIs(parent.get_visible_dialog(), view.dialog)
        with patch("ui.inputs.audio_open_dialog") as chooser:
            view.add_button.emit("clicked")
        chooser.return_value.open_multiple.assert_called_once_with(
            parent, None, view._on_add_finished
        )

    def test_closing_attached_dialog_stops_verification_delivery(self):
        from gi.repository import Adw

        parent = Adw.Window(default_width=900, default_height=700)
        self.addCleanup(parent.close)
        parent.present()
        view, _context, _changed = self.make_view(parent)
        view.present()
        view._verifying = True
        view.dialog.close()
        deadline = time.monotonic() + 3
        while not view._lifetime.disposed and time.monotonic() < deadline:
            self.main_context.iteration(False)
            time.sleep(0.001)
        self.assertTrue(view._lifetime.disposed)
        self.assertTrue(view._verify_stop.is_set())
        with patch.object(view._files_group, "set_title") as set_title:
            view._apply_result("/tmp/good.wav", True, "late result", 1)
        set_title.assert_not_called()

    def test_dialog_height_tracks_files_and_verification_with_bounded_scrolling(self):
        from gi.repository import Adw

        parent = Adw.Window(default_width=900, default_height=700)
        self.addCleanup(parent.close)
        parent.present()
        view, _context, _changed = self.make_view(parent)
        view.present()
        body = view.dialog.get_child()
        self.assertIsNotNone(body)
        assert body is not None

        def wait_for(predicate: Callable[[], bool]) -> None:
            deadline = time.monotonic() + 3
            while not predicate() and time.monotonic() < deadline:
                self.main_context.iteration(False)
                time.sleep(0.001)
            self.assertTrue(
                predicate(), f"Unexpected dialog size: {body.get_width()}x{body.get_height()}"
            )

        wait_for(lambda: body.get_width() == 620 and 0 < body.get_height() < 400)
        compact_height = body.get_height()
        view._status = {path: (False, "Could not read this file") for path in view.paths}
        view._rebuild_list()
        view._sync_actions()
        wait_for(lambda: body.get_height() > compact_height)
        view.paths = [f"/tmp/track-{index}.wav" for index in range(30)]
        view._status.clear()
        view._rebuild_list()
        view._sync_actions()
        wait_for(lambda: body.get_height() > 500)
        self.assertLess(body.get_height(), parent.get_height())
        self.assertEqual(body.get_width(), 620)
        scroll = view._input_scroll.get_vadjustment()
        wait_for(lambda: scroll.get_upper() > scroll.get_page_size())
        expanded_height = body.get_height()
        view.clear_button.emit("clicked")
        wait_for(lambda: 0 < body.get_height() < compact_height)
        self.assertLess(body.get_height(), expanded_height)
        self.assertEqual(body.get_width(), 620)

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
            if isinstance(w, Gtk.Button) and w.get_icon_name() == "cross-small-symbolic"
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
            view._on_closed()
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
        view._on_closed()
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
        context.unreadable_input_paths = {"/tmp/bad.wav"}
        view._verification_generation = context.begin_input_verification()
        view._verifying = True
        view._verify_total = 2
        view._on_verify(view.verify_button)
        self.assertTrue(view._verify_stop.is_set())
        view._verify_done(
            [],
            cancelled=True,
            verified_paths=["/tmp/good.wav"],
        )
        context.set_unreadable_input_paths.assert_called_once_with(["/tmp/bad.wav"])
        self.assertFalse(view._verifying)
        self.assertTrue(view.verify_button.get_sensitive())
        changed.assert_not_called()

    def test_closed_scan_updates_application_results_without_touching_widgets(self):
        view, context, changed = self.make_view()
        context.unreadable_input_paths = {'/tmp/good.wav', '/tmp/bad.wav'}
        view._verification_generation = context.begin_input_verification()
        verified = Mock()
        view._on_verification_changed = verified
        view._on_closed()
        with patch.object(view, '_rebuild_list') as rebuild:
            view._verify_done([], True, ['/tmp/good.wav'])
        self.assertEqual(context.unreadable_input_paths, {'/tmp/bad.wav'})
        verified.assert_called_once_with()
        changed.assert_not_called()
        rebuild.assert_not_called()

    def test_closed_old_scan_cannot_overwrite_new_scan_results(self):
        view, context, changed = self.make_view()
        view._verification_generation = context.begin_input_verification()
        view._on_closed()
        newer = context.begin_input_verification()
        context.apply_input_verification(newer, ['/tmp/good.wav'], ['/tmp/good.wav'])
        view._verify_done([], True, ['/tmp/good.wav'])
        self.assertEqual(context.unreadable_input_paths, {'/tmp/good.wav'})
        changed.assert_not_called()
