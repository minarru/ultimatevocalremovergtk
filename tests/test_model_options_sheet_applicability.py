"""Sheet applicability: banners on inactive tabs, badges on ensemble tabs."""

from __future__ import annotations

import os
import unittest

from bundled.constants import ENSEMBLE_PARTITION, MDX_ARCH_TYPE, VR_ARCH_PM, VR_ARCH_TYPE
from ui.model_options.applicability import (
    OPEN_CONTEXT_ENSEMBLE,
    OPEN_CONTEXT_SEPARATION,
)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SheetApplicabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.sheet-applicability")
        cls._app.register()

    def _sheet(self, on_switch_method=None):
        from ui.model_options.sheet import ModelOptionsSheet
        from ui.window import MainWindow

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        sheet = ModelOptionsSheet(
            window,
            views=window._views,
            views_by_stack=window._views_by_stack,
            settings=window.settings,
            on_switch_method=on_switch_method,
        )
        return sheet, window

    @staticmethod
    def _show(sheet, stack_name):
        """Bring a tab on screen; the sheet has one banner describing it."""
        sheet._stack.set_visible_child_name(stack_name)

    def test_active_separation_tab_has_no_visible_banner(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self._show(sheet, "mdx")
        self.assertFalse(sheet._banner.get_revealed())

    def test_inactive_separation_tab_reveals_a_banner(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self._show(sheet, "vr")
        banner = sheet._banner
        self.assertTrue(banner.get_revealed())
        self.assertIn("MDX-Net", banner.get_title())

    def test_the_banner_offers_to_switch(self):
        sheet, _window = self._sheet(on_switch_method=lambda _name: None)
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self._show(sheet, "vr")
        self.assertIn("VR Architecture", sheet._banner.get_button_label())

    def test_no_button_without_a_switch_callback(self):
        sheet, _window = self._sheet(on_switch_method=None)
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self._show(sheet, "vr")
        self.assertFalse(sheet._banner.get_button_label())

    def test_ensemble_tabs_are_badged_with_member_counts(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_ENSEMBLE,
            active_method_key="",
            selected_models=[
                f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Model A",
                f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Model B",
                f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}Model C",
            ],
        )
        self.assertEqual(sheet._tab_stack_pages["mdx"].get_badge_number(), 2)
        self.assertEqual(sheet._tab_stack_pages["vr"].get_badge_number(), 1)

    def test_separation_context_carries_no_badges(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        for stack_name in ("vr", "mdx", "demucs"):
            self.assertEqual(
                sheet._tab_stack_pages[stack_name].get_badge_number(), 0, stack_name
            )

    def test_activating_the_banner_calls_back_with_the_stack_name(self):
        switched = []
        sheet, _window = self._sheet(on_switch_method=switched.append)
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self._show(sheet, "vr")
        sheet._banner.emit("button-clicked")
        self.assertEqual(switched, ["vr"])

    def test_banner_switch_button_changes_the_main_window_method(self):
        """End-to-end: the banner's own button, wired through the real window
        handler, must actually flip the main window's active architecture --
        not just invoke a callback that happens to be a no-op stand-in."""
        from ui.model_options.sheet import ModelOptionsSheet
        from ui.window import MainWindow

        from ui.widgets.rows import set_combo_value

        window = MainWindow()
        self.addCleanup(window.set_application, None)
        # Force a known starting method regardless of whatever a previous test
        # run left persisted on disk -- this drives the same combo + signal
        # path the window itself uses, so it also exercises "starting on MDX"
        # honestly rather than assuming it.
        set_combo_value(window.method_row, "MDX-Net")
        self.assertEqual(window._active_view().method_key, MDX_ARCH_TYPE)

        sheet = ModelOptionsSheet(
            window,
            views=window._views,
            views_by_stack=window._views_by_stack,
            settings=window.settings,
            on_switch_method=window._on_sheet_switch_method,
        )
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )

        sheet._stack.set_visible_child_name("vr")
        sheet._banner.emit("button-clicked")

        self.assertEqual(window._active_view().method_key, VR_ARCH_PM)
        self.assertEqual(window.settings.get("chosen_process_method"), VR_ARCH_PM)

    def test_empty_ensemble_prompts_on_every_tab(self):
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_ENSEMBLE,
            active_method_key="",
            selected_models=[],
        )
        for stack_name in ("vr", "mdx", "demucs"):
            self._show(sheet, stack_name)
            banner = sheet._banner
            self.assertTrue(banner.get_revealed(), stack_name)
            self.assertIn("Select ensemble member models", banner.get_title())

    def test_the_banner_lives_in_the_toolbar_not_in_a_page(self):
        """The banner is an ``Adw.ToolbarView`` top bar, so it renders flush
        under the header rather than floating inside a page's inset margins."""
        from gi.repository import Adw

        sheet, _window = self._sheet()
        ancestors = []
        node = sheet._banner.get_parent()
        while node is not None:
            ancestors.append(node)
            node = node.get_parent()

        self.assertTrue(
            any(isinstance(a, Adw.ToolbarView) for a in ancestors),
            "banner should sit inside the ToolbarView",
        )
        for stack_name, page in sheet._tab_pages.items():
            self.assertNotIn(page, ancestors, f"banner must not be inside {stack_name}")

    def test_the_banner_crossfades_instead_of_sliding(self):
        """The banner is an Adw.ToolbarView top bar, so a slide-down reveal
        re-allocates the content beneath it on every frame of the animation
        (measured: 13 distinct scroller heights per reveal) and tears along its
        bottom edge. Crossfade reaches the final height in one layout pass
        (measured: 2) while still animating."""
        from gi.repository import Gtk

        sheet, _window = self._sheet()
        revealer = sheet._banner.get_first_child()
        self.assertIsInstance(revealer, Gtk.Revealer)
        self.assertEqual(
            revealer.get_transition_type(), Gtk.RevealerTransitionType.CROSSFADE
        )

    def test_the_banner_keeps_its_reveal_animation(self):
        """Regression: an earlier fix stopped the tearing by killing the reveal
        outright. Crossfade addresses it without that, so the animation stays."""
        from gi.repository import Gtk

        sheet, _window = self._sheet()
        revealer = sheet._banner.get_first_child()
        self.assertIsInstance(revealer, Gtk.Revealer)
        self.assertGreater(revealer.get_transition_duration(), 0)

    def test_one_banner_is_shared_across_tabs(self):
        """Switching tabs relabels the single banner rather than swapping widgets."""
        sheet, _window = self._sheet()
        sheet.update_context(
            context=OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self._show(sheet, "mdx")
        self.assertFalse(sheet._banner.get_revealed())
        self._show(sheet, "demucs")
        self.assertTrue(sheet._banner.get_revealed())
        self.assertIn("MDX-Net", sheet._banner.get_title())


if __name__ == "__main__":
    unittest.main()
