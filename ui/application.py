"""``Adw.Application`` entry point for the GTK4 UVR shell."""

import sys
from typing import Optional, Sequence

from gi.repository import Adw, Gdk, Gio, Gtk

from uvr_core import SettingsModel, ensure_data_dir

from . import APP_ID
from .resources import register_gresources
from .window import MainWindow

#: String ``color_scheme`` settings values mapped to libadwaita scheme enums.
_COLOR_SCHEMES = {
    "auto": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


def apply_color_scheme(name: str) -> None:
    """Apply a ``color_scheme`` setting value via ``Adw.StyleManager``.

    Unknown values fall back to ``Adw.ColorScheme.DEFAULT`` (follow system).
    """
    scheme = _COLOR_SCHEMES.get(name, Adw.ColorScheme.DEFAULT)
    Adw.StyleManager.get_default().set_color_scheme(scheme)

#: Empty-state banners (tagged ``.app-banner``) are inset and rounded rather than
#: spanning edge-to-edge. The accent background lives on the banner's inner
#: ``revealer > widget`` node, so the radius/margin must target it there.
_CSS = b"""
.app-banner > revealer > widget {
  margin: 8px 0;
  border-radius: 12px;
}

.drop-highlight {
  box-shadow: inset 0 0 0 2px @accent_color;
  background-color: alpha(@accent_color, 0.1);
  border-radius: 12px;
}

.uvr-log-panel {
  min-width: 520px;
  border-radius: 16px 16px 12px 12px;
  background-image: none;
  background-color: @window_bg_color;
  color: @card_fg_color;
  border: 1px solid alpha(@borders, 0.45);
  box-shadow: 0 2px 6px alpha(@shade_color, 0.08),
              0 8px 24px alpha(@shade_color, 0.16);
}

.uvr-log-expander-arrow image {
  transition: -gtk-icon-transform 200ms cubic-bezier(0.4, 0, 0.2, 1);
  -gtk-icon-transform: rotate(0deg);
}

.uvr-log-expander-arrow:checked image {
  -gtk-icon-transform: rotate(180deg);
}

.uvr-run-controls {
  padding: 12px 12px 12px;
}

.uvr-progress-section {
  margin-bottom: 4px;
}

.uvr-progress-label {
  margin-top: 4px;
  margin-bottom: 8px;
  opacity: 0.85;
}

.uvr-log-meta {
  padding: 0 0 8px;
  min-height: 32px;
}

.uvr-log-body-wrap {
  padding: 0 0 4px;
}

.uvr-run-actions {
  min-height: 36px;
}

.uvr-log-body {
  min-height: 200px; /* keep in sync with _LOG_BODY_HEIGHT in log_panel.py */
}

.uvr-log-console {
  background-color: alpha(@window_fg_color, 0.04);
}

.uvr-log-empty {
  padding: 20px 16px;
}

.uvr-log-empty .dim-label {
  opacity: 0.75;
}

.uvr-log-console text {
  padding: 2px 0;
}
"""


class UVRApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self._did_activate = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        from uvr_core.debug_log import debug, enabled

        if enabled("ui"):
            debug("ui", "UVR_DEBUG ui tracing enabled")
        # Provision the writable runtime-data tree (and seed bundled assets when
        # running from a read-only install) before any window/model work.
        ensure_data_dir()
        register_gresources()
        self._load_styles()
        self._apply_saved_color_scheme()
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

    @staticmethod
    def _apply_saved_color_scheme():
        try:
            scheme = SettingsModel.load().get("color_scheme", "auto")
        except Exception:
            scheme = "auto"
        apply_color_scheme(scheme)

    @staticmethod
    def _load_styles():
        display = Gdk.Display.get_default()
        if display is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        self._did_activate = True
        register_gresources()
        from uvr_core.separate_import import warm_import_separate_engines

        warm_import_separate_engines()
        window = self.props.active_window
        if window is None:
            window = MainWindow(application=self)
        window.present()


def main(argv: Optional[Sequence[str]] = None) -> int:
    import os

    from uvr_core.debug_log import announce_log_file, debug, enabled

    if enabled():
        announce_log_file()
        debug("ui", f"uvr_gtk main pid={os.getpid()}")

    app = UVRApplication()
    try:
        status = app.run(list(argv) if argv is not None else sys.argv)
    except KeyboardInterrupt:
        # PyGObject calls app.quit() on SIGINT, then re-raises via
        # default_int_handler (e.g. sysprof-cli ^C while profiling).
        status = 130
        if enabled("ui"):
            debug("ui", "KeyboardInterrupt after main loop (SIGINT)")

    if enabled():
        if not app._did_activate:
            debug("ui", "duplicate instance rejected (single-instance, activate not called)")
        debug("ui", f"uvr_gtk exit status={status}")

    from .shutdown import finalize_process_exit

    finalize_process_exit(status)
