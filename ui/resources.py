"""Load bundled GResource assets (custom icon theme) at startup."""
import typing

import os
import shutil

from gi.repository import Gdk, Gio, GLib, Gtk

from core import paths

from . import APP_ID

#: GResource prefix (must match resources/compile_resources.sh).
RESOURCE_PREFIX = f"/{APP_ID.replace('.', '/')}"
#: GResource prefix for the bundled icon theme (must match compile_resources.sh).
ICON_RESOURCE_PREFIX = f"{RESOURCE_PREFIX}/icons"
STYLE_CSS_RESOURCE = f"{RESOURCE_PREFIX}/style.css"

_RESOURCE_PATH = os.path.join(os.path.dirname(__file__), "data", "uvr.gresource")
#: Source (uncompiled) stylesheet, used by the dev-time live CSS loader.
_SOURCE_STYLE_CSS = os.path.join(paths.BASE_PATH, "resources", "style.css")
#: Set ``UVR_DEV_CSS=1`` to load ``resources/style.css`` from disk (with live
#: reload) instead of the bundled GResource copy, so styling tweaks show up
#: without recompiling ``uvr.gresource``.
_DEV_CSS_ENV = "UVR_DEV_CSS"
_bundle_registered = False
_icon_theme_registered = False
_app_icon_registered = False
_styles_loaded = False
_dev_css_provider = None
_dev_css_monitor = None


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

    search_paths = list(theme.get_search_path() or [])
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
    prepend = getattr(theme, "prepend_resource_path", None)
    if callable(prepend):
        prepend(ICON_RESOURCE_PREFIX)
    else:
        theme.add_resource_path(ICON_RESOURCE_PREFIX)
    _icon_theme_registered = True
    return True


def register_gresources() -> bool:
    """Register the compiled GResource bundle and add its icon theme path.

    Safe to call more than once (e.g. from ``do_startup`` and again from
    ``do_activate`` if the display was not ready yet). Returns ``True`` when the
    bundle is loaded; the icon theme path is added whenever a display exists.

    Deliberately does **not** register the application icon: that costs two full
    ``Gtk.IconTheme`` scans (~312 ms) and only ``Adw.AboutDialog`` consumes the
    name. Call :func:`ensure_application_icon` at the point of use instead.
    """
    loaded = _register_bundle()
    _register_icon_theme()
    return loaded


def ensure_application_icon() -> bool:
    """Register ``packaging/<app-id>.png`` with the icon theme (idempotent).

    Deferred out of startup; call immediately before showing anything that
    names ``APP_ID`` as an icon.
    """
    return _register_application_icon()


def load_application_styles() -> bool:
    """Load bundled ``style.css`` at application priority (idempotent).

    When ``UVR_DEV_CSS`` is set, additionally load ``resources/style.css`` from
    disk at user priority (overriding the bundle) and watch it for changes so
    styling edits reload live without recompiling the GResource.
    """
    global _styles_loaded
    if _styles_loaded:
        return True
    display = Gdk.Display.get_default()
    if display is None:
        return False
    if not register_gresources():
        return False
    provider = Gtk.CssProvider()
    provider.load_from_resource(STYLE_CSS_RESOURCE)
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    _styles_loaded = True
    if os.environ.get(_DEV_CSS_ENV):
        _enable_dev_css(display)
    return True


def _enable_dev_css(display: typing.Any) -> None:
    """Load on-disk ``style.css`` at user priority with live reload."""
    global _dev_css_provider, _dev_css_monitor
    if _dev_css_provider is not None:
        return
    if not os.path.isfile(_SOURCE_STYLE_CSS):
        return

    provider = Gtk.CssProvider()
    _dev_css_provider = provider
    Gtk.StyleContext.add_provider_for_display(
        display,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER,
    )

    def reload_css(*_args: typing.Any) -> None:
        try:
            provider.load_from_path(_SOURCE_STYLE_CSS)
        except GLib.Error:
            pass

    reload_css()

    try:
        gfile = Gio.File.new_for_path(_SOURCE_STYLE_CSS)
        monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        monitor.connect("changed", lambda *_a: reload_css())
        _dev_css_monitor = monitor
    except GLib.Error:
        _dev_css_monitor = None
