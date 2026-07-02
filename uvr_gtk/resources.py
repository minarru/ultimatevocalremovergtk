"""Load bundled GResource assets (custom icon theme) at startup."""

import os
import shutil

from gi.repository import Gdk, Gio, GLib, Gtk

from uvr_core import paths

from . import APP_ID

#: GResource prefix for the bundled icon theme (must match compile_resources.sh).
ICON_RESOURCE_PREFIX = f"/{APP_ID.replace('.', '/')}/icons"

_RESOURCE_PATH = os.path.join(os.path.dirname(__file__), "data", "uvr.gresource")
_bundle_registered = False
_icon_theme_registered = False
_app_icon_registered = False


def resource_bundle_path() -> str:
    """Absolute path to the compiled ``uvr.gresource`` binary."""
    return _RESOURCE_PATH


def _packaging_app_icon_path() -> str:
    return os.path.join(paths.BASE_PATH, "packaging", f"{APP_ID}.png")


def _register_application_icon() -> bool:
    """Expose ``packaging/<app-id>.png`` to ``Gtk.IconTheme`` for About dialogs.

    ``Adw.AboutDialog`` takes an *icon name*, not a file path. The PNG is staged
    under ``hicolor/256x256/apps/`` and added as a filesystem search path when
    the bundled GResource does not already provide it.
    """
    global _app_icon_registered
    if _app_icon_registered:
        return True

    display = Gdk.Display.get_default()
    if display is None:
        return False

    theme = Gtk.IconTheme.get_for_display(display)
    if theme.has_icon(APP_ID):
        _app_icon_registered = True
        return True

    png = _packaging_app_icon_path()
    if not os.path.isfile(png):
        return False

    icons_root = os.path.join(os.path.dirname(__file__), "data", "icons")
    icon_dest = os.path.join(icons_root, "hicolor", "256x256", "apps", f"{APP_ID}.png")
    if not os.path.isfile(icon_dest):
        os.makedirs(os.path.dirname(icon_dest), exist_ok=True)
        shutil.copy2(png, icon_dest)

    search_paths = list(theme.get_search_path())
    if icons_root not in search_paths:
        theme.add_search_path(icons_root)

    _app_icon_registered = theme.has_icon(APP_ID)
    return _app_icon_registered


def _register_bundle() -> bool:
    global _bundle_registered
    if _bundle_registered:
        return True
    if not os.path.isfile(_RESOURCE_PATH):
        return False
    try:
        resource = Gio.Resource.load(_RESOURCE_PATH)
        Gio.resources_register(resource)
    except GLib.Error:
        return False
    _bundle_registered = True
    return True


def _register_icon_theme() -> bool:
    """Attach the bundled icon theme to the default display (idempotent)."""
    global _icon_theme_registered
    if _icon_theme_registered:
        return True
    display = Gdk.Display.get_default()
    if display is None:
        return False
    theme = Gtk.IconTheme.get_for_display(display)
    if hasattr(theme, "prepend_resource_path"):
        theme.prepend_resource_path(ICON_RESOURCE_PREFIX)
    else:
        theme.add_resource_path(ICON_RESOURCE_PREFIX)
    _icon_theme_registered = True
    return True


def register_gresources() -> bool:
    """Register the compiled GResource bundle and add its icon theme path.

    Safe to call more than once (e.g. from ``do_startup`` and again from
    ``do_activate`` if the display was not ready yet). Returns ``True`` when the
    bundle is loaded; the icon theme path is added whenever a display exists.
    """
    loaded = _register_bundle()
    _register_icon_theme()
    _register_application_icon()
    return loaded
