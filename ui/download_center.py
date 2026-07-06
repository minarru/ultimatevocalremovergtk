"""Download Center window — catalogue browser and download queue."""

from __future__ import annotations

import threading

from gi.repository import Adw, Gio, Gtk

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    NO_CONNECTION,
    NO_NEW_MODELS,
    VR_ARCH_TYPE,
)
from core.debug_log import debug
from core.download_queue import DownloadQueue, DownloadQueueItem
from core.downloads import DownloadManager

from .dispatch import idle_on_main
from .help_text import VIP_DOWNLOAD_CODE_HINT
from .hints import set_tooltip
from .markup import set_row_subtitle, set_row_title
from .spacing import set_inset

_NETWORKS = [
    ("VR Arch", VR_ARCH_TYPE),
    ("MDX-Net", MDX_ARCH_TYPE),
    ("Demucs", DEMUCS_ARCH_TYPE),
]

_CLAMP_MAX_WIDTH = 800


class DownloadCenterWindow:
    """Non-modal utility window for browsing and queueing model downloads."""

    def __init__(
        self,
        parent,
        app_context,
        manager: DownloadManager,
        queue: DownloadQueue,
        on_models_changed=None,
    ):
        self.parent = parent
        self.context = app_context
        self.settings = app_context.settings
        self.manager = manager
        self.queue = queue
        self._on_models_changed = on_models_changed

        self._available: dict[str, list[str]] = {}
        self._refreshing = False
        self._size_lookup_id = 0
        self._row_checks: dict[tuple[str, str], Gtk.CheckButton] = {}
        self._row_actions: dict[tuple[str, str], Adw.ActionRow] = {}
        self._search_entries: dict[str, Gtk.SearchEntry] = {}
        self._list_boxes: dict[str, Gtk.ListBox] = {}
        self._queue_rows: dict[str, Gtk.ListBoxRow] = {}
        self._stack_pages: dict[str, Adw.ViewStackPage] = {}

        saved_code = self.settings.get("user_code", "")
        if saved_code:
            self.manager.validate_vip_code(saved_code)

        self.window = Adw.Window()
        self.window.set_title("Download Center")
        self.window.set_default_size(760, 620)
        if parent is not None:
            self.window.set_transient_for(parent)

        self.window.connect("close-request", self._on_close_request)

        self._actions = Gio.SimpleActionGroup()
        self.window.insert_action_group("dc", self._actions)
        manual_action = Gio.SimpleAction.new("manual", None)
        manual_action.connect("activate", lambda *_: self._open_manual())
        self._actions.add_action(manual_action)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self._build_content())
        self.window.set_content(self.toast_overlay)

        self.queue.set_on_changed(self._on_queue_changed)
        self.queue.set_on_batch_complete(self._on_queue_batch_complete)
        self._render_queue()

    def present(self) -> None:
        self.window.present()
        if not self._available:
            self.start_refresh()

    def _on_close_request(self, _window) -> bool:
        self.window.set_visible(False)
        return True

    def _build_content(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        if hasattr(Adw, "InlineViewSwitcher"):
            self.stack = Adw.ViewStack()
            self.stack.set_vexpand(True)
            self.stack.set_hexpand(True)
            if hasattr(self.stack, "set_enable_transitions"):
                self.stack.set_enable_transitions(True)
            self.switcher = Adw.InlineViewSwitcher()
            self.switcher.set_stack(self.stack)
            self.switcher.set_display_mode(Adw.InlineViewSwitcherDisplayMode.LABELS)
            self.switcher.set_homogeneous(True)
        else:
            self.stack = Gtk.Stack()
            self.stack.set_vexpand(True)
            self.stack.set_hexpand(True)
            self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.switcher = Gtk.StackSwitcher()
            self.switcher.set_stack(self.stack)
        header.set_title_widget(self.switcher)

        self.vip_button = Gtk.Button(icon_name="dialog-password-symbolic")
        set_tooltip(self.vip_button, f"{VIP_DOWNLOAD_CODE_HINT} (Unlock VIP models)")
        self.vip_button.connect("clicked", lambda *_: self._open_vip())
        header.pack_start(self.vip_button)

        menu = Gio.Menu()
        menu.append("Manual downloads", "dc.manual")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        set_tooltip(menu_button, "Manual download links")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        toolbar.add_top_bar(header)

        for label, arch in _NETWORKS:
            page = self._build_catalogue_page(arch, label)
            self.stack.add_titled(page, arch, label)
            if isinstance(self.stack, Adw.ViewStack):
                self._stack_pages[arch] = self.stack.get_page(page)

        self.queue_revealer = Gtk.Revealer()
        self.queue_revealer.set_reveal_child(False)
        self.queue_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)

        queue_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        set_inset(queue_panel, top=12, bottom=4, start=12, end=12)

        queue_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.queue_title = Gtk.Label(label="Downloads", xalign=0.0)
        self.queue_title.add_css_class("heading")
        self.queue_title.set_hexpand(True)
        queue_header.append(self.queue_title)
        clear_button = Gtk.Button(label="Clear finished")
        clear_button.add_css_class("flat")
        clear_button.connect("clicked", lambda *_: self._clear_finished_queue())
        queue_header.append(clear_button)
        queue_panel.append(queue_header)

        self.queue_list = Gtk.ListBox()
        self.queue_list.set_selection_mode(Gtk.SelectionMode.NONE)
        queue_scroller = Gtk.ScrolledWindow()
        queue_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        queue_scroller.set_max_content_height(220)
        queue_scroller.set_child(self.queue_list)
        queue_panel.append(queue_scroller)

        self.queue_revealer.set_child(queue_panel)

        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self.refresh_button.add_css_class("flat")
        self.refresh_button.connect("clicked", lambda *_: self.start_refresh())
        set_tooltip(self.refresh_button, "Refresh catalogue")

        self.download_button = Gtk.Button(label="Download")
        self.download_button.add_css_class("suggested-action")
        self.download_button.set_hexpand(True)
        self.download_button.connect("clicked", lambda *_: self._enqueue_selected())

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        action_row.add_css_class("uvr-run-actions")
        action_row.append(self.refresh_button)
        action_row.append(self.download_button)

        self.status_label = Gtk.Label(label="Loading catalogue…", xalign=0.0)
        self.status_label.add_css_class("dim-label")
        self.status_label.set_wrap(True)

        action_dock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        action_dock.add_css_class("uvr-run-controls")
        action_dock.append(self.status_label)
        action_dock.append(action_row)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.set_vexpand(True)
        body.append(self.stack)
        body.append(self.queue_revealer)
        body.append(action_dock)

        clamp = Adw.Clamp(child=body, maximum_size=_CLAMP_MAX_WIDTH)
        clamp.set_vexpand(True)
        clamp.set_hexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.set_vexpand(True)
        content.append(clamp)

        toolbar.set_content(content)
        return toolbar

    def _build_catalogue_page(self, arch: str, network_label: str) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        set_inset(page, top=6, start=12, end=12)

        search = Gtk.SearchEntry()
        search.set_placeholder_text(f"Search {network_label} models")
        search.connect("search-changed", self._on_search_changed, arch)
        search.set_hexpand(True)
        page.append(search)
        self._search_entries[arch] = search

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        list_box.set_filter_func(lambda row, a=arch: self._row_matches_filter(row, a))
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(list_box)
        page.append(scroller)
        self._list_boxes[arch] = list_box

        return page

    def _catalogue_row_action(self, row: Gtk.ListBoxRow) -> Adw.ActionRow | None:
        child = row.get_child()
        return child if isinstance(child, Adw.ActionRow) else None

    def _row_matches_filter(self, row: Gtk.ListBoxRow, arch: str) -> bool:
        search = self._search_entries.get(arch)
        if search is None:
            return True
        query = search.get_text().strip().casefold()
        if not query:
            return True
        action = self._catalogue_row_action(row)
        label = getattr(action, "_uvr_model_name", "") if action is not None else ""
        return query in str(label).casefold()

    def _on_search_changed(self, entry: Gtk.SearchEntry, arch: str) -> None:
        list_box = self._list_boxes.get(arch)
        if list_box is not None:
            list_box.invalidate_filter()
        self._update_download_button()

    def _add_model_row(self, arch: str, name: str) -> None:
        if name in (NO_NEW_MODELS, NO_CONNECTION):
            return
        key = (arch, name)
        if key in self._row_checks:
            return

        check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        check.connect("toggled", lambda *_: self._on_row_check_toggled(key))

        action = Adw.ActionRow()
        set_row_title(action, name)
        action.add_prefix(check)
        action.set_activatable_widget(check)
        action._uvr_model_name = name  # type: ignore[attr-defined]
        action._uvr_check = check  # type: ignore[attr-defined]

        self._row_checks[key] = check
        self._row_actions[key] = action
        self._list_boxes[arch].append(action)

    def _on_row_check_toggled(self, key: tuple[str, str]) -> None:
        self._update_download_button()
        check = self._row_checks.get(key)
        if check is None:
            return
        if check.get_active():
            self._lookup_row_size(key)
            return
        action = self._row_actions.get(key)
        if action is not None:
            set_row_subtitle(action, "")

    def _lookup_row_size(self, key: tuple[str, str]) -> None:
        arch, name = key
        action = self._row_actions.get(key)
        if action is None:
            return
        set_row_subtitle(action, "Looking up size…")
        self._size_lookup_id += 1
        lookup_id = self._size_lookup_id

        def worker() -> None:
            text = self.manager.describe_selection_download_size(name, arch)
            idle_on_main(self._apply_row_size, lookup_id, key, text)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_row_size(self, lookup_id: int, key: tuple[str, str], text: str) -> None:
        if lookup_id != self._size_lookup_id:
            return
        action = self._row_actions.get(key)
        if action is not None:
            set_row_subtitle(action, text or "")

    def _selected_entries(self) -> list[tuple[str, str]]:
        selected: list[tuple[str, str]] = []
        for (arch, name), check in self._row_checks.items():
            if check.get_active():
                selected.append((name, arch))
        return selected

    def _selected_count_by_arch(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for (arch, _name), check in self._row_checks.items():
            if check.get_active():
                counts[arch] = counts.get(arch, 0) + 1
        return counts

    def _update_tab_badges(self) -> None:
        if not self._stack_pages:
            return
        selected = self._selected_count_by_arch()
        for _label, arch in _NETWORKS:
            page = self._stack_pages.get(arch)
            if page is not None:
                count = selected.get(arch, 0)
                page.set_badge_number(count)
                # Accent badge styling requires needs-attention (see indicatorbin CSS).
                page.set_needs_attention(count > 0)

    def _update_download_button(self) -> None:
        count = len(self._selected_entries())
        if count:
            self.download_button.set_label(f"Download ({count})")
            self.download_button.set_sensitive(not self._refreshing)
        else:
            self.download_button.set_label("Download")
            self.download_button.set_sensitive(False)
        if self._available:
            total = sum(
                1
                for arch, models in self._available.items()
                for name in models
                if name not in (NO_NEW_MODELS, NO_CONNECTION)
            )
            if count:
                self.status_label.set_label(
                    f"{count} selected · {total} available across all networks"
                )
            elif not self._refreshing:
                self.status_label.set_label(
                    f"{total} models available — check one or more, then Download"
                )
        self._update_tab_badges()

    def start_refresh(self) -> None:
        if self._refreshing:
            return
        debug("download", "ui refresh start")
        self._refreshing = True
        self.status_label.set_label("Refreshing catalogue…")
        self.refresh_button.set_sensitive(False)
        self._update_download_button()
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        is_online = self.manager.refresh()
        if is_online and self.settings.get("is_auto_update_model_params", True):
            self.manager.update_model_settings(self.context.repo)
        available = self.manager.available_downloads() if is_online else {}
        idle_on_main(self._refresh_done, is_online, available)

    def _refresh_done(self, is_online: bool, available: dict) -> None:
        self._refreshing = False
        self.refresh_button.set_sensitive(True)
        if not is_online:
            self.status_label.set_label(NO_CONNECTION)
            self._clear_catalogue()
            return

        self._available = available
        self._rebuild_catalogue()
        counts = {arch: len(models) for arch, models in available.items()}
        debug("download", f"ui refresh done available={counts}")
        total = sum(
            1
            for arch, models in available.items()
            for name in models
            if name not in (NO_NEW_MODELS, NO_CONNECTION)
        )
        self._update_tab_counts()
        selected = len(self._selected_entries())
        if selected:
            self.status_label.set_label(
                f"{selected} selected · {total} available across all networks"
            )
        else:
            self.status_label.set_label(
                f"{total} models available — check one or more, then Download"
            )
        self._update_download_button()

    def _update_tab_counts(self) -> None:
        for network_label, arch in _NETWORKS:
            models = self._available.get(arch) or []
            count = sum(1 for name in models if name not in (NO_NEW_MODELS, NO_CONNECTION))
            search = self._search_entries.get(arch)
            if search is not None:
                search.set_placeholder_text(
                    f"Search {network_label} models — {count} available"
                )

    def _clear_catalogue(self) -> None:
        self._row_checks.clear()
        self._row_actions.clear()
        for list_box in self._list_boxes.values():
            while (child := list_box.get_first_child()) is not None:
                list_box.remove(child)

    def _rebuild_catalogue(self) -> None:
        self._clear_catalogue()
        for _label, arch in _NETWORKS:
            models = self._available.get(arch) or [NO_NEW_MODELS]
            for name in models:
                self._add_model_row(arch, name)
            list_box = self._list_boxes[arch]
            list_box.invalidate_filter()

    def _enqueue_selected(self) -> None:
        entries = self._selected_entries()
        if not entries:
            return
        ids = self.queue.enqueue_many(entries)
        if not ids:
            self._toast("Nothing to download for the current selection")
            return
        for arch, name in [(a, n) for n, a in entries]:
            check = self._row_checks.get((arch, name))
            if check is not None:
                check.set_active(False)
        self._update_download_button()
        self._toast(f"Queued {len(ids)} download(s)")

    def _on_queue_changed(self) -> None:
        idle_on_main(self._render_queue)

    def _render_queue(self) -> None:
        while (child := self.queue_list.get_first_child()) is not None:
            self.queue_list.remove(child)
        self._queue_rows.clear()

        items = self.queue.items()
        active = [item for item in items if item.status in ("queued", "downloading")]
        self.queue_revealer.set_reveal_child(bool(items))

        if not items:
            return

        self.queue_title.set_label(
            f"Downloads ({len(active)} active)" if active else f"Downloads ({len(items)} recent)"
        )

        for item in items:
            list_row = self._make_queue_row(item)
            self._update_queue_row(list_row, item)
            self.queue_list.append(list_row)
            self._queue_rows[item.item_id] = list_row

    def _make_queue_row(self, item: DownloadQueueItem) -> Gtk.ListBoxRow:
        title = Gtk.Label(xalign=0.0, wrap=True, natural_wrap_mode=Gtk.NaturalWrapMode.WORD)
        title.set_label(item.label)

        detail = Gtk.Label(xalign=0.0, wrap=True, natural_wrap_mode=Gtk.NaturalWrapMode.WORD)
        detail.add_css_class("dim-label")

        progress = Gtk.ProgressBar()
        progress.set_show_text(False)

        stop_button = Gtk.Button(icon_name="process-stop-symbolic")
        stop_button.set_valign(Gtk.Align.START)
        stop_button.connect("clicked", lambda *_: self.queue.cancel(item.item_id))

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_row.append(title)
        title_row.append(stop_button)
        title.set_hexpand(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        set_inset(content, top=10, bottom=10, start=4, end=4)
        content.append(title_row)
        content.append(detail)
        content.append(progress)

        list_row = Gtk.ListBoxRow()
        list_row.set_child(content)
        list_row._uvr_title = title  # type: ignore[attr-defined]
        list_row._uvr_detail = detail  # type: ignore[attr-defined]
        list_row._uvr_progress = progress  # type: ignore[attr-defined]
        list_row._uvr_item_id = item.item_id  # type: ignore[attr-defined]
        return list_row

    def _update_queue_row(self, list_row: Gtk.ListBoxRow, item: DownloadQueueItem) -> None:
        title: Gtk.Label = list_row._uvr_title  # type: ignore[attr-defined]
        detail: Gtk.Label = list_row._uvr_detail  # type: ignore[attr-defined]
        progress: Gtk.ProgressBar = list_row._uvr_progress  # type: ignore[attr-defined]
        title.set_label(item.label)
        subtitle = item.detail or item.status.replace("_", " ").title()
        detail.set_label(subtitle)
        detail.set_visible(bool(subtitle))
        if item.status in ("queued", "downloading"):
            progress.set_fraction(item.progress if item.status == "downloading" else 0.0)
            progress.set_visible(True)
        elif item.status == "complete":
            progress.set_fraction(1.0)
            progress.set_visible(True)
        else:
            progress.set_visible(False)

    def _clear_finished_queue(self) -> None:
        self.queue.clear_finished()
        self._render_queue()

    def _on_queue_batch_complete(self) -> None:
        idle_on_main(self._after_downloads)

    def _after_downloads(self) -> None:
        self._available = self.manager.available_downloads()
        self._rebuild_catalogue()
        if self._on_models_changed is not None:
            self._on_models_changed()
        self._toast("Downloads finished")

    def _open_vip(self) -> None:
        from .download import open_vip_code_dialog

        open_vip_code_dialog(self.window, self.context, on_validated=self._on_vip_validated)

    def _open_manual(self) -> None:
        from .download import open_manual_downloads

        open_manual_downloads(self.window, self.context)

    def _on_vip_validated(self, unlocked: bool) -> None:
        if unlocked:
            self.start_refresh()
            self._toast("VIP models unlocked")

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))
