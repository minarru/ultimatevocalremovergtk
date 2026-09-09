"""Preferences reorganization preserves settings and explicit profile actions."""

import os
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock, patch


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "GTK needs a display"
)
class PreferencesDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls.app = Adw.Application(application_id="org.uvr.test.preferences-design")
        cls.app.register()

    def dialog(self):
        from core.settings import Settings
        from ui.preferences import PreferencesDialog

        settings = Settings.defaults()
        settings.process.sample_mode = True
        settings.process.long_file_chunk_seconds = 0
        settings.process.long_file_chunk_overlap_seconds = 3.5
        context = SimpleNamespace(settings=settings, gpu_devices=[], try_save_settings=Mock())
        with patch("ui.preferences.ProfileStore") as store:
            store.return_value.list_profiles.return_value = []
            store.return_value.save.return_value = None
            self.profile_store = store.return_value
            dialog = PreferencesDialog(context)
        self.persist = Mock()
        dialog._persist = self.persist
        return dialog

    def test_open_and_reload_preserve_settings_and_page_ownership(self):
        from gi.repository import Adw

        dialog = self.dialog()
        before = dialog.settings.to_json_dict()
        owners = [
            (dialog.color_scheme_row, "general"),
            (dialog.device_row, "processing"),
            (dialog.output_name_preview_row, "output"),
            (dialog.diagnostic_level_row, "maintenance"),
        ]
        for widget, expected in owners:
            while widget is not None and not isinstance(widget, Adw.PreferencesPage):
                widget = widget.get_parent()
            assert isinstance(widget, Adw.PreferencesPage)
            self.assertEqual(widget.get_name(), expected)
        self.assertTrue(dialog.get_search_enabled())
        self.assertFalse(hasattr(dialog, "sample_mode_row"))
        dialog._reload_widgets()
        self.assertEqual(dialog.settings.to_json_dict(), before)
        dialog.context.try_save_settings.assert_not_called()
        self.persist.assert_not_called()

    def test_chunking_off_preserves_overlap_and_shows_off(self):
        dialog = self.dialog()
        self.assertEqual(dialog.long_chunk_row.get_text(), "Off")
        self.assertFalse(dialog.long_chunk_overlap_row.get_sensitive())
        dialog.long_chunk_row.set_value(600)
        self.assertTrue(dialog.long_chunk_overlap_row.get_sensitive())
        dialog.long_chunk_row.set_value(0)
        self.assertFalse(dialog.long_chunk_overlap_row.get_sensitive())
        self.assertEqual(dialog.long_chunk_overlap_row.get_value(), 3.5)
        self.assertEqual(dialog.settings.process.long_file_chunk_overlap_seconds, 3.5)

    def test_profile_save_validates_name_and_cancel_does_not_write(self):
        dialog = self.dialog()
        self.assertFalse(dialog.save_profile_dialog.get_response_enabled("save"))
        dialog.profile_name_row.set_text("bad/name")
        self.assertTrue(dialog.profile_name_error.get_visible())
        self.assertFalse(dialog.save_profile_dialog.get_response_enabled("save"))
        dialog.profile_name_row.set_text("My settings")
        self.assertFalse(dialog.profile_name_error.get_visible())
        self.assertTrue(dialog.save_profile_dialog.get_response_enabled("save"))
        dialog.save_profile_dialog.emit("response", "cancel")
        self.profile_store.save.assert_not_called()
        dialog.save_profile_dialog.emit("response", "save")
        self.profile_store.save.assert_called_once_with("My settings", dialog.settings.to_dict())
        self.assertEqual(dialog.profile_name_row.get_text(), "")

    def test_existing_profile_still_requires_replace_confirmation(self):
        from gi.repository import Adw

        dialog = self.dialog()
        self.profile_store.list_profiles.return_value = ["Existing"]
        dialog.profile_name_row.set_text("Existing")
        with patch.object(Adw.AlertDialog, "present") as present:
            dialog.save_profile_dialog.emit("response", "save")
        present.assert_called_once_with(dialog)
        self.profile_store.save.assert_not_called()
        dialog._on_save_profile_confirmed(None, "cancel", dialog.profile_name_row, "Existing")
        self.profile_store.save.assert_not_called()
        dialog._on_save_profile_confirmed(None, "replace", dialog.profile_name_row, "Existing")
        self.profile_store.save.assert_called_once()

    def test_profile_dialog_reopens_and_enter_saves(self):
        import time

        from gi.repository import Adw, GLib, Gtk

        gtk_settings = Gtk.Settings.get_default()
        assert gtk_settings is not None
        animations = gtk_settings.get_property("gtk-enable-animations")
        self.addCleanup(gtk_settings.set_property, "gtk-enable-animations", animations)
        gtk_settings.set_property("gtk-enable-animations", False)
        dialog = self.dialog()
        window = Adw.ApplicationWindow(application=self.app)
        window.set_default_size(800, 600)
        window.present()
        self.addCleanup(window.set_visible, False)
        self.addCleanup(dialog.force_close)
        dialog.present(window)

        def wait_for(predicate: Callable[[], bool]):
            deadline = time.monotonic() + 3
            while not predicate() and time.monotonic() < deadline:
                GLib.MainContext.default().iteration(False)
                time.sleep(0.005)
            self.assertTrue(predicate())

        def save_ready() -> bool:
            button = dialog.save_profile_dialog.get_default_widget()
            return (
                button is not None and button.get_mapped() and dialog.profile_name_row.get_mapped()
            )

        dialog._on_save_profile_requested(Adw.ActionRow())
        wait_for(save_ready)
        dialog.profile_name_row.set_text("Keyboard save")
        dialog.save_profile_dialog.close()
        wait_for(lambda: not dialog.save_profile_dialog.get_mapped())
        self.profile_store.save.assert_not_called()
        dialog._on_save_profile_requested(Adw.ActionRow())
        wait_for(save_ready)
        dialog.profile_name_row.emit("entry-activated")
        wait_for(lambda: self.profile_store.save.called)
        self.profile_store.save.assert_called_once_with("Keyboard save", dialog.settings.to_dict())
