"""The light Preferences resync must not leave Audio Tools rows stale.

``MainWindow._sync_after_preferences`` calls only ``target.on_activated()`` as
a cheap alternative to a full reload. For Audio Tools, ``on_activated`` used to
call only ``_sync_shared_from_settings()``, which covers the block shared with
every tab (inputs/output/format/GPU/sample mode) but not the Audio-Tools-only
"Normalize output" switch or amplification threshold spin row — both editable
from Preferences (see ``ui/preferences.py``). A user who changes normalization
in Preferences while Separation or Ensemble is the visible tab would see the
Audio Tools switch keep showing the old value for the rest of the session.
"""

from __future__ import annotations

import os
import unittest


class _StubWindow:
    """Minimal window stand-in AudioToolsPage's constructor/on_activated need."""

    def toast(self, _message: str) -> None:
        pass

    def _refresh_start_readiness(self) -> None:
        pass


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class AudioToolsPreferencesResyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(
            application_id="org.uvr.test.audio-tools-preferences-resync"
        )
        cls._app.register()

    def _page(self):
        from core.settings import Settings
        from ui.audio_tools.window import AudioToolsPage

        class _Context:
            settings = Settings.defaults()

        context = _Context()
        return AudioToolsPage(_StubWindow(), context)

    def test_normalization_row_follows_settings_through_light_resync(self):
        page = self._page()
        self.assertFalse(page.normalize_row.get_active())

        # Simulate a Preferences edit made while another tab is visible: only
        # the settings dict changes, exactly as ``PreferencesDialog`` does.
        page.settings.set("is_normalization", True)

        # This is the light-resync path: MainWindow._sync_after_preferences
        # calls exactly this method on the visible tab's target.
        page.on_activated()

        self.assertTrue(
            page.normalize_row.get_active(),
            "the Normalize output switch must pick up a Preferences edit "
            "through the light resync path (on_activated), not just a full "
            "reload",
        )

    def test_amplification_threshold_row_follows_settings_through_light_resync(self):
        page = self._page()
        self.assertEqual(page.amplification_row.get_value(), 0.0)

        page.settings.set("amplification_threshold", 0.75)
        page.on_activated()

        self.assertAlmostEqual(page.amplification_row.get_value(), 0.75)


if __name__ == "__main__":
    unittest.main()
