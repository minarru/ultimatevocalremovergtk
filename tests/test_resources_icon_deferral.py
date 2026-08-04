"""Application-icon registration must not run during do_startup.

Two full Gtk.IconTheme scans (~312 ms measured) blocked the window for an icon
name only Adw.AboutDialog ever consumes.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK icon theme access needs a display",
)
class IconDeferralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.icon-deferral")
        cls._app.register()

    def test_register_gresources_skips_the_icon_scan(self) -> None:
        import ui.resources as resources

        with mock.patch.object(resources, "_register_application_icon") as icon:
            resources.register_gresources()
        icon.assert_not_called()

    def test_ensure_application_icon_performs_registration(self) -> None:
        import ui.resources as resources

        with mock.patch.object(
            resources, "_register_application_icon", return_value=True
        ) as icon:
            self.assertTrue(resources.ensure_application_icon())
        icon.assert_called_once()

    def test_about_requests_the_icon(self) -> None:
        import ui.about as about

        source = __import__("inspect").getsource(about.open_about)
        self.assertIn(
            "ensure_application_icon",
            source,
            "About supplies application_icon=APP_ID and must register it itself",
        )


if __name__ == "__main__":
    unittest.main()
