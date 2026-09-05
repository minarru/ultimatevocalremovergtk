"""Download Center window — catalogue browser and download queue."""

from __future__ import annotations

import os
import threading
import typing
from dataclasses import replace

from gi.repository import Adw, Gio, Gtk

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    NO_CONNECTION,
    NO_NEW_MODELS,
    VR_ARCH_TYPE,
)
from core import paths
from core.debug_log import debug
from core.download_queue import DownloadQueue
from core.downloads import DownloadManager
from core.model_identity import FAMILY_BY_ARCH
from core.model_scores import (
    ARCH_FILTER_ALL,
    MDX_NETWORK_SUBTYPES,
    NETWORK_FILTER_OPTIONS,
    PURPOSE_ALL,
    PURPOSE_FILTER_OPTIONS,
    PURPOSE_PAGE_OPTIONS,
    PURPOSE_VOCALS,
    SORT_NAME,
    SORT_OPTIONS,
    catalogue_network_id,
    family_arch_for_network_filter,
    format_sdr_subtitle,
    network_filter_hides_headers,
    network_filter_matches,
    parse_sdr_score,
    primary_sdr,
    purpose_roles_from_meta,
    sdr_for_files,
)

from .catalogue_browser import (
    BrowserFilters,
    CatalogueBrowserState,
    catalogue_evidence_detail,
    catalogue_matches,
    catalogue_semantics_subtitle,
    project_browser,
    project_row,
)
from .dialogs.utils import close_on_escape
from .dispatch import idle_on_main
from .hints import set_icon_button_a11y, set_tooltip
from .lifetime import UiLifetime
from .markup import set_row_subtitle, set_row_title
from .spacing import set_inset
from .widget_state import drop, fetch, stash
from .widgets.rows import get_combo_value, make_combo_row, set_combo_value

_NETWORKS = [
    ("VR Arch", VR_ARCH_TYPE),
    ("MDX-Net", MDX_ARCH_TYPE),
    ("Demucs", DEMUCS_ARCH_TYPE),
    # Apollo models are restoration (Audio Tools), not separation networks, but
    # they share the catalogue/queue plumbing so they stay in the network filter.
    ("Apollo", APOLLO_ARCH_TYPE),
]

_ARCH_FILTER_OPTIONS = NETWORK_FILTER_OPTIONS

