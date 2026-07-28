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

    # -- Regression: narrow-column stacking must react to the sheet's real
    # allocated width, not the requested ``content-width`` (which nothing
    # updates after construction and so never changes again). These tests
    # actually present the dialog inside a parent window so the columns box
    # gets a real GTK size allocation, rather than asserting on the frozen
    # requested size the way the old (dead) coverage did.

    def _pump(self, iterations: int = 200) -> None:
        from gi.repository import GLib

        context = GLib.MainContext.default()
        for _ in range(iterations):
            while context.pending():
                context.iteration(False)

    def _presented_sheet(self, parent_width: int):
        sheet, window = self._sheet()
        window.set_application(self._app)
        window.set_default_size(parent_width, 480)
        window.present()
        sheet.present(
            context="separation", active_method_key="MDX-Net", selected_models=[]
        )
        self._pump()
        return sheet, window

    def test_narrow_parent_stacks_the_columns(self):
        from gi.repository import Gtk

        from ui.model_options import sheet as sheet_module

        sheet, window = self._presented_sheet(640)
        self.addCleanup(window.close)
        # Sanity: the allocated width, not the 760px requested cap, is what
        # crossed the breakpoint.
        self.assertLess(sheet.dialog.get_width(), sheet_module._STACK_BREAKPOINT)

        for stack_name, columns_box in sheet._tab_columns.items():
            self.assertEqual(
                columns_box.get_orientation(),
                Gtk.Orientation.VERTICAL,
                f"{stack_name}: columns should stack under a narrow parent",
            )

    def test_wide_parent_keeps_the_columns_side_by_side(self):
        from gi.repository import Gtk

        from ui.model_options import sheet as sheet_module

        sheet, window = self._presented_sheet(1100)
        self.addCleanup(window.close)
        self.assertGreaterEqual(sheet.dialog.get_width(), sheet_module._STACK_BREAKPOINT)

        for stack_name, columns_box in sheet._tab_columns.items():
            self.assertEqual(
                columns_box.get_orientation(),
                Gtk.Orientation.HORIZONTAL,
                f"{stack_name}: columns should stay side-by-side under a wide parent",
            )


if __name__ == "__main__":
    unittest.main()
