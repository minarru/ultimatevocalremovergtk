"""Download Center window — catalogue browser and download queue."""

from __future__ import annotations
import typing

import os
import threading

from gi.repository import Adw, Gio, Gtk

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    NO_CONNECTION,
    NO_NEW_MODELS,
    VR_ARCH_TYPE,
)
from core.debug_log import debug
from core.download_queue import DownloadQueue
from core.downloads import DownloadManager
from core.model_scores import (
    PURPOSE_ALL,
    PURPOSE_FILTER_OPTIONS,
    SORT_NAME,
    SORT_OPTIONS,
    SORT_SDR,
    filter_labels_by_purpose,
    format_sdr_subtitle,
    parse_sdr_score,
    purpose_for_label,
    sort_labels_by_sdr,
)
from core import paths

from .dialogs.utils import close_on_escape
from .dispatch import idle_on_main
from .help_text import VIP_DOWNLOAD_CODE_HINT
from .hints import set_icon_button_a11y
from core.model_naming import canonical_display_name
from core.model_scores import primary_sdr, sdr_for_files

from .markup import set_row_subtitle, set_row_title
from .spacing import set_inset
from .widgets.rows import get_combo_value, make_combo_row, set_combo_value
from .widget_state import fetch, stash

_NETWORKS = [
    ("VR Arch", VR_ARCH_TYPE),
    ("MDX-Net", MDX_ARCH_TYPE),
    ("Demucs", DEMUCS_ARCH_TYPE),
    # Apollo models are restoration (Audio Tools), not separation networks, but
    # they share the catalogue/queue plumbing so they get their own tab.
    ("Apollo", APOLLO_ARCH_TYPE),
]

_CLAMP_MAX_WIDTH = 800


def catalogue_matches(
    names: list[str],
    query: str,
    *,
    purpose: str = PURPOSE_ALL,
) -> list[str]:
    """Return selectable catalogue names matching query and purpose filter.

    Matching covers both the raw catalogue label and its canonical rendering,
    so a user typing what the row *shows* finds it.
    """
    selectable = [
        name for name in names if name not in (NO_NEW_MODELS, NO_CONNECTION)
    ]
    selectable = filter_labels_by_purpose(selectable, purpose)
    folded = query.strip().casefold()
    if not folded:
        return selectable
    return [
        name
        for name in selectable
        if folded in name.casefold()
        or folded in canonical_display_name(name).casefold()
    ]


def resolve_catalogue_action_row(row: Gtk.ListBoxRow) -> Adw.ActionRow | None:
    """Return the catalogue ``ActionRow`` for a ListBox filter callback.

    ``Adw.ActionRow`` subclasses ``Gtk.ListBoxRow``, so filters receive the
    action row itself. ``get_child()`` is only its internal layout box.
    """
    if isinstance(row, Adw.ActionRow):
        return row
    child = row.get_child()
    return child if isinstance(child, Adw.ActionRow) else None


