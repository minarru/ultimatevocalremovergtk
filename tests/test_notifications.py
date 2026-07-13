"""Tests for desktop notification preference gates."""

import unittest
from unittest.mock import MagicMock, patch

from core.settings import SettingsModel
from ui.notifications import (
    NOTIFY_DOWNLOAD_COMPLETE,
    NOTIFY_PROCESS_COMPLETE,
    notification_enabled,
    send_desktop_notification,
)


class NotificationEnabledTests(unittest.TestCase):
    def test_defaults_to_enabled_when_missing(self) -> None:
        settings = SettingsModel()
        settings._data.pop(NOTIFY_PROCESS_COMPLETE)
        self.assertTrue(notification_enabled(settings, NOTIFY_PROCESS_COMPLETE))

    def test_respects_disabled_setting(self) -> None:
        settings = SettingsModel()
        settings.set(NOTIFY_DOWNLOAD_COMPLETE, False)
        self.assertFalse(notification_enabled(settings, NOTIFY_DOWNLOAD_COMPLETE))


class SendDesktopNotificationTests(unittest.TestCase):
    @patch("ui.notifications.Gio.Notification.new")
    def test_skips_when_setting_disabled(self, new_notification) -> None:
        settings = SettingsModel()
        settings.set(NOTIFY_PROCESS_COMPLETE, False)
        send_desktop_notification(
            MagicMock(),
            settings,
            setting_key=NOTIFY_PROCESS_COMPLETE,
            ident="uvr-complete",
            title="Done",
            body="Finished",
        )
        new_notification.assert_not_called()


if __name__ == "__main__":
    unittest.main()
