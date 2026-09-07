"""Download Center window — catalogue browser and download queue."""

from __future__ import annotations

import os
import threading
import typing
from dataclasses import replace

from gi.repository import Adw, Gio, GObject, Gtk

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
from core.model_catalogue import catalogue_label_matches
from core.model_identity import FAMILY_BY_ARCH
from core.model_scores import (
    ARCH_FILTER_ALL,
    MDX_NETWORK_SUBTYPES,
    PURPOSE_INSTRUMENTAL,
    PURPOSE_PAGE_OPTIONS,
    PURPOSE_VOCALS,
    SORT_NAME,
    SORT_SDR,
    catalogue_network_id,
    family_arch_for_network_filter,
    format_sdr_subtitle,
    load_model_scores,
    network_filter_matches,
    parse_sdr_score,
    purpose_roles_from_meta,
    sdr_for_files,
)

from .catalogue_browser import (
    BrowserFilters,
    CatalogueBrowserState,
    LiveCatalogueCounts,
    LiveCatalogueEntry,
    catalogue_evidence_detail,
    catalogue_matches,
    project_live_counts,
    project_row,
)
from .dialogs.utils import close_on_escape
from .dispatch import idle_on_main
from .download_presentation import (
    ARCHITECTURE_LABELS,
    ARCHITECTURES,
    PURPOSE_DESCRIPTIONS,
    SEARCH_LABELS,
    architecture_for,
    compare_models,
    output_summary,
    purpose_score,
)
from .hints import set_icon_button_a11y, set_tooltip
from .lifetime import UiLifetime
from .markup import set_row_subtitle, set_row_title
from .template import load_builder, object_from_builder
from .widget_state import drop, fetch, stash

_NETWORKS = [
    ("VR Arch", VR_ARCH_TYPE),
    ("MDX-Net", MDX_ARCH_TYPE),
    ("Demucs", DEMUCS_ARCH_TYPE),
    # Apollo models are restoration (Audio Tools), not separation networks, but
    # they share the catalogue/queue plumbing so they stay in the network filter.
    ("Apollo", APOLLO_ARCH_TYPE),
]

