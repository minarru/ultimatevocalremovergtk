"""Rendered Download Center controls for the public model catalogue."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock


@unittest.skipUnless(
    os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"),
    "GTK widget construction needs a display",
)
class DownloadCenterPublicUiTests(unittest.TestCase):
    def test_header_has_public_menu_without_password_control(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        from core.downloads import DownloadManager
        from core.settings import Settings
        from ui.download_center import DownloadCenterWindow

        context = SimpleNamespace(settings=Settings.defaults())
        center = DownloadCenterWindow(
            None, context, DownloadManager(), mock.MagicMock()
        )
        self.addCleanup(center.window.destroy)

        icon_names: list[str] = []
        stack: list[Gtk.Widget] = [center.window]
        while stack:
            widget = stack.pop()
            if isinstance(widget, (Gtk.Button, Gtk.MenuButton)):
                icon = widget.get_icon_name()
                if icon:
                    icon_names.append(icon)
            child = widget.get_first_child()
            while child is not None:
                stack.append(child)
                child = child.get_next_sibling()

        self.assertIn("open-menu-symbolic", icon_names)
        self.assertNotIn("dialog-password-symbolic", icon_names)


if __name__ == "__main__":
    unittest.main()