class DownloadCenterWindow:
    """Non-modal utility window for browsing and queueing model downloads."""

    def __init__(
        self,
        parent: typing.Any,
        app_context: typing.Any,
        manager: DownloadManager,
        queue: DownloadQueue,
        on_models_changed: typing.Any=None,
    ):
        self.parent = parent
        self.context = app_context
        self.settings = app_context.settings
        self.manager = manager
        self.queue = queue
        self._on_models_changed = on_models_changed

        self._available: dict[str, list[str]] = {}
        self._unsupported: dict[str, list[tuple[str, str]]] = {}
        self._catalogue_online: bool | None = None
        self._refreshing = False
        self._size_lookup_ids: dict[tuple[str, str], int] = {}
        self._row_checks: dict[tuple[str, str], Gtk.CheckButton] = {}
        self._row_actions: dict[tuple[str, str], Adw.ActionRow] = {}
        self._search_entries: dict[str, Gtk.SearchEntry] = {}
        self._list_boxes: dict[str, Gtk.ListBox] = {}
        self._empty_pages: dict[str, Adw.StatusPage] = {}
        self._stack_pages: dict[str, Adw.ViewStackPage] = {}
        self._purpose = PURPOSE_ALL
        self._sort_mode = SORT_NAME
        self._hide_unsupported = False
        self._stem_refresh_armed = False

        saved_code = self.settings.process.user_code
        if saved_code:
            self.manager.validate_vip_code(saved_code)

        self.window = Adw.Window()
        self.window.set_title("Download Center")
        self.window.set_default_size(760, 620)
        if parent is not None:
            self.window.set_transient_for(parent)
        close_on_escape(self.window)

        self.window.connect("close-request", self._on_close_request)

        self._actions = Gio.SimpleActionGroup()
        self.window.insert_action_group("dc", self._actions)
        models_action = Gio.SimpleAction.new("open-models", None)
        models_action.connect("activate", lambda *_: self._open_models_folder())
        self._actions.add_action(models_action)
        manual_action = Gio.SimpleAction.new("manual", None)
        manual_action.connect("activate", lambda *_: self._open_manual())
        self._actions.add_action(manual_action)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self._build_content())
        self.window.set_content(self.toast_overlay)

    def present(self) -> None:
        self.window.present()
        if not self._available:
            self.start_refresh()

    def _on_close_request(self, _window: typing.Any) -> bool:
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
        set_icon_button_a11y(
            self.vip_button, f"{VIP_DOWNLOAD_CODE_HINT} (Unlock VIP models)"
        )
        self.vip_button.connect("clicked", lambda *_: self._open_vip())
        header.pack_start(self.vip_button)

        menu = Gio.Menu()
        menu.append("Open models folder", "dc.open-models")
        menu.append("Manual downloads", "dc.manual")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        set_icon_button_a11y(menu_button, "Models folder and manual download links")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        toolbar.add_top_bar(header)

        for label, arch in _NETWORKS:
            page = self._build_catalogue_page(arch, label)
            self.stack.add_titled(page, arch, label)
            if isinstance(self.stack, Adw.ViewStack):
                self._stack_pages[arch] = self.stack.get_page(page)
        self.stack.connect("notify::visible-child-name", self._on_catalogue_tab_changed)

        filter_group = Adw.PreferencesGroup()
        set_inset(filter_group, start=12, end=12, top=6)
        purpose_labels = [label for _value, label in PURPOSE_FILTER_OPTIONS]
        self.purpose_row = make_combo_row("Purpose", purpose_labels)
        self.purpose_row.connect("notify::selected", self._on_purpose_changed)
        set_combo_value(self.purpose_row, PURPOSE_FILTER_OPTIONS[0][1])
        filter_group.add(self.purpose_row)
        sort_labels = [label for _value, label in SORT_OPTIONS]
        self.sort_row = make_combo_row("Sort", sort_labels)
        self.sort_row.connect("notify::selected", self._on_sort_changed)
        set_combo_value(self.sort_row, SORT_OPTIONS[0][1])
        filter_group.add(self.sort_row)

        self.hide_unsupported_row = Adw.SwitchRow(
            title="Hide unsupported",
            subtitle="Hide catalogue models this build cannot run yet",
        )
        self.hide_unsupported_row.set_active(False)
        self.hide_unsupported_row.connect(
            "notify::active", self._on_hide_unsupported_changed
        )
        filter_group.add(self.hide_unsupported_row)

        self.refresh_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self.refresh_button.add_css_class("flat")
        self.refresh_button.connect("clicked", lambda *_: self.start_refresh())
        set_icon_button_a11y(self.refresh_button, "Refresh catalogue")

        self.download_button = Gtk.Button(label="_Download", use_underline=True)
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
        self._refresh_spinner = Gtk.Spinner()
        self._refresh_spinner.set_visible(False)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_row.append(self._refresh_spinner)
        status_row.append(self.status_label)

        action_dock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        action_dock.add_css_class("uvr-run-controls")
        action_dock.append(status_row)
        action_dock.append(action_row)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.set_vexpand(True)
        body.append(filter_group)
        body.append(self.stack)
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

        empty_page = Adw.StatusPage(
            icon_name="network-offline-symbolic",
            title="Catalogue unavailable",
            description="Check your connection and try again.",
        )
        empty_page.set_vexpand(True)
        empty_page.set_visible(False)
        retry = Gtk.Button(label="Try Again")
        retry.add_css_class("suggested-action")
        retry.set_halign(Gtk.Align.CENTER)
        retry.connect("clicked", lambda *_: self.start_refresh())
        empty_page.set_child(retry)
        page.append(empty_page)
        self._empty_pages[arch] = empty_page

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        list_box.set_filter_func(lambda row, a=arch: self._row_matches_filter(row, a))
        list_box.set_sort_func(lambda r1, r2: self._compare_rows(r1, r2))
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(list_box)
        page.append(scroller)
        self._list_boxes[arch] = list_box

        return page

    def _catalogue_row_action(self, row: Gtk.ListBoxRow) -> Adw.ActionRow | None:
        return resolve_catalogue_action_row(row)

    def _row_matches_filter(self, row: Gtk.ListBoxRow, arch: str) -> bool:
        action = self._catalogue_row_action(row)
        label = fetch(action, "_uvr_model_name", "") if action is not None else ""
        if not label:
            return False
        if self._hide_unsupported and fetch(action, "_uvr_unsupported", False):
            return False
        if self._purpose != PURPOSE_ALL and purpose_for_label(label) != self._purpose:
            return False
        search = self._search_entries.get(arch)
        if search is None:
            return True
        query = search.get_text().strip().casefold()
        if not query:
            return True
        return query in str(label).casefold()

    def _row_sort_key(self, row: typing.Any) -> tuple[int, int, float, str]:
        """Order key: supported first, then the active sort mode, then name."""
        unsupported = 1 if fetch(row, "_uvr_unsupported", False) else 0
        name = fetch(row, "_uvr_sort_name", "")
        if self._sort_mode == SORT_SDR and not unsupported:
            sdr = fetch(row, "_uvr_sdr", None)
            if sdr is None:
                # Unscored models sink below scored ones, as in the old sort.
                return (unsupported, 1, 0.0, name)
            return (unsupported, 0, -float(sdr), name)
        return (unsupported, 0, 0.0, name)

    def _compare_rows(self, row1: typing.Any, row2: typing.Any) -> int:
        left = self._row_sort_key(row1)
        right = self._row_sort_key(row2)
        if left < right:
            return -1
        return 1 if left > right else 0

    def _invalidate_all_sorts(self) -> None:
        for arch, list_box in self._list_boxes.items():
            list_box.invalidate_sort()
            self._update_catalogue_page_state(arch)

    def _on_hide_unsupported_changed(self, *_args: typing.Any) -> None:
        self._hide_unsupported = bool(self.hide_unsupported_row.get_active())
        self._invalidate_all_filters()
        self._update_tab_counts()
        self._update_status_from_catalogue()

    def _on_search_changed(self, entry: Gtk.SearchEntry, arch: str) -> None:
        list_box = self._list_boxes.get(arch)
        if list_box is not None:
            list_box.invalidate_filter()
        self._update_catalogue_page_state(arch)
        self._update_download_button()

    def _on_purpose_changed(self, *_args: typing.Any) -> None:
        label = get_combo_value(self.purpose_row) or PURPOSE_FILTER_OPTIONS[0][1]
        self._purpose = next(
            (value for value, text in PURPOSE_FILTER_OPTIONS if text == label),
            PURPOSE_ALL,
        )
        self._invalidate_all_filters()

    def _on_sort_changed(self, *_args: typing.Any) -> None:
        label = get_combo_value(self.sort_row) or SORT_OPTIONS[0][1]
        self._sort_mode = next(
            (value for value, text in SORT_OPTIONS if text == label),
            SORT_NAME,
        )
        # Re-sorting in place keeps every checked row, the way Purpose
        # filtering always has. Rebuilding dropped the selection.
        self._invalidate_all_sorts()

    def _invalidate_all_filters(self) -> None:
        for arch, list_box in self._list_boxes.items():
            list_box.invalidate_filter()
            self._update_catalogue_page_state(arch)
        self._update_download_button()

    def _on_catalogue_tab_changed(self, *_args: typing.Any) -> None:
        self._update_download_button()

    def _row_score(self, name: str) -> tuple[str | None, float | None, str]:
        """Return ``(stem, sdr, stems_text)`` for a catalogue label.

        Falls back to the filename regex when the benchmark table has no entry,
        which covers the handful of models whose SDR lives only in their name.
        """
        meta = self.manager.catalogue_meta.get(name)
        stems_text = ", ".join(meta.stems) if meta is not None and meta.stems else ""
        if meta is not None:
            # stem_count disambiguates a 2-stem 'other' (meaning instrumental)
            # from a 4-stem model's real 'other' residual.
            scored = primary_sdr(
                sdr_for_files(meta.files),
                meta.target_instrument,
                stem_count=len(meta.stems) or 2,
            )
            if scored is not None:
                return (scored[0], scored[1], stems_text)
        return (None, parse_sdr_score(name), stems_text)

    def _add_model_row(self, arch: str, name: str) -> None:
        if name in (NO_NEW_MODELS, NO_CONNECTION):
            return
        key = (arch, name)
        if key in self._row_checks or key in self._row_actions:
            return

        check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        check.connect("toggled", lambda *_: self._on_row_check_toggled(key))

        stem, sdr, stems_text = self._row_score(name)

        action = Adw.ActionRow()
        set_row_title(action, canonical_display_name(name))
        action.add_prefix(check)
        action.set_activatable_widget(check)
        # Identity stays the raw catalogue label: resolve()/download() key on it.
        stash(action, "_uvr_model_name", name)
        stash(action, "_uvr_check", check)
        stash(action, "_uvr_unsupported", False)
        stash(action, "_uvr_sdr", sdr)
        stash(action, "_uvr_sdr_stem", stem)
        stash(action, "_uvr_stems_text", stems_text)
        stash(action, "_uvr_sort_name", canonical_display_name(name).casefold())
        set_row_subtitle(action, format_sdr_subtitle(sdr, stem=stem, extra=stems_text))

        self._row_checks[key] = check
        self._row_actions[key] = action
        self._list_boxes[arch].append(action)

    def _add_unsupported_row(self, arch: str, name: str, reason: str) -> None:
        key = (arch, name)
        if key in self._row_actions:
            return

        action = Adw.ActionRow()
        set_row_title(action, canonical_display_name(name))
        set_row_subtitle(action, f"Unsupported — {reason}")
        action.add_css_class("dim-label")
        action.set_sensitive(False)
        stash(action, "_uvr_model_name", name)
        stash(action, "_uvr_unsupported", True)
        stash(action, "_uvr_sdr", parse_sdr_score(name))
        stash(action, "_uvr_sdr_stem", None)
        stash(action, "_uvr_stems_text", "")
        stash(action, "_uvr_sort_name", canonical_display_name(name).casefold())

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
            set_row_subtitle(
                action,
                format_sdr_subtitle(
                    fetch(action, "_uvr_sdr", None),
                    "",
                    stem=fetch(action, "_uvr_sdr_stem", None),
                    extra=fetch(action, "_uvr_stems_text", ""),
                ),
            )

    def _lookup_row_size(self, key: tuple[str, str]) -> None:
        arch, name = key
        action = self._row_actions.get(key)
        if action is None:
            return
        set_row_subtitle(action, "Looking up size…")
        lookup_id = self._size_lookup_ids.get(key, 0) + 1
        self._size_lookup_ids[key] = lookup_id

        def worker() -> None:
            text = self.manager.describe_selection_download_size(name, arch)
            idle_on_main(self._apply_row_size, lookup_id, key, text)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_row_size(self, lookup_id: int, key: tuple[str, str], text: str) -> None:
        # Guard is keyed per-row: checking another model must not discard this
        # row's own in-flight lookup result.
        if self._size_lookup_ids.get(key) != lookup_id:
            return
        action = self._row_actions.get(key)
        if action is not None:
            set_row_subtitle(
                action,
                format_sdr_subtitle(
                    fetch(action, "_uvr_sdr", None),
                    text or "",
                    stem=fetch(action, "_uvr_sdr_stem", None),
                    extra=fetch(action, "_uvr_stems_text", ""),
                ),
            )

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
                for _arch, models in self._available.items()
                for name in models
                if name not in (NO_NEW_MODELS, NO_CONNECTION)
            )
            active_arch = self.stack.get_visible_child_name()
            active_search = self._search_entries.get(active_arch or "")
            query = active_search.get_text().strip() if active_search is not None else ""
            if query and active_arch:
                network_label = next(
                    (label for label, arch in _NETWORKS if arch == active_arch),
                    "current network",
                )
                shown = len(
                    catalogue_matches(self._available.get(active_arch) or [], query)
                )
                self.status_label.set_label(
                    f"{shown} match{'es' if shown != 1 else ''} for “{query}” "
                    f"in {network_label}"
                )
            elif count:
                self.status_label.set_label(
                    f"{count} selected · {total} available across all networks"
                )
            elif not self._refreshing:
                if total:
                    self.status_label.set_label(
                        f"{total} models available — check one or more, then Download"
                    )
                else:
                    self.status_label.set_label(
                        "All available models are already installed"
                    )
        self._update_tab_badges()

    def start_refresh(self) -> None:
        if self._refreshing:
            return
        debug("download", "ui refresh start")
        self._refreshing = True
        self.status_label.set_label("Refreshing catalogue…")
        self._refresh_spinner.set_visible(True)
        self._refresh_spinner.start()
        self.refresh_button.set_sensitive(False)
        self._update_download_button()
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        is_online = self.manager.refresh()
        if is_online and self.settings.process.auto_update_model_params:
            self.manager.update_model_settings(self.context.repo)
        available = self.manager.available_downloads() if is_online else {}
        unsupported = self.manager.unsupported_downloads() if is_online else {}
        idle_on_main(self._refresh_done, is_online, available, unsupported)

    def _refresh_done(
        self,
        is_online: bool,
        available: dict,
        unsupported: dict | None = None,
    ) -> None:
        self._refreshing = False
        self._catalogue_online = is_online
        self.refresh_button.set_sensitive(True)
        self._refresh_spinner.stop()
        self._refresh_spinner.set_visible(False)
        if not is_online:
            self._available = {}
            self._unsupported = {}
            self.status_label.set_label(NO_CONNECTION)
            self._clear_catalogue()
            for _label, arch in _NETWORKS:
                self._set_catalogue_page_message(
                    arch,
                    "Catalogue unavailable",
                    description="Check your connection and try again.",
                    offline=True,
                )
            return

        self._available = available
        self._unsupported = unsupported or {}
        self._rebuild_catalogue()
        counts = {arch: len(models) for arch, models in available.items()}
        debug(
            "download",
            f"ui refresh done available={counts} "
            f"unsupported={ {a: len(r) for a, r in self._unsupported.items()} }",
        )
        self._update_tab_counts()
        self._update_status_from_catalogue()
        self._update_download_button()
        self._ensure_stem_cache_listener()

    def _ensure_stem_cache_listener(self) -> None:
        from core.catalogue_stem_cache import ensure_worker_started, subscribe

        subscribe(self._schedule_stem_subtitle_refresh)
        ensure_worker_started()

    def _schedule_stem_subtitle_refresh(self) -> None:
        idle_on_main(self._arm_stem_subtitle_refresh)

    def _arm_stem_subtitle_refresh(self) -> None:
        if self._stem_refresh_armed:
            return
        self._stem_refresh_armed = True
        from gi.repository import GLib

        GLib.timeout_add(200, self._flush_stem_subtitles)

    def _flush_stem_subtitles(self) -> bool:
        self._stem_refresh_armed = False
        updated = self.manager.apply_catalogue_stem_cache()
        if not updated:
            return False
        for key, action in self._row_actions.items():
            _arch, name = key
            if name not in updated:
                continue
            if fetch(action, "_uvr_unsupported", False):
                continue
            meta = self.manager.catalogue_meta.get(name)
            stems_text = ", ".join(meta.stems) if meta is not None and meta.stems else ""
            stash(action, "_uvr_stems_text", stems_text)
            set_row_subtitle(
                action,
                format_sdr_subtitle(
                    fetch(action, "_uvr_sdr", None),
                    "",
                    stem=fetch(action, "_uvr_sdr_stem", None),
                    extra=stems_text,
                ),
            )
        return False

    def _available_count(self) -> int:
        return sum(
            1
            for models in self._available.values()
            for name in models
            if name not in (NO_NEW_MODELS, NO_CONNECTION)
        )

    def _unsupported_count(self, *, visible_only: bool = False) -> int:
        if visible_only and self._hide_unsupported:
            return 0
        return sum(len(rows) for rows in self._unsupported.values())

    def _update_status_from_catalogue(self) -> None:
        total = self._available_count()
        unsupported = self._unsupported_count(visible_only=True)
        selected = len(self._selected_entries())
        if selected:
            self.status_label.set_label(
                f"{selected} selected · {total} available across all networks"
            )
            return
        if total and unsupported:
            self.status_label.set_label(
                f"{total} downloadable · {unsupported} unsupported shown"
            )
        elif total:
            self.status_label.set_label(
                f"{total} models available — check one or more, then Download"
            )
        elif unsupported:
            self.status_label.set_label(
                f"{unsupported} unsupported models listed (not downloadable)"
            )
        else:
            self.status_label.set_label("All available models are already installed")

    def _update_tab_counts(self) -> None:
        for network_label, arch in _NETWORKS:
            models = self._available.get(arch) or []
            count = sum(1 for name in models if name not in (NO_NEW_MODELS, NO_CONNECTION))
            unsupported = 0 if self._hide_unsupported else len(self._unsupported.get(arch) or [])
            search = self._search_entries.get(arch)
            if search is not None:
                if unsupported:
                    search.set_placeholder_text(
                        f"Search {network_label} — {count} available, {unsupported} unsupported"
                    )
                else:
                    search.set_placeholder_text(
                        f"Search {network_label} models — {count} available"
                    )

    def _clear_catalogue(self) -> None:
        self._row_checks.clear()
        self._row_actions.clear()
        self._size_lookup_ids.clear()
        for list_box in self._list_boxes.values():
            while (child := list_box.get_first_child()) is not None:
                list_box.remove(child)

    def _set_catalogue_page_message(
        self,
        arch: str,
        title: str,
        *,
        description: str = "",
        offline: bool = False,
    ) -> None:
        page = self._empty_pages.get(arch)
        list_box = self._list_boxes.get(arch)
        if page is None:
            return
        list_parent = list_box.get_parent() if list_box is not None else None
        if not title:
            page.set_visible(False)
            if list_parent is not None:
                list_parent.set_visible(True)
            return
        page.set_title(title)
        page.set_description(description or None)
        page.set_icon_name(
            "network-offline-symbolic" if offline else "edit-find-symbolic"
        )
        child = page.get_child()
        if child is not None:
            child.set_visible(offline)
        page.set_visible(True)
        if list_parent is not None:
            list_parent.set_visible(False)

    def _update_catalogue_page_state(self, arch: str) -> None:
        if self._catalogue_online is False:
            self._set_catalogue_page_message(
                arch,
                "Catalogue unavailable",
                description="Check your connection and try again.",
                offline=True,
            )
            return
        if self._catalogue_online is None:
            self._set_catalogue_page_message(
                arch,
                "Catalogue is still loading…",
                description="Please wait.",
            )
            return
        names = self._available.get(arch) or []
        search = self._search_entries.get(arch)
        query = search.get_text().strip() if search is not None else ""
        matches = catalogue_matches(names, query, purpose=self._purpose)
        unsupported_matches = self._unsupported_matches(arch, query)
        if (query or self._purpose != PURPOSE_ALL) and not matches and not unsupported_matches:
            if query:
                self._set_catalogue_page_message(
                    arch,
                    "No matching models",
                    description=f'Try a broader search than “{query}”.',
                )
            else:
                self._set_catalogue_page_message(
                    arch,
                    "No matching models",
                    description="No models match this purpose filter.",
                )
        elif (
            not catalogue_matches(names, "", purpose=PURPOSE_ALL)
            and not (self._unsupported.get(arch) or [])
        ):
            self._set_catalogue_page_message(
                arch,
                "All installed",
                description="All models for this network are already installed.",
            )
        else:
            self._set_catalogue_page_message(arch, "")

    def _unsupported_matches(self, arch: str, query: str) -> list[tuple[str, str]]:
        if self._hide_unsupported:
            return []
        rows = list(self._unsupported.get(arch) or [])
        if self._purpose != PURPOSE_ALL:
            rows = [
                (label, reason)
                for label, reason in rows
                if purpose_for_label(label) == self._purpose
            ]
        folded = query.strip().casefold()
        if not folded:
            return rows
        return [
            (label, reason)
            for label, reason in rows
            if folded in label.casefold() or folded in reason.casefold()
        ]

    def _rebuild_catalogue(self) -> None:
        previously_selected = {(arch, name) for name, arch in self._selected_entries()}
        self._clear_catalogue()
        for _label, arch in _NETWORKS:
            models = [
                name
                for name in (self._available.get(arch) or [])
                if name not in (NO_NEW_MODELS, NO_CONNECTION)
            ]
            for name in models:
                self._add_model_row(arch, name)
            unsupported = sorted(
                self._unsupported.get(arch) or [],
                key=lambda pair: pair[0].casefold(),
            )
            for name, reason in unsupported:
                self._add_unsupported_row(arch, name, reason)
            if not models and not unsupported:
                # Keep a placeholder-free empty page via status message.
                pass
            list_box = self._list_boxes[arch]
            list_box.invalidate_filter()
            self._update_catalogue_page_state(arch)
        # Rebuilding (e.g. changing Sort) recreates every row/checkbox from
        # scratch — reapply any selection that still exists so it isn't
        # silently dropped, matching how purpose-filtering never loses it.
        for key in previously_selected:
            check = self._row_checks.get(key)
            if check is not None:
                check.set_active(True)

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

    def refresh_after_downloads(self) -> None:
        """Rebuild catalogue after a download batch completes."""
        self._catalogue_online = True
        self._available = self.manager.available_downloads()
        self._unsupported = self.manager.unsupported_downloads()
        self._rebuild_catalogue()
        self._update_tab_counts()
        self._update_status_from_catalogue()
        self._update_download_button()
        self._ensure_stem_cache_listener()

    def _open_vip(self) -> None:
        from .download import open_vip_code_dialog

        open_vip_code_dialog(self.window, self.context, on_validated=self._on_vip_validated)

    def _open_manual(self) -> None:
        from .download import open_manual_downloads

        open_manual_downloads(self.window, self.context)

    def _open_models_folder(self) -> None:
        """Open the model folder for the visible network, or the parent folder."""
        from .files import open_folder_in_file_manager

        arch = self.stack.get_visible_child_name()
        target = self.manager.model_directory(arch) if arch else paths.MODELS_DIR
        if not target:
            target = paths.MODELS_DIR
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as exc:
            self._toast(f"Couldn't open models folder: {exc}")
            return
        open_folder_in_file_manager(self.window, target, on_error=self._toast)

    def _on_vip_validated(self, unlocked: bool) -> None:
        if unlocked:
            self.start_refresh()
            self._toast("VIP models unlocked")

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))
