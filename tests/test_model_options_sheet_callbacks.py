"""Regression: model-options sheet must not wrap settings callbacks after close."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ModelOptionsSheetCallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.model-options-sheet")
        cls._app.register()

    def _make_view(self, stack_name: str):
        from gi.repository import Adw

        view = MagicMock()
        view.stack_name = stack_name
        view.title = stack_name
        view.advanced_group = Adw.PreferencesGroup()
        view.secondary_group = Adw.PreferencesGroup()
        view._on_settings_changed = MagicMock(name=f"{stack_name}_settings_changed")
        return view

    def test_close_restores_settings_callbacks(self) -> None:
        from gi.repository import Gtk

        from ui.model_options.sheet import ModelOptionsSheet

        parent = Gtk.Window()
        mdx = self._make_view("mdx")
        demucs = self._make_view("demucs")
        original_mdx = mdx._on_settings_changed
        original_demucs = demucs._on_settings_changed

        sheet = ModelOptionsSheet(
            parent,
            views=[mdx, demucs],
            views_by_stack={"mdx": mdx, "demucs": demucs},
            settings=MagicMock(),
            on_toast=MagicMock(),
        )
        for view in (mdx, demucs):
            sheet._wrap_settings_callback(view)

        self.assertIsNot(mdx._on_settings_changed, original_mdx)
        self.assertIsNot(demucs._on_settings_changed, original_demucs)

        sheet._on_closed()

        self.assertIs(mdx._on_settings_changed, original_mdx)
        self.assertIs(demucs._on_settings_changed, original_demucs)
        self.assertEqual(sheet._settings_wrappers, {})

    def test_wrapped_callback_skips_toast_when_dialog_closed(self) -> None:
        from gi.repository import Gtk

        from ui.model_options.sheet import ModelOptionsSheet

        parent = Gtk.Window()
        mdx = self._make_view("mdx")
        toast = MagicMock()
        sheet = ModelOptionsSheet(
            parent,
            views=[mdx],
            views_by_stack={"mdx": mdx},
            settings=MagicMock(),
            on_toast=toast,
        )
        sheet._context = "separation"
        sheet._active_method_key = "Demucs"
        sheet._wrap_settings_callback(mdx)

        # Dialog is not presented, so get_mapped() is false.
        mdx._on_settings_changed()
        toast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
