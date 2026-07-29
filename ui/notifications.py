"""Desktop notification helpers with per-type settings gates."""

from __future__ import annotations

from typing import Optional

from gi.repository import Gio, GLib, Gtk

from core.debug_log import debug

from . import APP_ID
from .settings_bind import get_flat

NOTIFY_PROCESS_COMPLETE = "notify_process_complete"
NOTIFY_PROCESS_FAILED = "notify_process_failed"
NOTIFY_DOWNLOAD_COMPLETE = "notify_download_complete"
NOTIFY_DOWNLOAD_FAILED = "notify_download_failed"

NOTIFICATION_SETTING_KEYS = (
    NOTIFY_PROCESS_COMPLETE,
    NOTIFY_PROCESS_FAILED,
    NOTIFY_DOWNLOAD_COMPLETE,
    NOTIFY_DOWNLOAD_FAILED,
)

OPEN_OUTPUT_FOLDER_ACTION = "app.open-output-folder"
_OPEN_FOLDER_LABEL = "Open Folder"

_NOTIFY_ICONS = {
    "uvr-complete": "emblem-ok-symbolic",
    "uvr-failed": "dialog-error-symbolic",
    "uvr-download-complete": "folder-download-symbolic",
    "uvr-download-failed": "dialog-warning-symbolic",
}


def notification_enabled(settings, key: str) -> bool:
    if key not in NOTIFICATION_SETTING_KEYS:
        return True
    return bool(get_flat(settings, key, True))


def send_desktop_notification(
    app: Optional[Gtk.Application],
    settings,
    *,
    setting_key: str,
    ident: str,
    title: str,
    body: str,
    output_dir: Optional[str] = None,
) -> None:
    """Send a ``Gio.Notification`` when ``setting_key`` is enabled in settings."""
    if app is None:
        debug("download", f"notification skip ident={ident} reason=no_app")
        return
    if not notification_enabled(settings, setting_key):
        debug("download", f"notification skip ident={ident} reason=disabled key={setting_key}")
        return
    try:
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        icon_name = _NOTIFY_ICONS.get(ident, APP_ID)
        try:
            notification.set_icon(Gio.ThemedIcon.new(icon_name))
        except Exception:  # noqa: BLE001 - icon is best-effort
            pass
        if output_dir:
            target = GLib.Variant("s", output_dir)
            notification.add_button_with_target(
                _OPEN_FOLDER_LABEL,
                OPEN_OUTPUT_FOLDER_ACTION,
                target,
            )
        app.send_notification(ident, notification)
        debug("download", f"notification sent ident={ident} title={title!r}")
    except Exception as exc:  # noqa: BLE001 - notifications must never break the UI
        debug("download", f"notification failed ident={ident} err={type(exc).__name__}: {exc}")
