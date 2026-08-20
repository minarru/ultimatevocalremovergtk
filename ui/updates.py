"""Version / update view for the GTK fork release channel.

Shows the running application version and checks ``packaging/release.json`` on
Codeberg for a newer source release. Upgrade is documented on the release page
(``git pull`` + ``install_packages.sh``), not an in-app binary download.

Entry point: :func:`open_update_view` (wire to a ``win.updates`` action).
"""
import typing

import threading

from gi.repository import Adw, Gtk

from bundled.constants import FORK_RELEASE_PAGE, LOADING_VERSION_INFO_TEXT
from core.downloads import DownloadManager

from .dialogs.utils import present_modal_dialog, set_dialog_content
from .dispatch import idle_on_main
from .files import open_uri_in_browser


def _get_manager(app_context: typing.Any) -> DownloadManager:
    if app_context is None:
        return DownloadManager()
    manager = getattr(app_context, "download_manager", None)
    if isinstance(manager, DownloadManager):
        return manager
    existing = getattr(app_context, "_download_manager", None)
    if existing is None:
        existing = DownloadManager()
        setattr(app_context, "_download_manager", existing)
    return existing


class UpdateView:
    def __init__(self, parent: typing.Any, app_context: typing.Any=None):
        self.parent = parent
        self.context = app_context
        self.manager = _get_manager(app_context)
        self._update_link = FORK_RELEASE_PAGE

        self.dialog = Adw.Dialog()
        self.dialog.set_title("Application Version")
        self.dialog.set_content_width(480)
        self.dialog.set_follows_content_size(True)

        page = Adw.PreferencesPage()

        status = self.manager.update_status()
        version_group = Adw.PreferencesGroup(title="Application Version")
        version_group.add(
            Adw.ActionRow(title="Version", subtitle=str(status["version"] or "unknown"))
        )
        if status.get("upstream_base"):
            version_group.add(
                Adw.ActionRow(
                    title="Based on",
                    subtitle=str(status["upstream_base"]),
                )
            )
        page.add(version_group)

        update_group = Adw.PreferencesGroup(title="Updates")
        self.status_row = Adw.ActionRow(title="Status", subtitle=LOADING_VERSION_INFO_TEXT)
        update_group.add(self.status_row)

        self.upgrade_row = Adw.ActionRow(title="Upgrade")
        self.upgrade_row.set_visible(False)
        update_group.add(self.upgrade_row)

        self.update_row = Adw.ActionRow(title="Get the latest version")
        self.update_button = Gtk.Button(label="Check again", valign=Gtk.Align.CENTER)
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
        self.upgrade_row.set_visible(False)
        self.update_button.set_sensitive(False)
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        status = self.manager.check_release()
        idle_on_main(self._check_done, status)

    def _check_done(self, status: typing.Any) -> None:
        self.update_button.set_sensitive(True)
        self._update_link = status.get("update_link") or FORK_RELEASE_PAGE

        if not status.get("is_online"):
            self.status_row.set_subtitle("Could not check for updates (offline)")
            self.update_button.set_label("Check again")
        elif status.get("is_current"):
            self.status_row.set_subtitle("This release is up to date")
            self.update_button.set_label("View release notes")
        else:
            latest = status.get("latest") or "available"
            self.status_row.set_subtitle(
                f"New release available: {latest} — upgrade from source (see release notes)"
            )
            instructions = status.get("upgrade_instructions") or ""
            if instructions:
                self.upgrade_row.set_subtitle(str(instructions))
                self.upgrade_row.set_visible(True)
            self.update_button.set_label("View release notes")

    def _on_check_or_update(self, _button: typing.Any) -> None:
        label = self.update_button.get_label()
        if label == "Check again":
            self._check()
        elif self._update_link:
            open_uri_in_browser(self.parent, self._update_link)


def open_update_view(parent_window: typing.Any, app_context: typing.Any=None):
    """Open the version / update view. Wire this to a ``win.updates`` action."""
    view = UpdateView(parent_window, app_context)
    view.present()
    return view
