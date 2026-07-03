"""Download Center (GTK4 / libadwaita port of UVR's ``tab3`` download menu).

Provides :func:`open_download_center`, the entry point the main window's
``win.download`` action calls. It reuses :class:`uvr_core.downloads.DownloadManager`
for all network/disk work and mirrors UVR's behaviour:

* pick a network (VR Arch / MDX-Net / Demucs) and a not-yet-downloaded model;
* download with a live progress bar and a Stop button (cooperative cancel);
* refresh the catalogue, unlock VIP models with a download code, and fall back
  to per-link manual downloads.

Every network/IO operation runs on a worker thread; results are marshalled back
onto the GTK main loop with ``GLib.idle_add`` so widgets are only ever touched
from the main thread. Construction never imports ``torch``.
"""

import threading
import webbrowser

from gi.repository import Adw, GLib, Gtk

from data.constants import (
    DEMUCS_ARCH_TYPE,
    DONATE_LINK_BMAC,
    DONATE_LINK_PATREON,
    MDX_ARCH_TYPE,
    NO_CONNECTION,
    NO_MODEL,
    NO_NEW_MODELS,
    VR_ARCH_TYPE,
)
from uvr_core.downloads import DownloadManager

from .dialogs.utils import configure_dialog_width, fill_dialog_width, present_modal_dialog, set_dialog_content
from .help_text import VIP_DOWNLOAD_CODE_HINT
from .hints import set_tooltip
from .widgets.rows import get_combo_value, make_combo_row, set_combo_values, use_wrapping_list

# Network label -> arch-type constant (the radio buttons in UVR's tab3).
_NETWORKS = [
    ("VR Arch", VR_ARCH_TYPE),
    ("MDX-Net", MDX_ARCH_TYPE),
    ("Demucs", DEMUCS_ARCH_TYPE),
]


def _get_manager(app_context) -> DownloadManager:
    """Reuse a single :class:`DownloadManager` per app context across opens."""
    manager = getattr(app_context, "_download_manager", None)
    if manager is None:
        manager = DownloadManager()
        setattr(app_context, "_download_manager", manager)
    return manager

