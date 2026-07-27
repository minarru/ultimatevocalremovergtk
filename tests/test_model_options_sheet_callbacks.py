"""Regression: model-options sheet must not touch view settings callbacks."""

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

    def test_present_and_close_leave_settings_callbacks_untouched(self) -> None:
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
        )
        sheet.update_context(
            context="separation",
            active_method_key="Demucs",
            selected_models=[],
        )

        self.assertIs(mdx._on_settings_changed, original_mdx)
        self.assertIs(demucs._on_settings_changed, original_demucs)

        sheet._on_closed()

        self.assertIs(mdx._on_settings_changed, original_mdx)
        self.assertIs(demucs._on_settings_changed, original_demucs)


if __name__ == "__main__":
    unittest.main()
