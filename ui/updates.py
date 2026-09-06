"""Version / update view for the GTK fork release channel.

Shows the running application version and checks ``packaging/release.json`` on
Codeberg for a newer source release. Upgrade is documented on the release page
(``git pull`` + ``install_packages.sh``), not an in-app binary download.

Entry point: :func:`open_update_view` (wire to a ``win.updates`` action).
"""

import threading
import typing

from gi.repository import Adw, Gtk

from bundled.constants import FORK_RELEASE_PAGE, LOADING_VERSION_INFO_TEXT
from core.downloads import DownloadManager

from .dialogs.utils import present_modal_dialog
from .dispatch import idle_on_main
from .files import open_uri_in_browser
from .template import load_builder, object_from_builder


def _get_manager(app_context: typing.Any) -> DownloadManager:
    if app_context is None:
        return DownloadManager()
    return app_context.download_manager


class UpdateView:
    def __init__(self, parent: typing.Any, app_context: typing.Any = None):
        self.parent = parent
        self.context = app_context
        self.manager = _get_manager(app_context)
        self._update_link = FORK_RELEASE_PAGE

        builder = load_builder("update-view")
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        status = self.manager.update_status()
        version_row = object_from_builder(builder, "version_row", Adw.ActionRow)
        version_row.set_subtitle(str(status["version"] or "unknown"))
        upstream_row = object_from_builder(builder, "upstream_row", Adw.ActionRow)
        if status.get("upstream_base"):
            upstream_row.set_subtitle(str(status["upstream_base"]))
            upstream_row.set_visible(True)
        self.status_row = object_from_builder(builder, "status_row", Adw.ActionRow)
        self.status_row.set_subtitle(LOADING_VERSION_INFO_TEXT)
        self.upgrade_row = object_from_builder(builder, "upgrade_row", Adw.ActionRow)
        self.update_row = object_from_builder(builder, "update_row", Adw.ActionRow)
        self.update_button = object_from_builder(builder, "update_button", Gtk.Button)
        self.update_button.connect("clicked", self._on_check_or_update)

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


def open_update_view(parent_window: typing.Any, app_context: typing.Any = None):
    """Open the version / update view. Wire this to a ``win.updates`` action."""
    view = UpdateView(parent_window, app_context)
    view.present()
    return view