_ARCH_ORDER = {
    value: index
    for index, (value, _label) in enumerate(NETWORK_FILTER_OPTIONS)
    if value != ARCH_FILTER_ALL
}


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
    ):
        self.parent = parent
        self.context = app_context
        self.settings = app_context.settings
        self.manager = manager
        self.queue = queue

        self.browser = CatalogueBrowserState()
        self._lifetime = UiLifetime()
        self._listening = False
        self._catalogue_online: bool | None = None
        self._catalogue_notice = ""
        self._refreshing = False
        self._size_lookup_ids: dict[tuple[str, str], int] = {}
        self._row_checks: dict[tuple[str, str], Gtk.CheckButton] = {}
        self._row_actions: dict[tuple[str, str], Adw.ActionRow] = {}
        self._search_entries: dict[str, Gtk.SearchEntry] = {}
        self._list_boxes: dict[str, Gtk.ListBox] = {}
        self._empty_pages: dict[str, Adw.StatusPage] = {}
        self._stack_pages: dict[str, Adw.ViewStackPage] = {}
        self._purpose = PURPOSE_VOCALS
        self._arch_filter = ARCH_FILTER_ALL
        self._sort_mode = SORT_NAME
        self._hide_unsupported = False
        self._stem_refresh_armed = False
        self._stem_fetch_armed = False
        self._catalogue_refresh_armed = False
        self._downloads_dirty = False

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

    @property
    def _purpose(self) -> str:
        return self.browser.filters.purpose

    @_purpose.setter
    def _purpose(self, value: str) -> None:
        self.browser.filters = replace(self.browser.filters, purpose=value)

    @property
    def _arch_filter(self) -> str:
        return self.browser.filters.network

    @_arch_filter.setter
    def _arch_filter(self, value: str) -> None:
        self.browser.filters = replace(self.browser.filters, network=value)

    @property
    def _sort_mode(self) -> str:
        return self.browser.filters.sort_mode

    @_sort_mode.setter
    def _sort_mode(self, value: str) -> None:
        self.browser.filters = replace(self.browser.filters, sort_mode=value)

    @property
    def _hide_unsupported(self) -> bool:
        return self.browser.filters.hide_unsupported

    @_hide_unsupported.setter
    def _hide_unsupported(self, value: bool) -> None:
        self.browser.filters = replace(self.browser.filters, hide_unsupported=value)

    def present(self) -> None:
        self.window.present()
        if self.browser.pending_source:
            self.browser.pending_source = False
            self.start_refresh()
            return
        if self._downloads_dirty and self.browser.available:
            self._apply_download_completion_refresh()
        if not self.browser.available:
            self.start_refresh()

    def _on_close_request(self, _window: typing.Any) -> bool:
        self.window.set_visible(False)
        return True

    def dispose(self) -> None:
        """Terminal owner teardown; hiding the cached browser does not call this."""
        self._lifetime.dispose()

    def _build_content(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        if hasattr(Adw, "InlineViewSwitcher"):
            self.stack = Adw.ViewStack()
            if hasattr(self.stack, "set_enable_transitions"):
                self.stack.set_enable_transitions(False)
            self.switcher = Adw.InlineViewSwitcher()
            self.switcher.set_stack(self.stack)
            self.switcher.set_display_mode(Adw.InlineViewSwitcherDisplayMode.LABELS)
            self.switcher.set_homogeneous(False)
        else:
            self.stack = Gtk.Stack()
            self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
            self.switcher = Gtk.StackSwitcher()
            self.switcher.set_stack(self.stack)
        header.set_title_widget(self.switcher)

        menu = Gio.Menu()
        menu.append("Open models folder", "dc.open-models")
        menu.append("Manual downloads", "dc.manual")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        set_icon_button_a11y(menu_button, "Models and manual downloads")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        toolbar.add_top_bar(header)

        for value, label in PURPOSE_PAGE_OPTIONS:
            placeholder = Gtk.Box()
            self.stack.add_titled(placeholder, value, label)
            if isinstance(self.stack, Adw.ViewStack):
                self._stack_pages[value] = self.stack.get_page(placeholder)
        self.stack.set_visible_child_name(PURPOSE_VOCALS)
        self._purpose = PURPOSE_VOCALS

        filter_group = Adw.PreferencesGroup()
        set_inset(filter_group, start=12, end=12, top=6)
        arch_labels = [label for _value, label in _ARCH_FILTER_OPTIONS]
        self.arch_row = make_combo_row("Network", arch_labels)
        self.arch_row.connect("notify::selected", self._on_arch_filter_changed)
        set_combo_value(self.arch_row, _ARCH_FILTER_OPTIONS[0][1])
        filter_group.add(self.arch_row)
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
        self.hide_unsupported_row.connect("notify::active", self._on_hide_unsupported_changed)
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
        self.stack.set_visible(False)
        body.append(self.stack)
        body.append(filter_group)
        body.append(self._build_catalogue_page())
        body.append(action_dock)

        toolbar.set_content(body)
        self.stack.connect("notify::visible-child-name", self._on_catalogue_tab_changed)
        return toolbar

    def _build_catalogue_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        set_inset(page, top=6, start=12, end=12)

        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search models")
        search.connect("search-changed", self._on_search_changed)
        search.set_hexpand(True)
        page.append(search)
        self._search_entry = search
        for _label, arch in _NETWORKS:
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
        self._empty_page = empty_page
        for _label, arch in _NETWORKS:
            self._empty_pages[arch] = empty_page

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        list_box.add_css_class("boxed-list")
        list_box.set_filter_func(self._row_matches_filter)
        list_box.set_sort_func(lambda r1, r2: self._compare_rows(r1, r2))
        list_box.set_header_func(self._list_header)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(list_box)
        page.append(scroller)
        self._list_box = list_box
        for _label, arch in _NETWORKS:
            self._list_boxes[arch] = list_box

        return page

    def _catalogue_row_action(self, row: Gtk.ListBoxRow) -> Adw.ActionRow | None:
        return resolve_catalogue_action_row(row)

    def _browser_filters(self, query: str | None = None) -> BrowserFilters:
        return BrowserFilters(
            self._purpose,
            self._arch_filter,
            self._search_query() if query is None else query,
            self._hide_unsupported,
            self._sort_mode,
        )

    def _project_browser_row(self, arch: str, name: str, reason: str | None = None):
        family = FAMILY_BY_ARCH.get(arch)
        catalogue = getattr(self.manager, f"{family}_download_list", {}) if family else {}
        snapshot = self.manager.latest_snapshot
        by_family = snapshot.meta_by_family if snapshot is not None else {}
        display_meta = by_family.get(family, {}).get(name) if family else None
        row = project_row(
            arch,
            name,
            raw=catalogue.get(name),
            meta=self._catalogue_row_metadata(arch, name),
            intent=self._catalogue_intent(arch, name),
            reason=reason,
            display_meta=display_meta,
        )
        return replace(row, count_roles=self._count_roles(arch, name))

    def _count_roles(self, arch: str, name: str) -> tuple[str | None, tuple[str, ...]]:
        family = FAMILY_BY_ARCH.get(arch)
        scoped = getattr(self.manager, "catalogue_meta_by_family", {})
        meta = scoped.get(family, {}).get(name) if isinstance(scoped, dict) and family else None
        primary, outputs = purpose_roles_from_meta(meta)
        return primary, tuple(outputs or ())

    def _refresh_browser_metadata(self) -> None:
        for key, row in tuple(self.browser.rows.items()):
            primary_role, output_roles = purpose_roles_from_meta(self._catalogue_row_metadata(*key))
            self.browser.rows[key] = replace(
                row,
                intent=self._catalogue_intent(*key),
                primary_role=primary_role,
                output_roles=tuple(output_roles or ()),
                count_roles=self._count_roles(*key),
            )

    def _row_matches_filter(self, row: Gtk.ListBoxRow, arch: str | None = None) -> bool:
        action = self._catalogue_row_action(row)
        key = (
            str(arch or fetch(action, "_uvr_arch", "")),
            str(fetch(action, "_uvr_model_name", "")),
        )
        data = self.browser.rows.get(key)
        if data is None:
            return False
        primary_role, output_roles = purpose_roles_from_meta(self._catalogue_row_metadata(*key))
        data = replace(
            data,
            intent=self._catalogue_intent(*key),
            primary_role=primary_role,
            output_roles=tuple(output_roles or ()),
            count_roles=self._count_roles(*key),
        )
        self.browser.rows[key] = data
        return self.browser.matches(data, self._browser_filters(self._search_query(key[0])))

    def _search_query(self, arch: str = "") -> str:
        entry = getattr(self, "_search_entry", None)
        if entry is None:
            entries = getattr(self, "_search_entries", {}) or {}
            entry = entries.get(arch) if arch else None
            if entry is None and entries:
                entry = next(iter(entries.values()))
        if entry is None:
            return ""
        return str(entry.get_text() or "").strip()

    def _list_header(self, row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
        if network_filter_hides_headers(getattr(self, "_arch_filter", ARCH_FILTER_ALL)):
            row.set_header(None)
            return
        action = self._catalogue_row_action(row)
        network = ""
        if action is not None:
            network = str(fetch(action, "_uvr_network", "") or fetch(action, "_uvr_arch", "") or "")
        if before is not None:
            previous = self._catalogue_row_action(before)
            if previous is not None:
                previous_network = str(
                    fetch(previous, "_uvr_network", "") or fetch(previous, "_uvr_arch", "") or ""
                )
                if previous_network == network:
                    row.set_header(None)
                    return
        heading = next(
            (label for value, label in NETWORK_FILTER_OPTIONS if value == network),
            next((label for label, value in _NETWORKS if value == network), ""),
        )
        if not heading:
            row.set_header(None)
            return
        header = Gtk.Label(label=heading, xalign=0.0)
        header.add_css_class("heading")
        header.add_css_class("dim-label")
        set_inset(header, start=12, top=8, bottom=4)
        row.set_header(header)

    def _row_sort_key(self, row: typing.Any) -> tuple[int, int, int, float, str]:
        key = (fetch(row, "_uvr_arch", ""), fetch(row, "_uvr_model_name", ""))
        data = self.browser.rows.get(key)
        return data.sort_key(self._sort_mode) if data else (99, 0, 0, 0.0, "")

    def _compare_rows(self, row1: typing.Any, row2: typing.Any) -> int:
        left = self._row_sort_key(row1)
        right = self._row_sort_key(row2)
        if left < right:
            return -1
        return 1 if left > right else 0

    def _invalidate_all_sorts(self) -> None:
        for list_box in self._unique_list_boxes():
            list_box.invalidate_sort()
            if hasattr(list_box, "invalidate_headers"):
                list_box.invalidate_headers()
        self._update_catalogue_page_state()

    def _on_hide_unsupported_changed(self, *_args: typing.Any) -> None:
        self._hide_unsupported = bool(self.hide_unsupported_row.get_active())
        self._invalidate_all_filters()
        self._update_tab_counts()
        self._update_status_from_catalogue()

    def _on_search_changed(self, *_args: typing.Any) -> None:
        for list_box in self._unique_list_boxes():
            list_box.invalidate_filter()
        self._update_catalogue_page_state()
        self._update_download_button()
        self._schedule_stem_yaml_fetches()

    def _on_arch_filter_changed(self, *_args: typing.Any) -> None:
        label = get_combo_value(self.arch_row) or _ARCH_FILTER_OPTIONS[0][1]
        self._arch_filter = next(
            (value for value, text in _ARCH_FILTER_OPTIONS if text == label),
            ARCH_FILTER_ALL,
        )
        self._invalidate_all_filters()
        self._schedule_stem_yaml_fetches()

    def _on_sort_changed(self, *_args: typing.Any) -> None:
        label = get_combo_value(self.sort_row) or SORT_OPTIONS[0][1]
        self._sort_mode = next(
            (value for value, text in SORT_OPTIONS if text == label),
            SORT_NAME,
        )
        # Re-sorting in place keeps every checked row, the way Purpose
        # filtering always has. Rebuilding dropped the selection.
        self._invalidate_all_sorts()

    def _unique_list_boxes(self) -> list[Gtk.ListBox]:
        seen: list[Gtk.ListBox] = []
        for list_box in self._list_boxes.values():
            if list_box not in seen:
                seen.append(list_box)
        extra = getattr(self, "_list_box", None)
        if extra is not None and extra not in seen:
            seen.append(extra)
        return seen

    def _invalidate_all_filters(self) -> None:
        for list_box in self._unique_list_boxes():
            list_box.invalidate_filter()
            if hasattr(list_box, "invalidate_headers"):
                list_box.invalidate_headers()
        self._update_catalogue_page_state()
        self._update_download_button()

    def _on_catalogue_tab_changed(self, *_args: typing.Any) -> None:
        name = self.stack.get_visible_child_name()
        known = {value for value, _label in PURPOSE_PAGE_OPTIONS}
        if name in known:
            self._purpose = str(name)
        self._invalidate_all_filters()
        self._update_tab_counts()
        self._schedule_stem_yaml_fetches()

    def select_catalogue(
        self,
        *,
        purpose: str | None = None,
        arch: str | None = None,
    ) -> None:
        """Show a purpose page and network filter (empty-state banner targeting)."""
        known_pages = {value for value, _label in PURPOSE_PAGE_OPTIONS}
        page = purpose or ""
        if page in known_pages:
            self._purpose = page
            if self.stack.get_visible_child_name() != page:
                self.stack.set_visible_child_name(page)
        if arch is not None:
            label = next(
                (text for value, text in _ARCH_FILTER_OPTIONS if value == arch),
                None,
            )
            if label is not None:
                set_combo_value(self.arch_row, label)
        self._invalidate_all_filters()
        self._update_tab_counts()

    def _catalogue_row_metadata(self, arch: str, name: str) -> typing.Any:
        """Resolve one row without flattening equal labels across families."""
        family = FAMILY_BY_ARCH.get(arch)
        scoped = getattr(self.manager, "catalogue_meta_by_family", {})
        if family is not None:
            family_metadata = scoped.get(family, {})
            if name in family_metadata:
                return family_metadata[name]
        return getattr(self.manager, "catalogue_meta", {}).get(name)

    def _network_id_for_row(self, arch: str, name: str) -> str:
        meta = self._catalogue_row_metadata(arch, name)
        files: tuple[str, ...] = ()
        if meta is not None:
            raw_files = getattr(meta, "files", None) or {}
            if isinstance(raw_files, dict):
                files = tuple(str(key) for key in raw_files)
        return catalogue_network_id(family_arch=arch, files=files, label=name)

    def _names_matching_network(self, arch: str, names: list[str]) -> list[str]:
        arch_filter = getattr(self, "_arch_filter", ARCH_FILTER_ALL)
        if arch_filter in ("", ARCH_FILTER_ALL, None):
            return list(names)
        if str(arch_filter) not in MDX_NETWORK_SUBTYPES:
            return list(names)
        return [
            name
            for name in names
            if network_filter_matches(
                str(arch_filter),
                family_arch=arch,
                network=self._network_id_for_row(arch, name),
            )
        ]

    def _row_score(self, arch: str, name: str) -> tuple[str | None, float | None, str]:
        """Return ``(stem, sdr, stems_text)`` for a catalogue label.

        Falls back to the filename regex when the benchmark table has no entry,
        which covers the handful of models whose SDR lives only in their name.
        """
        meta = self._catalogue_row_metadata(arch, name)
        stems_text = catalogue_semantics_subtitle(meta) if meta is not None else ""
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

        stem, sdr, _text = self._row_score(arch, name)
        data = replace(self._project_browser_row(arch, name), sdr_stem=stem, sdr=sdr)
        self.browser.rows[key] = data
        stem, sdr, stems_text = data.sdr_stem, data.sdr, data.semantics
        display = data.display
        action = Adw.ActionRow()
        set_row_title(action, display)
        action.add_prefix(check)
        action.set_activatable_widget(check)
        # Identity stays the raw catalogue label: resolve()/download() key on it.
        stash(action, "_uvr_model_name", name)
        stash(action, "_uvr_display_name", display)
        stash(action, "_uvr_arch", arch)
        stash(action, "_uvr_network", data.network)
        stash(action, "_uvr_check", check)
        stash(action, "_uvr_unsupported", False)
        stash(action, "_uvr_sdr", sdr)
        stash(action, "_uvr_sdr_stem", stem)
        stash(action, "_uvr_stems_text", stems_text)
        stash(action, "_uvr_sort_name", display.casefold())
        set_row_subtitle(action, format_sdr_subtitle(sdr, stem=stem, extra=stems_text))
        meta = self._catalogue_row_metadata(arch, name)
        set_tooltip(action, catalogue_evidence_detail(meta) if meta is not None else "")

        self._row_checks[key] = check
        self._row_actions[key] = action
        self._list_boxes[arch].append(action)

    def _add_unsupported_row(self, arch: str, name: str, reason: str) -> None:
        key = (arch, name)
        if key in self._row_actions:
            return

        data = self._project_browser_row(arch, name, reason)
        self.browser.rows[key] = data
        display = data.display
        action = Adw.ActionRow()
        set_row_title(action, display)
        set_row_subtitle(action, f"Unsupported — {reason}")
        action.add_css_class("dim-label")
        action.set_sensitive(False)
        stash(action, "_uvr_model_name", name)
        stash(action, "_uvr_display_name", display)
        stash(action, "_uvr_arch", arch)
        stash(action, "_uvr_network", data.network)
        stash(action, "_uvr_unsupported", True)
        stash(action, "_uvr_unsupported_reason", reason)
        stash(action, "_uvr_sdr", parse_sdr_score(name))
        stash(action, "_uvr_sdr_stem", None)
        stash(action, "_uvr_stems_text", "")
        stash(action, "_uvr_sort_name", display.casefold())

        self._row_actions[key] = action
        self._list_boxes[arch].append(action)

    def _on_row_check_toggled(self, key: tuple[str, str]) -> None:
        check = self._row_checks.get(key)
        self.browser.set_selected(key, check is not None and check.get_active())
        self._update_download_button()
        if check is None:
            return
        if check.get_active():
            self._lookup_row_size(key)
            return
        action = self._row_actions.get(key)
        if action is not None:
            drop(action, "_uvr_size")
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
        generation = self.browser.generation
        lookup_id = self._size_lookup_ids.get(key, 0) + 1
        self._size_lookup_ids[key] = lookup_id
        jobs_obj = self._resolve_pinned(name, arch)
        jobs: list[tuple[str, str]] = (
            [(str(url), str(path)) for url, path in jobs_obj]
            if isinstance(jobs_obj, (list, tuple))
            else []
        )
        pending = [url for url, path in jobs if url and not os.path.isfile(path)]
        if not pending:

            def worker() -> None:
                text = self.manager.describe_selection_download_size(name, arch)
                idle_on_main(self._apply_row_size, lookup_id, key, text, generation)

            threading.Thread(target=worker, name="uvr-size-lookup", daemon=True).start()
            return

        from core.download_sizes import describe_cached_download_size, request_url_size

        remaining = {"n": len(pending)}
        lock = threading.Lock()

        def on_url(_url: str, _size: int | None) -> None:
            with lock:
                remaining["n"] -= 1
                done = remaining["n"] <= 0
            if done:
                text = describe_cached_download_size(jobs)
                idle_on_main(self._apply_row_size, lookup_id, key, text, generation)

        for url in pending:
            request_url_size(url, on_url)

    def _apply_row_size(self, lookup_id: int, key: tuple[str, str], text: str, generation: int) -> None:
        if self._lifetime.disposed:
            return
        # Guard is keyed per-row: checking another model must not discard this
        # row's own in-flight lookup result.
        if generation != self.browser.generation or self._size_lookup_ids.get(key) != lookup_id:
            return
        action = self._row_actions.get(key)
        if action is not None:
            size_text = text or ""
            stash(action, "_uvr_size", size_text)
            set_row_subtitle(
                action,
                format_sdr_subtitle(
                    fetch(action, "_uvr_sdr", None),
                    size_text,
                    stem=fetch(action, "_uvr_sdr_stem", None),
                    extra=fetch(action, "_uvr_stems_text", ""),
                ),
            )

    def _selected_entries(self) -> list[tuple[str, str]]:
        return [(name, arch) for arch, name in self.browser.selected_keys()]

    def _selected_count_by_purpose(self) -> dict[str, int]:
        self._refresh_browser_metadata()
        return self.browser.selected_counts()

    def _update_tab_badges(self) -> None:
        if not self._stack_pages:
            return
        selected = self._selected_count_by_purpose()
        for value, _label in PURPOSE_PAGE_OPTIONS:
            page = self._stack_pages.get(value)
            if page is not None:
                count = selected.get(value, 0)
                page.set_badge_number(count)
                page.set_needs_attention(count > 0)

    def _filter_archs(self) -> list[str]:
        arch_filter = getattr(self, "_arch_filter", ARCH_FILTER_ALL)
        if arch_filter in ("", ARCH_FILTER_ALL, None):
            return [arch for _label, arch in _NETWORKS]
        family = family_arch_for_network_filter(str(arch_filter))
        if family in ("", ARCH_FILTER_ALL, None):
            return [arch for _label, arch in _NETWORKS]
        return [family]

    def _update_download_button(self) -> None:
        count = len(self._selected_entries())
        if count:
            self.download_button.set_label(f"Download ({count})")
            self.download_button.set_sensitive(not self._refreshing)
        else:
            self.download_button.set_label("Download")
            self.download_button.set_sensitive(False)
        if self.browser.available:
            total = sum(
                1
                for _arch, models in self.browser.available.items()
                for name in models
                if name not in (NO_NEW_MODELS, NO_CONNECTION)
            )
            query = self._search_query()
            purpose_label = next(
                (label for value, label in PURPOSE_PAGE_OPTIONS if value == self._purpose),
                next(
                    (label for value, label in PURPOSE_FILTER_OPTIONS if value == self._purpose),
                    "selected purpose",
                ),
            )
            arch_filter = getattr(self, "_arch_filter", ARCH_FILTER_ALL)
            filtered = query or self._purpose not in ("", PURPOSE_ALL, None)
            if filtered:
                shown = sum(self._matching_count(arch, query) for arch in self._filter_archs())
                if query:
                    message = f"{shown} match{'es' if shown != 1 else ''} for “{query}”"
                else:
                    message = f"{shown} {purpose_label.casefold()} model{'s' if shown != 1 else ''}"
                if arch_filter not in ("", ARCH_FILTER_ALL, None):
                    network_label = next(
                        (label for value, label in NETWORK_FILTER_OPTIONS if value == arch_filter),
                        "current network",
                    )
                    message += f" in {network_label}"
                self._set_catalogue_status(message)
            elif count:
                self._set_catalogue_status(
                    f"{count} selected · {total} available across all networks"
                )
            elif not self._refreshing:
                if total:
                    self._set_catalogue_status(
                        f"{total} models available — check one or more, then Download"
                    )
                else:
                    self._set_catalogue_status("All available models are already installed")
        self._update_tab_badges()

    def start_refresh(self) -> None:
        if self._refreshing:
            return
        debug("download", "ui refresh start")
        self._refreshing = True
        self._refresh_spinner.set_visible(True)
        self._refresh_spinner.start()
        self.refresh_button.set_sensitive(False)
        self._update_download_button()
        self.status_label.set_label("Refreshing catalogue…")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        try:
            is_online = self.manager.refresh()
            if is_online and self.settings.process.auto_update_model_params:
                self.manager.update_model_settings(self.context.repo)
            usable = is_online or self.manager.ensure_catalogues()
            available = self.manager.available_downloads() if usable else {}
            unsupported = self.manager.unsupported_downloads() if usable else {}
        except Exception as exc:  # surfaced through the UI/log
            from .errorlog import log_error

            log_error("Download Center", exc, context="refreshing catalogue")
            idle_on_main(self._refresh_failed, str(exc).strip() or type(exc).__name__)
            return
        idle_on_main(self._refresh_done, is_online, available, unsupported)

    def _finish_refresh_controls(self) -> None:
        self._refreshing = False
        self.refresh_button.set_sensitive(True)
        self._refresh_spinner.stop()
        self._refresh_spinner.set_visible(False)

    def _refresh_failed(self, message: str) -> None:
        if self._lifetime.disposed:
            return
        self._finish_refresh_controls()
        self._catalogue_online = False
        if self.browser.available:
            self._catalogue_notice = "Refresh failed — showing previous catalogue · "
            self._update_download_button()
        else:
            self._catalogue_notice = ""
            self.status_label.set_label("Catalogue refresh failed")
            for _label, arch in _NETWORKS:
                self._set_catalogue_page_message(
                    arch,
                    "Catalogue unavailable",
                    description="The catalogue could not be refreshed. Try again.",
                    offline=True,
                )
        self._toast(f"Couldn't refresh catalogue: {message}")

    def _refresh_done(
        self,
        is_online: bool,
        available: dict,
        unsupported: dict | None = None,
    ) -> None:
        if self._lifetime.disposed:
            return
        self._finish_refresh_controls()
        self._catalogue_online = is_online
        if not is_online and not available and not self.browser.available:
            self._catalogue_notice = ""
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

        if is_online or available:
            self.browser.available = available
            self.browser.unsupported = unsupported or {}
        self._catalogue_notice = "" if is_online else "Offline — showing saved catalogue · "
        self._rebuild_catalogue()
        counts = {arch: len(models) for arch, models in available.items()}
        debug(
            "download",
            f"ui refresh done available={counts} "
            f"unsupported={ {a: len(r) for a, r in self.browser.unsupported.items()} }",
        )
        self._update_tab_counts()
        self._update_status_from_catalogue()
        self._update_download_button()
        self._ensure_background_listeners()
        self._pin_current_snapshot()
        self._schedule_stem_yaml_fetches()

    def _pin_current_snapshot(self) -> None:
        self.browser.pin(self.manager.latest_snapshot)

    def _pinned_catalogue(self, arch: str) -> dict | None:
        return self.browser.pinned_catalogue(arch)

    def _resolve_pinned(self, selection: str, arch: str) -> typing.Any:
        catalogue = self._pinned_catalogue(arch)
        return self.manager.resolve(selection, arch, catalogue=catalogue)

    def _ensure_background_listeners(self) -> None:
        """Listen for both background catalogue refinements.

        Stem YAML fetches rewrite subtitles; the size warmup's identity HEADs
        can drop whole rows. Both land after the list has rendered, and both
        notify from a worker thread.
        """
        if self._listening or self._lifetime.disposed:
            return
        self._listening = True
        from core.catalogue_stem_cache import ensure_worker_started, subscribe, unsubscribe
        self._lifetime.own(lambda: unsubscribe(self._schedule_stem_subtitle_refresh))
        self._lifetime.own(lambda: self.manager.unsubscribe_catalogue_changed(self._schedule_catalogue_row_refresh))
        self._lifetime.own(lambda: self.manager.unsubscribe_delta(self._on_catalogue_delta))

        subscribe(self._schedule_stem_subtitle_refresh)
        ensure_worker_started()
        self.manager.subscribe_catalogue_changed(self._schedule_catalogue_row_refresh)
        subscribe_delta = getattr(self.manager, "subscribe_delta", None)
        if callable(subscribe_delta):
            subscribe_delta(self._on_catalogue_delta)

    def _on_catalogue_delta(self, delta: object) -> None:
        kind = getattr(delta, "kind", None)
        value = getattr(kind, "value", kind)
        if value == "identity_refined" or getattr(delta, "removal_only", False):
            self._schedule_catalogue_row_refresh()
            return
        if value == "metadata_changed":
            self._schedule_stem_subtitle_refresh()
            return
        self.browser.pending_source = True

    def _schedule_catalogue_row_refresh(self) -> None:
        idle_on_main(self._arm_catalogue_row_refresh)

    def _arm_catalogue_row_refresh(self) -> None:
        if self._lifetime.disposed:
            return
        if self._catalogue_refresh_armed:
            return
        self._catalogue_refresh_armed = True
        from gi.repository import GLib

        self._lifetime.timeout(GLib, 250, self._flush_catalogue_row_refresh)

    def _flush_catalogue_row_refresh(self) -> bool:
        """Drop rows the content dedupe removed, leaving the rest alone.

        Deliberately not ``_rebuild_catalogue``: this fires while the user is
        browsing, and a rebuild clears every list box — resetting scroll
        position and recreating ~500 rows to delete a handful. Dedupe only ever
        removes, so removal is the whole contract.
        """
        self._catalogue_refresh_armed = False
        self.browser.available = self.manager.available_downloads()
        self.browser.unsupported = self.manager.unsupported_downloads()

        live: set[tuple[str, str]] = set()
        for arch, names in self.browser.available.items():
            for name in names:
                live.add((arch, name))
        for arch, rows in self.browser.unsupported.items():
            for name, _reason in rows:
                live.add((arch, name))

        gone = self.browser.remove_missing(live)
        if not gone:
            return False

        for key in gone:
            arch, _name = key
            action = self._row_actions.pop(key, None)
            self._row_checks.pop(key, None)
            self._size_lookup_ids.pop(key, None)
            list_box = self._list_boxes.get(arch)
            if list_box is not None and action is not None:
                list_box.remove(action)

        debug("download", f"catalogue refresh removed {len(gone)} row(s)")
        self._update_tab_counts()
        self._update_status_from_catalogue()
        # A removed row may have been checked — the button count must follow.
        self._update_download_button()
        return False

    def _visible_catalogue_labels(self) -> list[str]:
        """Labels the user can actually see: active tab, current filters.

        Scoped to the visible stack page — matching every tab's filter would
        make "visible" mean most of the catalogue and drain the priority lane
        of any meaning. Falls back to all tabs before a page is selected.
        """
        return [label for _family, label in self._visible_catalogue_entries()]

    def _visible_catalogue_entries(self) -> list[tuple[str, str]]:
        """Return visible canonical selections with their catalogue family."""
        archs = [
            arch
            for arch in self._filter_archs()
            if arch in (self.browser.available or {}) or arch in (self.browser.unsupported or {})
        ]
        if not archs:
            archs = list(self.browser.available)
        entries: list[tuple[str, str]] = []
        query = self._search_query()
        for arch in archs:
            family = FAMILY_BY_ARCH.get(arch)
            if family is None:
                continue
            names = self._names_matching_network(arch, list(self.browser.available.get(arch) or []))
            intents = self._catalogue_intents(family)
            primaries, outputs = self._catalogue_role_maps(family)
            entries.extend(
                (family, label)
                for label in catalogue_matches(
                    names,
                    query,
                    purpose=self._purpose,
                    intents=intents,
                    arches={name: arch for name in names},
                    primary_roles=primaries,
                    output_roles=outputs,
                )
            )
        return entries

    def _all_catalogue_entries(self) -> list[tuple[str, str]]:
        """Return all current rows as family-scoped canonical selections."""
        return [
            (family, label)
            for arch, labels in self.browser.available.items()
            if (family := FAMILY_BY_ARCH.get(arch)) is not None
            for label in labels
            if label not in (NO_NEW_MODELS, NO_CONNECTION)
        ]

    def _catalogue_intents(self, family: str) -> dict[str, str]:
        """Return curated purpose metadata for the current catalogue rows."""
        manager = getattr(self, "manager", None)
        scoped = getattr(manager, "catalogue_meta_by_family", {})
        metadata = scoped.get(family, {}) if isinstance(scoped, dict) else {}
        return {label: meta.intent for label, meta in metadata.items() if meta.intent}

    def _catalogue_role_maps(
        self, family: str
    ) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
        """Return reviewed stem roles keyed by catalogue label."""
        manager = getattr(self, "manager", None)
        scoped = getattr(manager, "catalogue_meta_by_family", {})
        metadata = scoped.get(family, {}) if isinstance(scoped, dict) else {}
        primaries: dict[str, str] = {}
        outputs: dict[str, tuple[str, ...]] = {}
        for label, meta in metadata.items():
            primary_role, roles = purpose_roles_from_meta(meta)
            if primary_role:
                primaries[label] = primary_role
            if roles:
                outputs[label] = roles
        return primaries, outputs

    def _catalogue_intent(self, arch: str, label: str) -> str | None:
        manager = getattr(self, "manager", None)
        scoped = getattr(manager, "catalogue_meta_by_family", {})
        family = FAMILY_BY_ARCH.get(arch)
        metadata = scoped.get(family, {}) if isinstance(scoped, dict) and family else {}
        meta = metadata.get(label)
        return meta.intent if meta is not None else None

    def _schedule_stem_yaml_fetches(self) -> None:
        if self._lifetime.disposed:
            return
        """Arm a debounced rescan; a burst of typing costs one pass, not one each."""
        if self._stem_fetch_armed:
            return
        self._stem_fetch_armed = True
        from gi.repository import GLib

        self._lifetime.timeout(GLib, 250, self._flush_stem_yaml_fetches)

    def _flush_stem_yaml_fetches(self) -> bool:
        """Prioritize visible rows, then drain the rest while DC is open."""
        self._stem_fetch_armed = False
        from core.catalogue_stem_cache import catalogue_stems_enabled

        if not catalogue_stems_enabled():
            return False
        visible = tuple(self._visible_catalogue_entries())
        visible_set = set(visible)
        bulk = tuple(entry for entry in self._all_catalogue_entries() if entry not in visible_set)
        if visible:
            self.manager.queue_catalogue_evidence(visible, priority=True)
        if bulk:
            self.manager.queue_catalogue_evidence(bulk, priority=False)
        return False

    def _schedule_stem_subtitle_refresh(self) -> None:
        idle_on_main(self._arm_stem_subtitle_refresh)

    def _arm_stem_subtitle_refresh(self) -> None:
        if self._lifetime.disposed:
            return
        if self._stem_refresh_armed:
            return
        self._stem_refresh_armed = True
        from gi.repository import GLib

        self._lifetime.timeout(GLib, 200, self._flush_stem_subtitles)

    def _flush_stem_subtitles(self) -> bool:
        self._stem_refresh_armed = False
        updated = self.manager.apply_catalogue_stem_cache()
        if not updated:
            return False
        for key, action in self._row_actions.items():
            arch, name = key
            if name not in updated:
                continue
            if fetch(action, "_uvr_unsupported", False):
                continue
            meta = self._catalogue_row_metadata(arch, name)
            data = self.browser.rows[key]
            data = replace(
                data,
                semantics=catalogue_semantics_subtitle(meta) if meta is not None else "",
                evidence_detail=catalogue_evidence_detail(meta) if meta is not None else "",
            )
            self.browser.rows[key] = data
            stems_text = data.semantics
            stash(action, "_uvr_stems_text", stems_text)
            set_tooltip(action, data.evidence_detail)
            set_row_subtitle(
                action,
                format_sdr_subtitle(
                    fetch(action, "_uvr_sdr", None),
                    fetch(action, "_uvr_size", ""),
                    stem=fetch(action, "_uvr_sdr_stem", None),
                    extra=stems_text,
                ),
            )
        return False

    def _available_count(self) -> int:
        return self.browser.available_count()

    def _unsupported_count(self, *, visible_only: bool = False) -> int:
        return self.browser.unsupported_count(hide=visible_only and self._hide_unsupported)

    def _update_status_from_catalogue(self) -> None:
        total = self.browser.available_count()
        unsupported = self._unsupported_count(visible_only=True)
        selected = len(self._selected_entries())
        if selected:
            self._set_catalogue_status(
                f"{selected} selected · {total} available across all networks"
            )
            return
        if total and unsupported:
            self._set_catalogue_status(f"{total} downloadable · {unsupported} unsupported shown")
        elif total:
            self._set_catalogue_status(
                f"{total} models available — check one or more, then Download"
            )
        elif unsupported:
            self._set_catalogue_status(
                f"{unsupported} unsupported models listed (not downloadable)"
            )
        else:
            self._set_catalogue_status("All available models are already installed")

    def _set_catalogue_status(self, message: str) -> None:
        notice = getattr(self, "_catalogue_notice", "")
        self.status_label.set_label(f"{notice}{message}")

    def _update_tab_counts(self) -> None:
        search = getattr(self, "_search_entry", None)
        if search is None and self._search_entries:
            search = next(iter(self._search_entries.values()))
        if search is None:
            return
        purpose_label = next(
            (label for value, label in PURPOSE_PAGE_OPTIONS if value == self._purpose),
            "models",
        )
        self._refresh_browser_metadata()
        view = project_browser(self.browser, self._browser_filters(""), online=self._catalogue_online)
        count = view.placeholder_count
        search.set_placeholder_text(f"Search {purpose_label.casefold()} — {count} available")

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
        page = self._empty_pages.get(arch) or getattr(self, "_empty_page", None)
        list_box = self._list_boxes.get(arch) or getattr(self, "_list_box", None)
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
        page.set_icon_name("network-offline-symbolic" if offline else "edit-find-symbolic")
        child = page.get_child()
        if child is not None:
            child.set_visible(offline)
        page.set_visible(True)
        if list_parent is not None:
            list_parent.set_visible(False)

    def _update_catalogue_page_state(self, arch: str | None = None) -> None:
        self._refresh_browser_metadata()
        view = project_browser(self.browser, self._browser_filters(), online=self._catalogue_online)
        self._set_catalogue_page_message(
            arch or next(iter(self._empty_pages), ""),
            view.title,
            description=view.description,
            offline=view.offline,
        )

    def _matching_count(self, arch: str, query: str) -> int:
        self._refresh_browser_metadata()
        return self.browser.matching_count(arch, self._browser_filters(query))

    def _rebuild_catalogue(self) -> None:
        previously_selected = self.browser.selected_keys()
        rows = []
        for _label, arch in _NETWORKS:
            rows.extend(
                self._project_browser_row(arch, name)
                for name in self.browser.available.get(arch, ())
                if name not in (NO_NEW_MODELS, NO_CONNECTION)
            )
            rows.extend(
                self._project_browser_row(arch, name, reason)
                for name, reason in sorted(
                    self.browser.unsupported.get(arch, ()), key=lambda pair: pair[0].casefold()
                )
                if (arch, name) not in {row.key for row in rows}
            )
        self.browser.replace_rows(rows)
        self._pin_current_snapshot()
        self._clear_catalogue()
        for _label, arch in _NETWORKS:
            models = [
                name
                for name in (self.browser.available.get(arch) or [])
                if name not in (NO_NEW_MODELS, NO_CONNECTION)
            ]
            for name in models:
                self._add_model_row(arch, name)
            unsupported = sorted(
                self.browser.unsupported.get(arch) or [],
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
        ids: list[str] = []
        already_queued = 0
        for name, arch in entries:
            if self.queue.active_item_id(name, arch) is not None:
                already_queued += 1
                continue
            jobs = self._resolve_pinned(name, arch)
            action = self._row_actions.get((arch, name))
            display = fetch(action, "_uvr_display_name", name) if action is not None else name
            item_id = self.queue.enqueue(name, arch, jobs=jobs, label=str(display or name))
            if item_id:
                ids.append(item_id)
        if not ids:
            if already_queued:
                for name, arch in entries:
                    check = self._row_checks.get((arch, name))
                    if check is not None:
                        check.set_active(False)
                self._update_download_button()
                noun = "download" if already_queued == 1 else "downloads"
                self._toast(f"{already_queued} {noun} already queued")
                return
            self._toast("Nothing to download for the current selection")
            return
        for arch, name in [(a, n) for n, a in entries]:
            check = self._row_checks.get((arch, name))
            if check is not None:
                check.set_active(False)
        self._update_download_button()
        message = f"Queued {len(ids)} download(s)"
        if already_queued:
            message += f"; {already_queued} already queued"
        self._toast(message)

    def refresh_after_downloads(self) -> None:
        """Remove newly installed rows without disturbing catalogue state."""
        self._catalogue_online = True
        if not self.window.get_visible():
            # The cached window survives close by being hidden. Avoid rebuilding
            # hundreds of rows off-screen; consume the latest manager state on
            # the next presentation instead.
            self._downloads_dirty = True
            return
        self._apply_download_completion_refresh()

    def _apply_download_completion_refresh(self) -> None:
        self._downloads_dirty = False
        # Downloads only make catalogue rows unavailable. Reuse the incremental
        # removal path so active tab, filters, checkboxes, and scroll survive.
        self._flush_catalogue_row_refresh()

    def _open_manual(self) -> None:
        from .download import open_manual_downloads

        open_manual_downloads(self.window, self.context)

    def _open_models_folder(self) -> None:
        """Open the model folder for the network filter, or the models root."""
        from .files import open_folder_in_file_manager

        arch = family_arch_for_network_filter(str(getattr(self, "_arch_filter", ARCH_FILTER_ALL)))
        if arch in ("", ARCH_FILTER_ALL, None):
            target = paths.MODELS_DIR
        else:
            target = self.manager.model_directory(arch)
        if not target:
            target = paths.MODELS_DIR
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as exc:
            self._toast(f"Couldn't open models folder: {exc}")
            return
        open_folder_in_file_manager(self.window, target, on_error=self._toast)

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))
