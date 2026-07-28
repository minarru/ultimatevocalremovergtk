"""Sheet shell: capped width, content-driven height, balanced columns."""

from __future__ import annotations

import os
import unittest


class SheetConstantsTests(unittest.TestCase):
    """Headless: the sizing policy is expressed as module constants."""

    def test_width_is_capped_not_parent_tracked(self):
        from ui.model_options import sheet

        self.assertEqual(sheet._SHEET_WIDTH, 760)

    def test_height_fraction_leaves_room_for_the_parent_window(self):
        from ui.model_options import sheet

        self.assertEqual(sheet._SHEET_MAX_HEIGHT_FRACTION, 0.9)

    def test_parent_width_tracking_is_gone(self):
        from ui.model_options import sheet

        for name in (
            "_sync_from_parent_width",
            "_start_width_tracking",
            "_stop_width_tracking",
        ):
            self.assertFalse(
                hasattr(sheet.ModelOptionsSheet, name), f"{name} should be removed"
            )

    def test_the_sheet_no_longer_reaches_parent_window_width(self):
        import inspect

        from ui.model_options import sheet

        source = inspect.getsource(sheet)
        self.assertNotIn("parent_window_width", source)
        self.assertNotIn("configure_dialog_width", source)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SheetLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.sheet-layout")
        cls._app.register()

    def _sheet(self):
        from ui.model_options.sheet import ModelOptionsSheet
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        return ModelOptionsSheet(
            window,
            views=window._views,
            views_by_stack=window._views_by_stack,
            settings=window.settings,
        ), window

    def test_content_width_is_the_cap(self):
        from ui.model_options import sheet as sheet_module

        sheet, _window = self._sheet()
        self.assertEqual(sheet.dialog.get_content_width(), sheet_module._SHEET_WIDTH)

    def test_columns_are_not_homogeneous(self):
        sheet, _window = self._sheet()
        for columns_box in sheet._tab_columns.values():
            self.assertFalse(columns_box.get_homogeneous())

    def test_every_tab_carries_all_three_groups(self):
        sheet, window = self._sheet()
        for stack_name, view in window._views_by_stack.items():
            for group in (
                view.advanced_group,
                view.secondary_group,
                view.maintenance_group,
            ):
                self.assertIsNotNone(
                    group.get_parent(), f"{stack_name}: group not placed"
                )

    def test_maintenance_sits_below_secondary_in_the_end_column(self):
        sheet, window = self._sheet()
        for stack_name, view in window._views_by_stack.items():
            self.assertIs(
                view.maintenance_group.get_parent(),
                view.secondary_group.get_parent(),
                stack_name,
            )

    def test_inference_is_alone_in_the_start_column(self):
        sheet, window = self._sheet()
        for stack_name, view in window._views_by_stack.items():
            self.assertIsNot(
                view.advanced_group.get_parent(),
                view.secondary_group.get_parent(),
                stack_name,
            )

    def test_height_falls_back_when_the_parent_is_unrealized(self):
        from ui.model_options import sheet as sheet_module

        sheet, _window = self._sheet()
        self.assertEqual(sheet._sheet_height(), sheet_module._SHEET_FALLBACK_HEIGHT)


if __name__ == "__main__":
    unittest.main()
