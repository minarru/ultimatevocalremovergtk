"""Version / update view (port of UVR's update half of ``online_data_refresh``).

Shows the running application version + patch (from :mod:`__version__`, reused
verbatim) and checks the online catalogue for a newer build, exactly as UVR's
Settings "version status" area does. On Linux the update action opens UVR's
Linux installation instructions page (matching ``UPDATE_LINUX_REPO``); the check
runs on a worker thread and updates the UI via ``GLib.idle_add``.

Entry point: :func:`open_update_view` (wire to a ``win.updates`` action).
"""

import threading
import webbrowser

from gi.repository import Adw, GLib, Gtk

from data.constants import CHECK_FOR_UPDATES_TEXT, LOADING_VERSION_INFO_TEXT
from uvr_core.downloads import DownloadManager

from .dialogs.utils import present_modal_dialog, set_dialog_content


def _get_manager(app_context) -> DownloadManager:
    if app_context is None:
        return DownloadManager()
    manager = getattr(app_context, "_download_manager", None)
    if manager is None:
        manager = DownloadManager()
        setattr(app_context, "_download_manager", manager)
    return manager

from .dispatch import idle_on_main
class UpdateView:
    def __init__(self, parent, app_context=None):
        self.parent = parent
        self.context = app_context
        self.manager = _get_manager(app_context)
        self._update_link = ""

        self.dialog = Adw.Dialog()
        self.dialog.set_title("Application Version")
        self.dialog.set_content_width(480)
        self.dialog.set_follows_content_size(True)

        page = Adw.PreferencesPage()

        status = self.manager.update_status()
        version_group = Adw.PreferencesGroup(title="Application Version")
        version_group.add(Adw.ActionRow(title="Version", subtitle=status["version"] or "unknown"))
        version_group.add(Adw.ActionRow(title="Patch", subtitle=status["current"] or "unknown"))
        page.add(version_group)

        update_group = Adw.PreferencesGroup(title="Updates")
        self.status_row = Adw.ActionRow(title="Status", subtitle=LOADING_VERSION_INFO_TEXT)
        update_group.add(self.status_row)

        self.update_row = Adw.ActionRow(title="Get the latest version")
        self.update_button = Gtk.Button(label=CHECK_FOR_UPDATES_TEXT, valign=Gtk.Align.CENTER)
        self.update_button.connect("clicked", self._on_check_or_update)
        self.update_row.add_suffix(self.update_button)
        update_group.add(self.update_row)
        page.add(update_group)

        set_dialog_content(self.dialog, page)

    def present(self) -> None:
        present_modal_dialog(self.dialog, self.parent)
        self._check()

    def _check(self) -> None:
        self.status_row.set_subtitle(LOADING_VERSION_INFO_TEXT)
        self.update_button.set_sensitive(False)
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        self.manager.refresh()
        status = self.manager.update_status()
        idle_on_main(self._check_done, status)

    def _check_done(self, status) -> None:
        self.update_button.set_sensitive(True)
        self._update_link = status["update_link"]
        if not status["is_online"]:
            self.status_row.set_subtitle("No internet connection")
            self.update_button.set_label("Refresh")
        elif status["is_current"]:
            self.status_row.set_subtitle("UVR version is up to date")
            self.update_button.set_label(CHECK_FOR_UPDATES_TEXT)
        else:
            latest = status["latest"] or "available"
            self.status_row.set_subtitle(f"Update available: {latest}")
            self.update_button.set_label("Open Update Page")

    def _on_check_or_update(self, _button) -> None:
        label = self.update_button.get_label()
        if label in (CHECK_FOR_UPDATES_TEXT, "Refresh"):
            self._check()
        elif self._update_link:
            webbrowser.open_new_tab(self._update_link)


def open_update_view(parent_window, app_context=None):
    """Open the version / update view. Wire this to a ``win.updates`` action."""
    view = UpdateView(parent_window, app_context)
    view.present()
    return view