_ARCH_FILTER_OPTIONS = ARCHITECTURES


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
        self._descending = False
        self._compact_rows = False
        self._syncing_purpose = False
        self._purpose = PURPOSE_VOCALS
        self._arch_filter = ARCH_FILTER_ALL
        self._sort_mode = SORT_NAME
        self._hide_unsupported = False
        self._stem_refresh_armed = False
        self._stem_fetch_armed = False
        self._catalogue_refresh_armed = False
        self._downloads_dirty = False

        self._layout_builder = load_builder("download-center")
        self.window = object_from_builder(self._layout_builder, "window", Adw.Window)
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

        self.toast_overlay = object_from_builder(
            self._layout_builder, "toast_overlay", Adw.ToastOverlay
        )
        self._build_content()

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

    def _build_content(self) -> None:
        def get[T: GObject.Object](name: str, cls: type[T]) -> T:
            return object_from_builder(self._layout_builder, name, cls)

        self.switcher = get("purposes", Gtk.Box)
        self.compact_purpose = get("compact_purpose", Gtk.DropDown)
        self._purpose_buttons: dict[str, Gtk.ToggleButton] = {}
        self._purpose_badges: dict[str, Gtk.Label] = {}
        # The hidden stack preserves the existing navigation entry point.
        self.stack = Gtk.Stack()
        for (value, _label), widget_id in zip(
            PURPOSE_PAGE_OPTIONS,
            ("vocals", "instrumental", "karaoke", "stems", "fx", "removal", "restore"),
            strict=True,
        ):
            self.stack.add_titled(Gtk.Box(), value, _label)
            button = get(widget_id, Gtk.ToggleButton)
            self._purpose_buttons[value] = button
            self._purpose_badges[value] = get(widget_id + "_badge", Gtk.Label)
            button.connect("toggled", self._on_purpose_button, value)
        self.stack.set_visible_child_name(self._purpose)
        self.stack.connect("notify::visible-child-name", self._on_catalogue_tab_changed)
        self.compact_purpose.set_model(
            Gtk.StringList.new([label for _, label in PURPOSE_PAGE_OPTIONS])
        )
        self.compact_purpose.connect("notify::selected", self._on_compact_purpose)
        self.arch_row = get("network", Gtk.DropDown)
        self.arch_row.set_model(Gtk.StringList.new([label for _, label in _ARCH_FILTER_OPTIONS]))
        self.arch_row.connect("notify::selected", self._on_arch_filter_changed)
        self.sort_row = get("sort", Gtk.DropDown)
        self.sort_row.set_model(Gtk.StringList.new(["Name", "SDR"]))
        self.sort_row.connect("notify::selected", self._on_sort_changed)
        self.direction_button = get("direction", Gtk.Button)
        self.direction_icon = get("direction_icon", Gtk.Image)
        self.direction_label = get("direction_label", Gtk.Label)
        self.direction_button.connect("clicked", self._toggle_direction)
        self.hide_unsupported_row = get("supported", Gtk.CheckButton)
        self.hide_unsupported_row.connect("toggled", self._on_hide_unsupported_changed)
        get("reset_filters", Gtk.Button).connect("clicked", self._reset_filters)
        get("empty_reset", Gtk.Button).connect("clicked", self._reset_or_retry)
        self.refresh_button = get("refresh_button", Gtk.Button)
        self.refresh_button.connect("clicked", lambda *_: self.start_refresh())
        set_icon_button_a11y(self.refresh_button, "Refresh catalogue")
        self.download_button = get("download_button", Gtk.Button)
        self.download_button.connect("clicked", lambda *_: self._enqueue_selected())
        self.clear_button = get("clear", Gtk.Button)
        self.clear_button.connect("clicked", self._clear_selection)
        self.selection_summary = get("selection_summary", Gtk.Stack)
        self.selection_label = get("selection", Gtk.Label)
        self.sizes_label = get("sizes", Gtk.Label)
        self.status_label = get("status_label", Gtk.Label)
        self.filter_summary = get("filter_summary", Gtk.Label)
        self._refresh_spinner = get("refresh_spinner", Gtk.Spinner)
        self._search_entry = get("search", Gtk.SearchEntry)
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._list_box = get("models", Gtk.ListBox)
        self._list_box.set_filter_func(self._row_matches_filter)
        self._list_box.set_sort_func(self._compare_rows)
        self._empty_page = get("empty_page", Adw.StatusPage)
        self.results = get("results", Gtk.Stack)
        for _, arch in _NETWORKS:
            self._search_entries[arch] = self._search_entry
            self._list_boxes[arch] = self._list_box
            self._empty_pages[arch] = self._empty_page
        self.window.set_size_request(360, 440)
        for width, narrow_filters in ((780, False), (512, True)):
            bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {width}sp"))
            bp.add_setter(self.switcher, "visible", False)
            bp.add_setter(self.compact_purpose, "visible", True)
            if narrow_filters:
                bp.add_setter(get("filter_bar", Gtk.Box), "orientation", Gtk.Orientation.VERTICAL)
                bp.add_setter(get("sort_controls", Gtk.Box), "halign", Gtk.Align.START)
            self.window.add_breakpoint(bp)
        self.window.connect("notify::current-breakpoint", self._on_breakpoint_changed)
        self._update_tab_counts()
        self._update_download_button()

    def _on_purpose_button(self, button: Gtk.ToggleButton, purpose: str) -> None:
        if button.get_active() and not self._syncing_purpose:
            self.stack.set_visible_child_name(purpose)

    def _on_compact_purpose(self, *_args: object) -> None:
        index = self.compact_purpose.get_selected()
        if not self._syncing_purpose and index < len(PURPOSE_PAGE_OPTIONS):
            self.stack.set_visible_child_name(PURPOSE_PAGE_OPTIONS[index][0])

    def _reset_filters(self, *_args: object) -> None:
        self.arch_row.set_selected(0)
        self.hide_unsupported_row.set_active(False)

    def _reset_or_retry(self, *_args: object) -> None:
        if self._empty_page.get_icon_name() == "network-offline-symbolic":
            self.start_refresh()
        else:
            self._search_entry.set_text("")
            self._reset_filters()

    def _clear_selection(self, *_args: object) -> None:
        for check in self._row_checks.values():
            check.set_active(False)

    def _toggle_direction(self, *_args: object) -> None:
        self._descending = not self._descending
        self._update_direction()
        self._invalidate_all_sorts()

    def _update_direction(self) -> None:
        by_score = self._sort_mode == SORT_SDR
        label = (
            ("High first" if self._descending else "Low first")
            if by_score
            else ("Z–A" if self._descending else "A–Z")
        )
        opposite = (
            ("Low first" if self._descending else "High first")
            if by_score
            else ("A–Z" if self._descending else "Z–A")
        )
        self.direction_label.set_label(label)
        self.direction_button.set_tooltip_text(f"{label} — switch to {opposite}")
        # The supplied 'down' asset emphasizes the upward arrow.
        self.direction_icon.set_from_icon_name(
            "vertical-arrows-down-symbolic" if self._descending else "vertical-arrows-up-symbolic"
        )

    def _on_breakpoint_changed(self, *_args: object) -> None:
        # Observe the final breakpoint, not its individual apply/unapply signals:
        # both compact layouts place row status text in the subtitle.
        self._adapt_rows(self.window.get_current_breakpoint() is not None)

    def _adapt_rows(self, compact: bool) -> None:
        if self._compact_rows == compact:
            return
        self._compact_rows = compact
        for key, action in self._row_actions.items():
            if fetch(action, "_uvr_size", ""):
                self._render_row_status(key)

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
        meta = self._catalogue_row_metadata(arch, name)
        network, _ = architecture_for(
            family, tuple(getattr(meta, "files", {}) or {}), name, row.display
        )
        return replace(row, network=network, semantics=output_summary(meta))

    def _count_roles(self, arch: str, name: str) -> tuple[str | None, tuple[str, ...]]:
        family = FAMILY_BY_ARCH.get(arch)
        scoped = getattr(self.manager, "catalogue_meta_by_family", {})
        meta = scoped.get(family, {}).get(name) if isinstance(scoped, dict) and family else None
        primary, outputs = purpose_roles_from_meta(meta)
        return primary, tuple(outputs or ())

    def _live_catalogue_counts(self, filters: BrowserFilters) -> LiveCatalogueCounts:
        entries = []
        for arch, names in self.browser.available.items():
            for name in names:
                primary, outputs = self._count_roles(arch, name)
                entries.append(
                    LiveCatalogueEntry(
                        (arch, name),
                        self._network_id_for_row(arch, name),
                        self._catalogue_intent(arch, name),
                        primary,
                        outputs,
                    )
                )
        for arch, rows in self.browser.unsupported.items():
            for name, reason in rows:
                primary, outputs = purpose_roles_from_meta(self._catalogue_row_metadata(arch, name))
                entries.append(
                    LiveCatalogueEntry(
                        (arch, name),
                        self._network_id_for_row(arch, name),
                        self._catalogue_intent(arch, name),
                        primary,
                        tuple(outputs or ()),
                        reason,
                    )
                )
        return project_live_counts(tuple(entries), filters)

    def _refresh_browser_metadata(self) -> None:
        for key, row in tuple(self.browser.rows.items()):
            primary_role, output_roles = purpose_roles_from_meta(self._catalogue_row_metadata(*key))
            self.browser.rows[key] = replace(
                row,
                intent=self._catalogue_intent(*key),
                primary_role=primary_role,
                output_roles=tuple(output_roles or ()),
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
        )
        self.browser.rows[key] = data
        return self._matches(data, self._search_query(key[0]))

    def _matches(self, data: typing.Any, query: str | None = None) -> bool:
        if self._arch_filter not in ("", ARCH_FILTER_ALL, data.network, data.key[0]):
            return False
        if not self.browser.matches(
            data, replace(self._browser_filters(""), network=ARCH_FILTER_ALL)
        ):
            return False
        text = f"{data.key[1]} {data.display} {data.semantics} {ARCHITECTURE_LABELS.get(data.network, '')} {data.reason or ''}"
        return catalogue_label_matches(
            data.key[1], self._search_query() if query is None else query, extra=text
        )

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

    def _compare_rows(self, row1: typing.Any, row2: typing.Any) -> int:
        left = self.browser.rows.get(
            (fetch(row1, "_uvr_arch", ""), fetch(row1, "_uvr_model_name", ""))
        )
        right = self.browser.rows.get(
            (fetch(row2, "_uvr_arch", ""), fetch(row2, "_uvr_model_name", ""))
        )
        if left is None or right is None:
            return 0
        return compare_models(
            left.display,
            left.sdr,
            left.reason is not None,
            right.display,
            right.sdr,
            right.reason is not None,
            self._sort_mode == SORT_SDR,
            getattr(self, "_descending", False),
        )

    def _invalidate_all_sorts(self) -> None:
        for list_box in self._unique_list_boxes():
            list_box.invalidate_sort()
            if hasattr(list_box, "invalidate_headers"):
                list_box.invalidate_headers()
        self._update_catalogue_page_state()

    def _on_hide_unsupported_changed(self, *_args: typing.Any) -> None:
        self._hide_unsupported = bool(self.hide_unsupported_row.get_active())
        self.filter_summary.set_label("Unsupported hidden" if self._hide_unsupported else "")
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
        index = self.arch_row.get_selected()
        self._arch_filter = (
            _ARCH_FILTER_OPTIONS[index][0] if index < len(_ARCH_FILTER_OPTIONS) else ARCH_FILTER_ALL
        )
        self._invalidate_all_filters()
        self._schedule_stem_yaml_fetches()

    def _on_sort_changed(self, *_args: typing.Any) -> None:
        self._sort_mode = SORT_SDR if self.sort_row.get_selected() == 1 else SORT_NAME
        self._descending = self._sort_mode == SORT_SDR
        self._update_direction()
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
        known = {value for value, _ in PURPOSE_PAGE_OPTIONS}
        if name not in known:
            return
        previous = self._purpose
        self._purpose = str(name)
        score_pages = (PURPOSE_VOCALS, PURPOSE_INSTRUMENTAL)
        if self._purpose not in score_pages or previous not in score_pages:
            self.sort_row.set_selected(0)
            self._sort_mode = SORT_NAME
            self._descending = False
        self.sort_row.set_visible(self._purpose in score_pages)
        self._update_direction()
        self._syncing_purpose = True
        try:
            self._purpose_buttons[self._purpose].set_active(True)
            self.compact_purpose.set_selected(
                next(
                    i for i, (value, _) in enumerate(PURPOSE_PAGE_OPTIONS) if value == self._purpose
                )
            )
        finally:
            self._syncing_purpose = False
        for key in self._row_actions:
            self._render_row(key)
        self._invalidate_all_filters()
        self._invalidate_all_sorts()
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
            if self.stack.get_visible_child_name() != page:
                self.stack.set_visible_child_name(page)
        if arch is not None:
            target = FAMILY_BY_ARCH.get(arch, arch)
            # A request for the whole MDX backend does not imply Classic MDX.
            if target == "mdx":
                target = ARCH_FILTER_ALL
            index = next(
                (i for i, (value, _) in enumerate(_ARCH_FILTER_OPTIONS) if value == target), 0
            )
            self.arch_row.set_selected(index)
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
        meta = self._catalogue_row_metadata(arch, name)
        score = purpose_score(
            sdr_for_files(getattr(meta, "files", {}) or {}, load_model_scores(allow_network=False)),
            self._purpose,
            len(getattr(meta, "stems", ()) or ()) or 2,
        )
        stem = (
            ("Vocal" if self._purpose == PURPOSE_VOCALS else "Instrumental")
            if score is not None
            else None
        )
        return stem, score, output_summary(meta)

    def _render_row(self, key: tuple[str, str]) -> None:
        action = self._row_actions.get(key)
        data = self.browser.rows.get(key)
        if action is None or data is None:
            return
        stem, score, outputs = self._row_score(*key)
        self.browser.rows[key] = replace(data, sdr=score, sdr_stem=stem, semantics=outputs)
        stash(action, "_uvr_stems_text", outputs)
        parts = ["Unsupported in this build" if data.reason is not None else outputs]
        if score is not None and data.reason is None:
            parts.append(f"{stem} SDR {score:.2f} dB")
        stash(action, "_uvr_base_subtitle", " · ".join(parts))
        self._render_row_status(key)
        set_tooltip(action, catalogue_evidence_detail(self._catalogue_row_metadata(*key)))

    def _render_row_status(self, key: tuple[str, str]) -> None:
        """Place size text using cached presentation; resizing never reacquires metadata."""
        action = self._row_actions.get(key)
        if action is None:
            return
        subtitle = str(fetch(action, "_uvr_base_subtitle", "") or "")
        status = str(fetch(action, "_uvr_size", "") or "")
        suffix = fetch(action, "_uvr_status_label", None)
        compact = getattr(self, "_compact_rows", False)
        if isinstance(suffix, Gtk.Label):
            suffix.set_label(status)
            suffix.set_visible(bool(status) and not compact)
        if status and (compact or not isinstance(suffix, Gtk.Label)):
            subtitle += f" · {status}"
        if action.get_subtitle() != subtitle:
            set_row_subtitle(action, subtitle)

    def _add_details(self, action: Adw.ActionRow, key: tuple[str, str]) -> None:
        status = Gtk.Label(valign=Gtk.Align.CENTER)
        status.add_css_class("dim-label")
        action.add_suffix(status)
        stash(action, "_uvr_status_label", status)
        button = Gtk.MenuButton(icon_name="info-outline-symbolic", valign=Gtk.Align.CENTER)
        button.add_css_class("flat")
        button.set_tooltip_text("Model details")
        button.set_create_popup_func(lambda *_: self._create_details_popup(button, key))
        action.add_suffix(button)

    def _create_details_popup(self, button: Gtk.MenuButton, key: tuple[str, str]) -> None:
        builder = load_builder("download-model-details")
        popover = object_from_builder(builder, "details", Gtk.Popover)
        label = object_from_builder(builder, "details_text", Gtk.Label)
        label.set_label(self._details_text(key))
        popover.connect("show", lambda *_: label.set_label(self._details_text(key)))
        button.set_popover(popover)

    def _details_text(self, key: tuple[str, str]) -> str:
        data = self.browser.rows.get(key)
        if data is None:
            return ""
        meta = self._catalogue_row_metadata(*key)
        files = tuple(getattr(meta, "files", {}) or {})
        architecture, source = architecture_for(
            FAMILY_BY_ARCH.get(key[0]), files, key[1], data.display
        )
        sections = [
            data.display,
            output_summary(meta),
            "Architecture: " + ARCHITECTURE_LABELS.get(architecture, "Unknown"),
        ]
        if source == "Catalogue name":
            sections.append("Architecture identified from the catalogue name.")
        for text in (data.reason, catalogue_evidence_detail(meta)):
            if text and text not in sections:
                sections.append(text)
        scores = sdr_for_files(files, load_model_scores(allow_network=False))
        if scores:
            sections.append(
                "Reported SDR\n"
                + "\n".join(f"{name}: {value:.2f} dB" for name, value in scores.items())
            )
        if files:
            sections.append("Files\n" + "\n".join(files))
        return "\n\n".join(sections)

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
        action = Adw.ActionRow(title_lines=1, subtitle_lines=1)
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
        self._add_details(action, key)
        self._render_row(key)
        self._list_boxes[arch].append(action)

    def _add_unsupported_row(self, arch: str, name: str, reason: str) -> None:
        key = (arch, name)
        if key in self._row_actions:
            return

        data = self._project_browser_row(arch, name, reason)
        self.browser.rows[key] = data
        display = data.display
        action = Adw.ActionRow(title_lines=1, subtitle_lines=1)
        set_row_title(action, display)
        set_row_subtitle(action, f"Unsupported — {reason}")
        action.add_css_class("dim-label")
        check = Gtk.CheckButton(sensitive=False, valign=Gtk.Align.CENTER)
        action.add_prefix(check)
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
        self._add_details(action, key)
        self._render_row(key)
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
            self._size_lookup_ids[key] = self._size_lookup_ids.get(key, 0) + 1
            drop(action, "_uvr_size")
            self._render_row(key)

    def _lookup_row_size(self, key: tuple[str, str]) -> None:
        arch, name = key
        action = self._row_actions.get(key)
        if action is None:
            return
        stash(action, "_uvr_size", "Looking up size…")
        self._render_row(key)
        generation = self.browser.generation
        lookup_id = self._size_lookup_ids.get(key, 0) + 1
        self._size_lookup_ids[key] = lookup_id
        jobs_obj = self._resolve_pinned(name, arch)
        jobs: list[tuple[str, str]] = (
            [(str(url), str(path)) for url, path in jobs_obj]
            if isinstance(jobs_obj, (list, tuple))
            else []
        )
        stash(action, "_uvr_size_jobs", jobs)
        self._update_download_button()
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

    def _apply_row_size(
        self, lookup_id: int, key: tuple[str, str], text: str, generation: int
    ) -> None:
        if self._lifetime.disposed:
            return
        # Guard is keyed per-row: checking another model must not discard this
        # row's own in-flight lookup result.
        if generation != self.browser.generation or self._size_lookup_ids.get(key) != lookup_id:
            return
        action = self._row_actions.get(key)
        if action is not None and key in self.browser.selected_keys():
            stash(action, "_uvr_size", text or "Download size unavailable")
            self._render_row(key)
            self._update_download_button()

    def _selected_entries(self) -> list[tuple[str, str]]:
        return [(name, arch) for arch, name in self.browser.selected_keys()]

    def _selected_count_by_purpose(self) -> dict[str, int]:
        self._refresh_browser_metadata()
        return self.browser.selected_counts()

    def _update_tab_badges(self) -> None:
        if not hasattr(self, "_purpose_badges"):
            return
        selected = self._selected_count_by_purpose()
        labels = []
        for value, label in PURPOSE_PAGE_OPTIONS:
            count = selected.get(value, 0)
            badge = self._purpose_badges[value]
            badge.set_label(str(count))
            badge.set_visible(count > 0)
            text = f"{label} ({count} selected)" if count else label
            description = PURPOSE_DESCRIPTIONS[value]
            if count:
                description += f"\n{count} selected"
            self._purpose_buttons[value].set_tooltip_text(description)
            labels.append(text)
        model = self.compact_purpose.get_model()
        if isinstance(model, Gtk.StringList) and labels != [
            model.get_string(i) for i in range(model.get_n_items())
        ]:
            self._syncing_purpose = True
            try:
                index = self.compact_purpose.get_selected()
                model.splice(0, model.get_n_items(), labels)
                self.compact_purpose.set_selected(index)
            finally:
                self._syncing_purpose = False

    def _filter_archs(self) -> list[str]:
        families = {family: arch for arch, family in FAMILY_BY_ARCH.items()}
        if self._arch_filter in families:
            return [families[self._arch_filter]]
        if self._arch_filter in families.values():
            return [self._arch_filter]
        return [arch for _, arch in _NETWORKS]

    def _update_download_button(self) -> None:
        selected = self.browser.selected_keys()
        self.download_button.set_label("Download")
        self.download_button.set_sensitive(bool(selected) and not self._refreshing)
        visible = {key for key, data in self.browser.rows.items() if self._matches(data)}
        if hasattr(self, "selection_summary"):
            self.selection_summary.set_visible_child_name("selected" if selected else "empty")
            self.clear_button.set_visible(bool(selected))
            hidden = sum(key not in visible for key in selected)
            text = f"{len(selected)} selected" + (
                f" · {hidden} outside this view" if hidden else ""
            )
            self.selection_label.set_label(text)
            self.selection_label.set_tooltip_text(text)
            from core.download_sizes import describe_cached_download_size

            jobs = []
            complete = True
            for key in selected:
                resolved = fetch(self._row_actions.get(key), "_uvr_size_jobs", None)
                if resolved is None:
                    complete = False
                else:
                    jobs.extend(resolved)
            text = (
                describe_cached_download_size(list(dict.fromkeys(jobs)))
                if complete and jobs
                else "Size unknown"
            )
            self.sizes_label.set_label(
                "Download size unavailable" if text == "Size unknown" else text
            )
        if not self._refreshing:
            self._set_catalogue_status(f"{len(visible)} models shown")
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
            if is_online:
                # Row rendering may have seeded the cache from the bundled fallback.
                # An explicit online refresh updates benchmarks off the GTK thread.
                load_model_scores(force=True)
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
        self._lifetime.own(
            lambda: self.manager.unsubscribe_catalogue_changed(self._schedule_catalogue_row_refresh)
        )
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
        if self.browser.rows:
            return [
                (family, key[1])
                for key, row in self.browser.rows.items()
                if row.reason is None
                and self._matches(row)
                and (family := FAMILY_BY_ARCH.get(key[0])) is not None
            ]
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
        for key in self._row_actions:
            if key[1] in updated:
                data = self._project_browser_row(*key, self.browser.rows[key].reason)
                self.browser.rows[key] = data
                self._render_row(key)
        self._invalidate_all_filters()
        self._invalidate_all_sorts()
        return False

    def _available_count(self) -> int:
        return self.browser.available_count()

    def _unsupported_count(self, *, visible_only: bool = False) -> int:
        return self.browser.unsupported_count(hide=visible_only and self._hide_unsupported)

    def _update_status_from_catalogue(self) -> None:
        if not self._refreshing:
            shown = sum(self._matches(data) for data in self.browser.rows.values())
            self._set_catalogue_status(f"{shown} models shown")

    def _set_catalogue_status(self, message: str) -> None:
        notice = getattr(self, "_catalogue_notice", "")
        self.status_label.set_label(f"{notice}{message}")
        self.status_label.set_tooltip_text(f"{notice}{message}")

    def _update_tab_counts(self) -> None:
        search = getattr(self, "_search_entry", None)
        if search is not None:
            index = next(
                (i for i, (value, _) in enumerate(PURPOSE_PAGE_OPTIONS) if value == self._purpose),
                0,
            )
            search.set_placeholder_text(SEARCH_LABELS[index])

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
        if page is None:
            return
        if hasattr(self, "results"):
            self.results.set_visible_child_name("empty" if title else "models")
        page.set_visible(bool(title))
        if not title:
            return
        page.set_title(title)
        page.set_description(description or None)
        page.set_icon_name("network-offline-symbolic" if offline else "edit-find-symbolic")
        child = page.get_child()
        if isinstance(child, Gtk.Button):
            child.set_visible(True)
            child.set_label("Try Again" if offline else "Reset Search and Filters")

    def _update_catalogue_page_state(self, arch: str | None = None) -> None:
        self._refresh_browser_metadata()
        any_visible = any(self._matches(data) for data in self.browser.rows.values())
        offline = not self.browser.rows and not self._catalogue_online
        self._set_catalogue_page_message(
            arch or next(iter(self._empty_pages), ""),
            "" if any_visible else ("Catalogue unavailable" if offline else "No Models Found"),
            description="Check your connection and try again."
            if offline
            else "Try a different search or reset the filters.",
            offline=offline,
        )

    def _matching_count(self, arch: str, query: str) -> int:
        self._refresh_browser_metadata()
        return self._live_catalogue_counts(self._browser_filters(query)).matching_count(arch)

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
