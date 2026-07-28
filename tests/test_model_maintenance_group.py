"""Change-model-defaults lives in its own group, not among the extra models."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class MaintenanceGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.maintenance-group")
        cls._app.register()

    def _views(self):
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return window, window._views

    def test_every_view_has_a_maintenance_group(self):
        _window, views = self._views()
        for view in views:
            self.assertIsNotNone(view.maintenance_group, view.stack_name)

    def test_the_group_is_titled_model_maintenance(self):
        _window, views = self._views()
        for view in views:
            self.assertEqual(
                view.maintenance_group.get_title(), "Model maintenance", view.stack_name
            )

    @staticmethod
    def _containing_group(row):
        """The Adw.PreferencesGroup that ultimately contains ``row``, or None."""
        from gi.repository import Adw

        current = row
        while current is not None:
            if isinstance(current, Adw.PreferencesGroup):
                return current
            current = current.get_parent()
        return None

    def test_the_change_row_left_the_extra_models_group(self):
        _window, views = self._views()
        for view in views:
            group = self._containing_group(view.change_row)
            self.assertIsNotNone(group, f"{view.stack_name}: change_row not in any group")
            self.assertIs(group, view.maintenance_group, view.stack_name)

    def test_maintenance_follows_secondary_in_the_group_order(self):
        _window, views = self._views()
        for view in views:
            groups = view.groups
            self.assertEqual(
                groups.index(view.maintenance_group),
                groups.index(view.secondary_group) + 1,
                view.stack_name,
            )


if __name__ == "__main__":
    unittest.main()
