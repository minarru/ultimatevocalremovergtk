"""Download Center entry point, VIP / manual dialogs, and shared download services."""

from __future__ import annotations

import webbrowser

from gi.repository import Adw, Gtk

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    DONATE_LINK_BMAC,
    DONATE_LINK_PATREON,
    MDX_ARCH_TYPE,
    VR_ARCH_TYPE,
)
from core.debug_log import debug
from core.download_queue import DownloadQueue
from core.downloads import DownloadManager

from .dialogs.utils import configure_dialog_width, fill_dialog_width, present_modal_dialog, set_dialog_content
from .download_center import DownloadCenterWindow


def _get_manager(app_context) -> DownloadManager:
    manager = getattr(app_context, "_download_manager", None)
    if manager is None:
        manager = DownloadManager()
        setattr(app_context, "_download_manager", manager)
    return manager


def _get_queue(app_context, manager: DownloadManager) -> DownloadQueue:
    queue = getattr(app_context, "_download_queue", None)
    if queue is None:
        queue = DownloadQueue(manager, on_changed=lambda: None)
        setattr(app_context, "_download_queue", queue)
    return queue


def open_download_center(parent_window, app_context, on_models_changed=None):
    """Open or raise the Download Center utility window."""
    center = getattr(app_context, "_download_center_window", None)
    if center is not None:
        center.present()
        return center

    manager = _get_manager(app_context)
    queue = _get_queue(app_context, manager)
    center = DownloadCenterWindow(
        parent_window,
        app_context,
        manager,
        queue,
        on_models_changed=on_models_changed,
    )
    app_context._download_center_window = center
    center.present()
    return center


# ---------------------------------------------------------------------------
# VIP code dialog
# ---------------------------------------------------------------------------

def open_vip_code_dialog(parent, app_context, on_validated=None):
    manager = _get_manager(app_context)
    settings = app_context.settings

    dialog = Adw.Dialog()
    dialog.set_title("Unlock VIP models")
    configure_dialog_width(dialog, parent, fallback=520)

    toast_overlay = Adw.ToastOverlay()
    fill_dialog_width(toast_overlay)

    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup(
        title="Download code",
        description=(
            "Obtain a code from the links below. Donations are appreciated but not required."
        ),
    )
    page.add(group)

    code_row = Adw.EntryRow(title="Code")
    code_row.set_text(settings.get("user_code", ""))
    group.add(code_row)

    def toast(message: str) -> None:
        toast_overlay.add_toast(Adw.Toast.new(message))

    def on_confirm(_button):
        code = code_row.get_text().strip()
        unlocked = manager.validate_vip_code(code)
        if unlocked:
            settings.set("user_code", code)
            app_context.save_settings(trigger="vip")
            toast("VIP models unlocked")
        else:
            toast("Incorrect code")
        debug("download", f"ui vip_code_confirm unlocked={unlocked}")
        if on_validated is not None:
            on_validated(unlocked)

    confirm_button = Gtk.Button(label="Unlock", valign=Gtk.Align.CENTER)
    confirm_button.add_css_class("suggested-action")
    confirm_button.connect("clicked", on_confirm)
    code_row.add_suffix(confirm_button)

    links_group = Adw.PreferencesGroup(title="Support UVR")
    for title, link in (
        ("Patreon", DONATE_LINK_PATREON),
        ("Buy Me a Coffee", DONATE_LINK_BMAC),
    ):
        row = Adw.ActionRow(title=title)
        button = Gtk.Button(icon_name="adw-external-link-symbolic", valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _b, url=link: webbrowser.open_new_tab(url))
        row.add_suffix(button)
        row.set_activatable_widget(button)
        links_group.add(row)
    page.add(links_group)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    content.set_margin_top(12)
    content.set_margin_bottom(12)
    content.set_margin_start(12)
    content.set_margin_end(12)
    fill_dialog_width(content)
    fill_dialog_width(page)
    content.append(page)

    toast_overlay.set_child(content)
    set_dialog_content(dialog, toast_overlay)
    present_modal_dialog(dialog, parent)
    return dialog


# ---------------------------------------------------------------------------
# Manual downloads dialog
# ---------------------------------------------------------------------------

def open_manual_downloads(parent, app_context):
    manager = _get_manager(app_context)
    data = manager.manual_download_data()

    dialog = Adw.Dialog()
    dialog.set_title("Manual downloads")
    configure_dialog_width(dialog, parent, fallback=520)
    dialog.set_content_height(560)

    page = Adw.PreferencesPage()

    catalogue = [
        ("VR models", VR_ARCH_TYPE, data["vr"]),
        ("MDX-Net models", MDX_ARCH_TYPE, data["mdx"]),
        ("Demucs models", DEMUCS_ARCH_TYPE, data["demucs"]),
    ]

    for group_title, arch, models in catalogue:
        if not models:
            continue
        group = Adw.PreferencesGroup(title=group_title)
        for selectable, model in models.items():
            row = Adw.ExpanderRow()
            row.set_use_markup(False)
            row.set_title(selectable)
            links = DownloadManager.manual_links(arch, model)
            for label, url in links:
                link_row = Adw.ActionRow()
                link_row.set_use_markup(False)
                link_row.set_title(label)
                link_row.set_subtitle(url)
                open_button = Gtk.Button(icon_name="adw-external-link-symbolic", valign=Gtk.Align.CENTER)
                open_button.connect("clicked", lambda _b, u=url: webbrowser.open_new_tab(u))
                link_row.add_suffix(open_button)
                link_row.set_activatable_widget(open_button)
                row.add_row(link_row)
            dir_row = Adw.ActionRow()
            dir_row.set_use_markup(False)
            dir_row.set_title("Install folder")
            dir_row.set_subtitle(DownloadManager.model_directory(arch, selectable))
            dir_button = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
            dir_button.connect(
                "clicked",
                lambda _b, d=DownloadManager.model_directory(arch, selectable): webbrowser.open(f"file://{d}"),
            )
            dir_row.add_suffix(dir_button)
            row.add_row(dir_row)
            group.add(row)
        page.add(group)

    scroller = Gtk.ScrolledWindow(propagate_natural_height=False, vexpand=True)
    fill_dialog_width(scroller)
    fill_dialog_width(page)
    scroller.set_child(page)
    set_dialog_content(dialog, scroller)
    present_modal_dialog(dialog, parent)
    return dialog

