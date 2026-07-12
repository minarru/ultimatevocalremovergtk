"""``Adw.Application`` entry point for the GTK4 UVR shell."""

import sys
from typing import Optional, Sequence

from gi.repository import Adw, Gio, GLib, Gtk

from core import SettingsModel, ensure_data_dir

from . import APP_ID
from .resources import load_application_styles, register_gresources
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


class UVRApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self._did_activate = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        from core.debug_log import debug, enabled
        from core.paths import DATA_DIR

        if enabled("ui"):
            try:
                adw_ver = f"{Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}"
            except Exception:  # noqa: BLE001
                adw_ver = "unknown"
            try:
                from __version__ import VERSION
            except Exception:  # noqa: BLE001
                VERSION = "unknown"
            debug(
                "ui",
                f"startup version={VERSION} data_dir={DATA_DIR} adw={adw_ver}",
            )
        # Provision the writable runtime-data tree (and seed bundled assets when
        # running from a read-only install) before any window/model work.
        ensure_data_dir()
        from core.external_tools import log_external_tools_once

        log_external_tools_once()
        register_gresources()
        load_application_styles()
        self._apply_saved_color_scheme()
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        open_output = Gio.SimpleAction.new(
            "open-output-folder", GLib.VariantType.new("s")
        )
        open_output.connect("activate", self._on_open_output_folder)
        self.add_action(open_output)

    def _on_open_output_folder(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        from .files import open_folder_in_file_manager

        window = self.props.active_window
        if window is None or param is None:
            return
        open_folder_in_file_manager(window, param.get_string())

    @staticmethod
    def _apply_saved_color_scheme():
        try:
            scheme = SettingsModel.load().get("color_scheme", "auto")
        except Exception:
            scheme = "auto"
        apply_color_scheme(scheme)

    def do_activate(self):
        self._did_activate = True
        register_gresources()
        from core.separate_import import warm_import_separate_engines

        warm_import_separate_engines()
        window = self.props.active_window
        if window is None:
            window = MainWindow(application=self)
        window.present()


def main(argv: Optional[Sequence[str]] = None) -> int:
    import os

    from core import glib_log
    from core.debug_log import announce_log_file, debug, enabled
    from core.torch_checkpoint import ensure_demucs_import_aliases

    ensure_demucs_import_aliases()

    glib_log.init()
    announce_log_file()
    if enabled("ui"):
        debug("ui", f"main pid={os.getpid()}")

    app = UVRApplication()
    try:
        status = app.run(list(argv) if argv is not None else sys.argv)
    except KeyboardInterrupt:
        # PyGObject calls app.quit() on SIGINT, then re-raises via
        # default_int_handler (e.g. sysprof-cli ^C while profiling).
        status = 130
        if enabled("ui"):
            debug("ui", "KeyboardInterrupt after main loop (SIGINT)")

    if enabled("ui"):
        if not app._did_activate:
            debug("ui", "duplicate instance rejected (single-instance)")
        debug("ui", f"exit status={status} activated={app._did_activate}")

    from .shutdown import finalize_process_exit

    finalize_process_exit(status)