from .dispatch import idle_on_main
class DownloadCenter:
    def __init__(self, parent, app_context, on_models_changed=None):
        self.parent = parent
        self.context = app_context
        self.settings = app_context.settings
        self.manager = _get_manager(app_context)
        self._on_models_changed = on_models_changed
        self._available = {}
        self._stop_event = None
        self._busy = False

        # Restore a previously-entered VIP code so VIP models stay unlocked.
        saved_code = self.settings.get("user_code", "")
        if saved_code:
            self.manager.validate_vip_code(saved_code)

        self.window = Adw.Window(title="Application Download Center")
        self.window.set_default_size(520, 0)
        if parent is not None:
            self.window.set_transient_for(parent)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.key_button = Gtk.Button(icon_name="dialog-password-symbolic")
        set_tooltip(self.key_button, VIP_DOWNLOAD_CODE_HINT)
        self.key_button.connect("clicked", self._on_vip_code)
        header.pack_start(self.key_button)
        toolbar.add_top_bar(header)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self._build_body())
        toolbar.set_content(self.toast_overlay)
        self.window.set_content(toolbar)

    # -- Layout -----------------------------------------------------------------

    def _build_body(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        select_group = Adw.PreferencesGroup(title="Select Download")
        self.network_row = make_combo_row("Network", [label for label, _ in _NETWORKS])
        use_wrapping_list(self.network_row)
        if hasattr(self.network_row, "set_enable_search"):
            self.network_row.set_enable_search(False)
        self.network_row.connect("notify::selected", self._on_network_changed)
        select_group.add(self.network_row)

        self.model_row = make_combo_row("Model", [NO_MODEL])
        use_wrapping_list(self.model_row)
        select_group.add(self.model_row)
        page.add(select_group)

        action_group = Adw.PreferencesGroup()
        download_row = Adw.ActionRow(title="Download selected model")
        self.download_button = Gtk.Button(label="Download", valign=Gtk.Align.CENTER)
        self.download_button.add_css_class("suggested-action")
        self.download_button.connect("clicked", self._on_download)
        download_row.add_suffix(self.download_button)
        self.stop_button = Gtk.Button(label="Stop", valign=Gtk.Align.CENTER)
        self.stop_button.add_css_class("destructive-action")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", self._on_stop)
        download_row.add_suffix(self.stop_button)
        action_group.add(download_row)

        refresh_row = Adw.ActionRow(title="Refresh List", subtitle="Re-check the online model catalogue.")
        refresh_button = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        refresh_button.connect("clicked", lambda *_: self.start_refresh())
        refresh_row.add_suffix(refresh_button)
        self.refresh_button = refresh_button
        action_group.add(refresh_row)

        manual_row = Adw.ActionRow(title="Try Manual Download", subtitle="Open direct links for any model.")
        manual_button = Gtk.Button(label="Manual\u2026", valign=Gtk.Align.CENTER)
        manual_button.connect("clicked", self._on_manual)
        manual_row.add_suffix(manual_button)
        action_group.add(manual_row)
        page.add(action_group)

        progress_group = Adw.PreferencesGroup()
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_margin_top(6)
        self.progress.set_margin_bottom(6)
        progress_group.add(self.progress)
        self.info_row = Adw.ActionRow(title="Loading version information\u2026")
        progress_group.add(self.info_row)
        page.add(progress_group)

        self._set_controls_sensitive(False)
        return page

    # -- Refresh ----------------------------------------------------------------

    def present(self) -> None:
        self.window.present()
        self.start_refresh()

    def start_refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._set_info("Refreshing model list\u2026")
        self._set_controls_sensitive(False)
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        is_online = self.manager.refresh()
        # Auto-refresh the model-data mappers when the user opted in (matches
        # UVR's is_auto_update_model_params behaviour on a successful check).
        if is_online and self.settings.get("is_auto_update_model_params", True):
            self.manager.update_model_settings(self.context.repo)
        idle_on_main(self._refresh_done, is_online)

    def _refresh_done(self, is_online: bool) -> None:
        self._busy = False
        if not is_online:
            self._set_info(NO_CONNECTION)
            self._set_controls_sensitive(False)
            self.refresh_button.set_sensitive(True)
            set_combo_values(self.model_row, [NO_CONNECTION])
            return
        self._available = self.manager.available_downloads()
        self._set_controls_sensitive(True)
        self._populate_models()
        self._set_info("Ready.")

    # -- Selection --------------------------------------------------------------

    def _current_arch(self) -> str:
        index = self.network_row.get_selected()
        index = 0 if index < 0 else index
        return _NETWORKS[index][1]

    def _populate_models(self) -> None:
        arch = self._current_arch()
        models = self._available.get(arch) or [NO_NEW_MODELS]
        set_combo_values(self.model_row, models)

    def _on_network_changed(self, *_args) -> None:
        if self._available:
            self._populate_models()

    # -- Download ---------------------------------------------------------------

    def _on_download(self, _button) -> None:
        if self._busy:
            return
        selection = get_combo_value(self.model_row)
        if not selection or selection in (NO_MODEL, NO_NEW_MODELS, NO_CONNECTION):
            self._set_info(NO_MODEL)
            return
        jobs = self.manager.resolve(selection, self._current_arch())
        if not jobs:
            self._set_info(NO_MODEL)
            return

        self._busy = True
        self._stop_event = threading.Event()
        self._set_controls_sensitive(False)
        self.stop_button.set_sensitive(True)
        self.progress.set_fraction(0.0)
        threading.Thread(target=self._download_worker, args=(jobs,), daemon=True).start()

    def _download_worker(self, jobs) -> None:
        try:
            result = self.manager.download(
                jobs,
                on_progress=lambda f: idle_on_main(self._set_progress, f),
                on_info=lambda text: idle_on_main(self._set_info, text),
                stop_event=self._stop_event,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced via the error log + UI
            from uvr_core.debug_log import debug

            debug("download", f"download failed error={type(exc).__name__}: {exc}")
            from .errorlog import log_error

            log_error("Downloading Item", exc)
            idle_on_main(self._download_done, "failed", str(type(exc).__name__))
            return
        idle_on_main(self._download_done, result, None)

    def _download_done(self, result: str, error_name) -> None:
        self._busy = False
        self.stop_button.set_sensitive(False)
        if result == "complete":
            self.progress.set_fraction(1.0)
            self._set_info("Download Complete")
            # Re-list so the freshly-downloaded model drops off the menu.
            self._available = self.manager.available_downloads()
            self._populate_models()
            # Notify the main window so its method dropdowns pick up the new model.
            if self._on_models_changed is not None:
                self._on_models_changed()
        elif result == "stopped":
            self._set_info("Download Stopped")
        elif result == "exists":
            self._set_info("File already exists!")
        else:
            self._set_info(f"Download Failed ({error_name})" if error_name else "Download Failed")
        self._set_controls_sensitive(True)

    def _on_stop(self, _button) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        self.stop_button.set_sensitive(False)
        self._set_info("Stopping\u2026")

    # -- VIP code ---------------------------------------------------------------

    def _on_vip_code(self, _button) -> None:
        open_vip_code_dialog(self.window, self.context, on_validated=self._on_vip_validated)

    def _on_vip_validated(self, unlocked: bool) -> None:
        if unlocked and self._available:
            self._available = self.manager.available_downloads()
            self._populate_models()
            self._toast("VIP Models Added!")

    # -- Manual -----------------------------------------------------------------

    def _on_manual(self, _button) -> None:
        open_manual_downloads(self.window, self.context)

    # -- Helpers ----------------------------------------------------------------

    def _set_controls_sensitive(self, sensitive: bool) -> None:
        for widget in (self.network_row, self.model_row, self.download_button,
                       self.refresh_button, self.key_button):
            widget.set_sensitive(sensitive)

    def _set_info(self, text: str) -> None:
        self.info_row.set_title(text)

    def _set_progress(self, fraction: float) -> None:
        self.progress.set_fraction(max(0.0, min(1.0, fraction)))
        self.progress.set_text(f"{int(fraction * 100)} %")

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))


