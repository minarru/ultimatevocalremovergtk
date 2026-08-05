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

    def test_about_calls_ensure_icon_before_dialog_construction(self) -> None:
        """Verify that ensure_application_icon is called *before* the dialog is built.

        Icon registration must occur before Adw.AboutDialog construction, or the
        icon name won't resolve for that specific dialog instance.
        """
        import typing

        import ui.about as about
        import ui.resources as resources
        from gi.repository import Adw

        call_sequence: list[str] = []

        def track_icon_call() -> bool:
            call_sequence.append("ensure_icon")
            return True

        def track_dialog_call(*_args: typing.Any, **_kwargs: typing.Any) -> mock.MagicMock:
            call_sequence.append("dialog_built")
            return mock.MagicMock()

        def track_about_window_call(*_args: typing.Any, **_kwargs: typing.Any) -> mock.MagicMock:
            call_sequence.append("about_window_built")
            return mock.MagicMock()

        with mock.patch.object(
            resources, "ensure_application_icon", side_effect=track_icon_call
        ) as icon_mock, mock.patch.object(
            resources, "register_gresources"
        ), mock.patch(
            "ui.about.Adw.AboutDialog", side_effect=track_dialog_call
        ), mock.patch(
            "ui.about.Adw.AboutWindow", side_effect=track_about_window_call
        ):
            try:
                about.open_about(mock.MagicMock())
            except Exception:
                # Mocked dialogs might not have all methods; that's fine
                pass

        # Verify ensure_application_icon was called once
        icon_mock.assert_called_once()

        # Verify that ensure_icon was called before any dialog was constructed
        # Either AboutDialog or AboutWindow may have been called, depending on
        # libadwaita version, but ensure_icon must come first
        self.assertIn(
            "ensure_icon", call_sequence, "ensure_application_icon must be called"
        )
        self.assertTrue(
            any(d in call_sequence for d in ["dialog_built", "about_window_built"]),
            "AboutDialog or AboutWindow must be constructed",
        )
        # Ensure icon registration comes before dialog construction
        ensure_idx = call_sequence.index("ensure_icon")
        dialog_idx = min(
            (
                call_sequence.index(d)
                for d in ["dialog_built", "about_window_built"]
                if d in call_sequence
            ),
            default=len(call_sequence),
        )
        self.assertLess(
            ensure_idx,
            dialog_idx,
            f"ensure_application_icon must be called before dialog construction, "
            f"but order was {call_sequence}",
        )


if __name__ == "__main__":
    unittest.main()
