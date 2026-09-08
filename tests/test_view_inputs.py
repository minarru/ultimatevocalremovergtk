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

    def test_verification_emphasis_summary_and_short_folder_paths(self):
        view, _context, _changed = self.make_view()
        self.assertFalse(view.verify_button.has_css_class("suggested-action"))
        self.assertIn("Not verified", view._total_text())
        path = "/mnt/Backup/recordings/Session/song.wav"
        view.paths = [path]
        view._rebuild_list()
        row = view._rows[path]
        self.assertEqual(row.get_subtitle(), "…/recordings/Session")
        self.assertEqual(row.get_tooltip_text(), path)
        view._apply_result(path, True, "Readable", 1)
        self.assertIn("All readable", view._total_text())
        view.clear_button.emit("clicked")
        self.assertTrue(view.add_button.has_css_class("suggested-action"))
        self.assertFalse(view.verify_button.get_sensitive())

    def test_search_filters_without_changing_the_batch(self):
        view, context, _changed = self.make_view()
        self.assertFalse(view._search.get_visible())
        paths = [f"/recordings/Session/track-{n}.wav" for n in range(8)]
        view.paths = paths.copy()
        view._rebuild_list()
        self.assertTrue(view._search.get_visible())
        context.settings.process.input_paths = paths.copy()
        view._search.set_text("TRACK-3")
        view._search.emit("search-changed")
        self.assertEqual([p for p, row in view._rows.items() if row.get_visible()], [paths[3]])
        self.assertIn("1 of 8 files", view._total_text())
        self.assertEqual(context.settings.process.input_paths, paths)
        view._search.set_text("does not exist")
        view._search.emit("search-changed")
        self.assertTrue(view._empty_state.get_visible())
        self.assertEqual(view._empty_state.get_title(), "No matching files")
        view._search.set_text("session")
        view._search.emit("search-changed")
        self.assertTrue(all(row.get_visible() for row in view._rows.values()))
        self.assertFalse(view._empty_state.get_visible())

    def test_search_and_summary_stay_fixed_while_files_scroll(self):
        from gi.repository import Adw, Gtk

        settings = Gtk.Settings.get_default()
        assert settings is not None
        animations = settings.get_property("gtk-enable-animations")
        settings.set_property("gtk-enable-animations", False)
        self.addCleanup(settings.set_property, "gtk-enable-animations", animations)
        parent = Adw.Window(default_width=900, default_height=700)
        self.addCleanup(parent.close)
        parent.present()
        view, _context, _changed = self.make_view(parent)
        view.paths = [f"/tmp/track-{n}.wav" for n in range(40)]
        view._rebuild_list()
        view._sync_actions()
        view.present()
        scroll = view._input_scroll.get_vadjustment()

        def wait_for(predicate: Callable[[], bool]) -> None:
            deadline = time.monotonic() + 3
            while not predicate() and time.monotonic() < deadline:
                self.main_context.iteration(False)
                time.sleep(0.001)
            self.assertTrue(predicate())

        wait_for(lambda: view._search.get_height() > 0 and scroll.get_upper() > scroll.get_page_size())
        self.assertFalse(view._search.is_ancestor(view._input_scroll))
        self.assertFalse(view._summary.is_ancestor(view._input_scroll))
        body = view.dialog.get_child()
        assert body is not None

        def y(widget: Gtk.Widget) -> float:
            valid, bounds = widget.compute_bounds(body)
            self.assertTrue(valid)
            return bounds.get_y()

        first = view._rows[view.paths[0]]
        old_row_y = y(first)
        old_search_y, old_summary_y = y(view._search), y(view._summary)
        scroll.set_value(scroll.get_upper() - scroll.get_page_size())
        wait_for(lambda: y(first) < old_row_y)
        self.assertEqual(y(view._search), old_search_y)
        self.assertEqual(y(view._summary), old_summary_y)

    def test_undo_clear_restores_order_and_unreadable_state(self):
        view, context, changed = self.make_view()
        view._status = {"/tmp/good.wav": (True, "Readable"), "/tmp/bad.wav": (False, "Unreadable")}
        context.unreadable_input_paths = {"/tmp/bad.wav"}
        context.clear_unreadable_input_paths.side_effect = context.unreadable_input_paths.clear
        before = list(view.paths)
        view.clear_button.emit("clicked")
        toast = view._undo_toast
        self.assertIsNotNone(toast)
        self.assertEqual(context.settings.process.input_paths, [])
        assert toast is not None
        toast.emit("button-clicked")
        self.assertEqual(view.paths, before)
        self.assertEqual(context.settings.process.input_paths, before)
        self.assertEqual(context.unreadable_input_paths, {"/tmp/bad.wav"})
        self.assertTrue(view._status_icons["/tmp/good.wav"].has_css_class("success"))
        self.assertTrue(view._status_icons["/tmp/bad.wav"].has_css_class("warning"))
        changed.assert_called_with(before)

    def test_undo_is_invalidated_by_another_removal_verification_and_close(self):
        view, _context, _changed = self.make_view()
        view._remove_path("/tmp/good.wav")
        first = view._undo_toast
        view._remove_path("/tmp/bad.wav")
        assert first is not None
        first.emit("button-clicked")
        self.assertEqual(view.paths, [])
        current = view._undo_toast
        assert current is not None
        current.emit("button-clicked")
        self.assertEqual(view.paths, ["/tmp/bad.wav"])
        view._remove_path("/tmp/bad.wav")
        last = view._undo_toast
        assert last is not None
        view._on_closed()
        last.emit("button-clicked")
        self.assertEqual(view.paths, [])

        other, _context, _changed = self.make_view()
        other._remove_path("/tmp/bad.wav")
        pending = other._undo_toast
        assert pending is not None
        with patch("ui.inputs.threading.Thread"):
            other.verify_button.emit("clicked")
        pending.emit("button-clicked")
        self.assertEqual(other.paths, ["/tmp/good.wav"])
        self.assertFalse(other._remove_buttons["/tmp/good.wav"].get_sensitive())
        other._apply_result("/tmp/good.wav", True, "Readable", 1)
        self.assertEqual(other.verify_button.get_label(), "Cancel")

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
        with patch.object(view._summary, "set_label") as set_title:
            view._apply_result("/tmp/good.wav", True, "late result", 1)
        set_title.assert_not_called()

    def test_dialog_height_tracks_files_and_verification_with_bounded_scrolling(self):
        from gi.repository import Adw, Gtk

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
                predicate(),
                f"Unexpected dialog size: {body.get_width()}x{body.get_height()}; "
                f"status allocation: {view._empty_state.get_width()}x{view._empty_state.get_height()}; "
                f"status measure: {view._empty_state.measure(Gtk.Orientation.VERTICAL, view._empty_state.get_width())}",
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
        assert view._undo_toast is not None
        view._undo_toast.dismiss()
        wait_for(lambda: 0 < body.get_height() < 400)
        # The status page must fit after its internal clamp applies typography.
        wait_for(
            lambda: view._empty_state.get_height()
            >= view._empty_state.measure(
                Gtk.Orientation.VERTICAL, view._empty_state.get_width()
            )[1]
        )
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
        self.assertEqual(view._rows, {})
        self.assertTrue(view._empty_state.get_visible())
        self.assertFalse(view._header_box.get_visible())
        self.assertFalse(view.verify_button.get_sensitive())
        self.assertFalse(view.clear_button.get_sensitive())
        self.assertTrue(view.add_button.get_sensitive())

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
            with patch("ui.inputs.audio_open_dialog") as chooser:
                view.add_button.emit("clicked")
            picker = chooser.return_value
            picker.open_multiple.assert_called_once_with(None, None, view._on_add_finished)
            picker.open_multiple_finish.return_value.get_n_items.return_value = 1
            picker.open_multiple_finish.return_value.get_item.return_value.get_path.return_value = (
                audio.name
            )
            view._on_add_finished(picker, object())
            self.assertEqual(context.settings.process.input_paths, [audio.name])
            self.assertIn(audio.name, view._rows)
        self.assertFalse(view._empty_state.get_visible())
        self.assertTrue(view._header_box.get_visible())
        self.assertTrue(view.verify_button.get_sensitive())

    def test_verify_button_delivers_results_then_removes_only_unreadable(self) -> None:
        view, context, changed = self.make_view()
        for icon in view._status_icons.values():
            self.assertEqual(icon.get_icon_name(), "audio-x-generic-symbolic")
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
        self.assertIn("1 unreadable", view._summary.get_label() or "")
        self.assertIn("probe result", view._rows["/tmp/bad.wav"].get_subtitle() or "")
        good_icon = view._status_icons["/tmp/good.wav"]
        bad_icon = view._status_icons["/tmp/bad.wav"]
        self.assertEqual(good_icon.get_icon_name(), "success-small-symbolic")
        self.assertTrue(good_icon.has_css_class("success"))
        self.assertEqual(bad_icon.get_icon_name(), "warning-outline-symbolic")
        self.assertTrue(bad_icon.has_css_class("warning"))
        view.remove_unreadable_button.emit("clicked")
        self.assertEqual(context.settings.process.input_paths, ["/tmp/good.wav"])
        self.assertFalse(view.remove_unreadable_button.get_visible())
        self.assertTrue(view.verify_button.get_sensitive())
        changed.assert_called_with(["/tmp/good.wav"])

        with patch("ui.inputs.threading.Thread"):
            view.verify_button.emit("clicked")
        icon = view._status_icons["/tmp/good.wav"]
        self.assertEqual(icon.get_icon_name(), "audio-x-generic-symbolic")
        self.assertFalse(icon.has_css_class("success"))
        self.assertFalse(icon.has_css_class("warning"))
        view._apply_result("/tmp/good.wav", False, "Unreadable", 1)
        self.assertEqual(icon.get_icon_name(), "warning-outline-symbolic")
        view._apply_result("/tmp/good.wav", True, "Readable", 1)
        self.assertEqual(icon.get_icon_name(), "success-small-symbolic")
        self.assertTrue(icon.has_css_class("success"))
        self.assertFalse(icon.has_css_class("warning"))

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
