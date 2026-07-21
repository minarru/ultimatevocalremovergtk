"""Regression tests for Download Center catalogue search filtering."""

from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class CatalogueActionRowResolveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        # Application init is enough for ActionRow construction under a display.
        cls._app = Adw.Application(application_id="org.uvr.test.catalogue-search")
        cls._app.register()

    def test_resolve_returns_action_row_itself(self) -> None:
        from gi.repository import Adw

        from ui.download_center import resolve_catalogue_action_row

        action = Adw.ActionRow()
        action._uvr_model_name = "MDX-Net Model: Kim Vocal 2"
        resolved = resolve_catalogue_action_row(action)
        self.assertIs(resolved, action)
        self.assertEqual(resolved._uvr_model_name, "MDX-Net Model: Kim Vocal 2")

    def test_internal_child_is_not_the_action_row(self) -> None:
        from gi.repository import Adw

        action = Adw.ActionRow()
        child = action.get_child()
        self.assertIsNotNone(child)
        self.assertFalse(isinstance(child, Adw.ActionRow))


if __name__ == "__main__":
    unittest.main()