# ---------------------------------------------------------------------------
# VIP code dialog (port of pop_up_user_code_input)
# ---------------------------------------------------------------------------

def open_vip_code_dialog(parent, app_context, on_validated=None):
    manager = _get_manager(app_context)
    settings = app_context.settings

    dialog = Adw.Dialog()
    dialog.set_title("Input Code")
    configure_dialog_width(dialog, parent, fallback=520)

    toast_overlay = Adw.ToastOverlay()
    fill_dialog_width(toast_overlay)

    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup(
        title="User Download Codes",
        description=(
            "Obtain codes by visiting one of the links below. From there you can "
            "donate, pledge, or just obtain the code! (Donations are not required.)"
        ),
    )
    page.add(group)

    code_row = Adw.EntryRow(title="Download Code")
    code_row.set_text(settings.get("user_code", ""))
    group.add(code_row)

    def toast(message: str) -> None:
        toast_overlay.add_toast(Adw.Toast.new(message))

    def on_confirm(_button):
        code = code_row.get_text().strip()
        unlocked = manager.validate_vip_code(code)
        if unlocked:
            settings.set("user_code", code)
            app_context.save_settings()
            toast("VIP models added")
        else:
            toast("Incorrect code")
        if on_validated is not None:
            on_validated(unlocked)

    confirm_button = Gtk.Button(label="Add", valign=Gtk.Align.CENTER)
    confirm_button.add_css_class("suggested-action")
    confirm_button.connect("clicked", on_confirm)
    code_row.add_suffix(confirm_button)

    links_group = Adw.PreferencesGroup(title="Support UVR")
    for title, link in (("UVR Patreon Link", DONATE_LINK_PATREON),
                        ('UVR "Buy Me a Coffee" Link', DONATE_LINK_BMAC)):
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
# Manual downloads dialog (port of menu_manual_downloads)
# ---------------------------------------------------------------------------

def open_manual_downloads(parent, app_context):
    manager = _get_manager(app_context)
    data = manager.manual_download_data()

    dialog = Adw.Dialog()
    dialog.set_title("Manual Downloads")
    configure_dialog_width(dialog, parent, fallback=520)
    dialog.set_content_height(560)

    page = Adw.PreferencesPage()

    catalogue = [
        ("VR Models", VR_ARCH_TYPE, data["vr"]),
        ("MDX-Net Models", MDX_ARCH_TYPE, data["mdx"]),
        ("Demucs Models", DEMUCS_ARCH_TYPE, data["demucs"]),
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
            dir_row.set_title("Selected Model Placement Path")
            dir_row.set_subtitle(DownloadManager.model_directory(arch, selectable))
            dir_button = Gtk.Button(label="Open Folder", valign=Gtk.Align.CENTER)
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def open_download_center(parent_window, app_context, on_models_changed=None):
    """Open the Download Center. Wire this to the ``win.download`` action."""
    center = DownloadCenter(parent_window, app_context, on_models_changed=on_models_changed)
    center.present()
    return center
