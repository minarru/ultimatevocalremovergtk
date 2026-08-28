"""Download Center window — catalogue browser and download queue."""

from __future__ import annotations

import os
import threading
import typing

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
from core.model_catalogue import (
    catalogue_entry_meta,
    catalogue_label_matches,
    filter_catalogue_labels,
    project_catalogue_display,
)
from core.model_identity import FAMILY_BY_ARCH
from core.model_naming import canonical_display_name
from core.model_scores import (
    PURPOSE_ALL,
    PURPOSE_FILTER_OPTIONS,
    SORT_NAME,
    SORT_OPTIONS,
    SORT_SDR,
    format_sdr_subtitle,
    parse_sdr_score,
    primary_sdr,
    purpose_for_label,
    sdr_for_files,
)

from .dialogs.utils import close_on_escape
from .dispatch import idle_on_main
from .hints import set_icon_button_a11y, set_tooltip
from .markup import set_row_subtitle, set_row_title
from .spacing import set_inset
from .widget_state import drop, fetch, stash
from .widgets.rows import get_combo_value, make_combo_row, set_combo_value

_NETWORKS = [
    ("VR Arch", VR_ARCH_TYPE),
    ("MDX-Net", MDX_ARCH_TYPE),
    ("Demucs", DEMUCS_ARCH_TYPE),
    # Apollo models are restoration (Audio Tools), not separation networks, but
    # they share the catalogue/queue plumbing so they get their own tab.
    ("Apollo", APOLLO_ARCH_TYPE),
]

_CLAMP_MAX_WIDTH = 800


def catalogue_semantics_subtitle(meta: typing.Any) -> str:
    """Render reviewed route labels, or an explicit raw-output fallback."""
    projection = getattr(meta, "stem_semantics", None)
    routes = tuple(getattr(projection, "routes", ()) or ())
    evidence = getattr(meta, "catalogue_evidence_status", "unavailable")
    evidence_value = str(getattr(evidence, "value", evidence) or "")
    if evidence_value == "not_applicable":
        return "Restoration · output details not applicable"
    if (
        getattr(projection, "status", "raw") == "reviewed"
        and routes
        and evidence_value in {"ready", "stale"}
    ):
        ordered = sorted(routes, key=lambda route: not route.logical_primary)
        stems = ", ".join(route.display for route in ordered)
        intent = str(getattr(meta, "intent", "") or "")
        purpose_bucket = purpose_for_label(
            str(getattr(meta, "label", "") or ""),
            intent=intent,
        )
        purpose = next(
            (label for value, label in PURPOSE_FILTER_OPTIONS if value == purpose_bucket),
            "Reviewed",
        )
        return f"{purpose} · {stems}"
    if evidence_value == "pending":
        return "Loading output details…"
    files = getattr(meta, "files", {}) or {}
    has_config = any(str(name).casefold().endswith((".yaml", ".yml")) for name in files)
    if evidence_value == "unavailable" and has_config:
        return "Output details unavailable"
    stems = ", ".join(str(stem) for stem in (getattr(meta, "stems", ()) or ()))
    return f"Raw outputs · {stems}" if stems else "Raw outputs"


def catalogue_evidence_detail(meta: typing.Any) -> str:
    """Return non-destructive evidence detail for a row tooltip."""
    return str(getattr(meta, "catalogue_evidence_warning", "") or "")


def catalogue_matches(
    names: list[str],
    query: str,
    *,
    purpose: str = PURPOSE_ALL,
    intents: typing.Mapping[str, str] | None = None,
) -> list[str]:
    """Return selectable catalogue names matching query and purpose filter.

    Matching covers both the raw catalogue label and its canonical rendering,
    so a user typing what the row *shows* finds it.
    """
    return filter_catalogue_labels(
        names,
        query,
        purpose=purpose,
        intents=dict(intents or {}),
        sentinels=(NO_NEW_MODELS, NO_CONNECTION),
    )


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

        self._available: dict[str, list[str]] = {}
        self._unsupported: dict[str, list[tuple[str, str]]] = {}
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
        self._purpose = PURPOSE_ALL
        self._sort_mode = SORT_NAME
        self._hide_unsupported = False
        self._stem_refresh_armed = False
        self._stem_fetch_armed = False
        self._catalogue_refresh_armed = False
        self._downloads_dirty = False
        self._pinned_revision = None
        self._pinned_snapshot = None
        self._pending_source_delta = False

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
        if self._pending_source_delta:
            self._pending_source_delta = False
            self.start_refresh()
            return
        if self._downloads_dirty and self._available:
            self._apply_download_completion_refresh()
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

        menu = Gio.Menu()
        menu.append("Open models folder", "dc.open-models")
        menu.append("Manual downloads", "dc.manual")
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        set_icon_button_a11y(menu_button, "Models and manual downloads")
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
        intent = self._catalogue_intent(arch, label)
        if (
            self._purpose != PURPOSE_ALL
            and purpose_for_label(label, intent=intent) != self._purpose
        ):
            return False
        search = self._search_entries.get(arch)
        if search is None:
            return True
        query = search.get_text().strip().casefold()
        reason = fetch(action, "_uvr_unsupported_reason", "")
        display = fetch(action, "_uvr_display_name", "")
        return catalogue_label_matches(str(label), query, extra=f"{display} {reason}".strip())

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
        self._schedule_stem_yaml_fetches()

    def _on_purpose_changed(self, *_args: typing.Any) -> None:
        label = get_combo_value(self.purpose_row) or PURPOSE_FILTER_OPTIONS[0][1]
        self._purpose = next(
            (value for value, text in PURPOSE_FILTER_OPTIONS if text == label),
            PURPOSE_ALL,
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

    def _invalidate_all_filters(self) -> None:
        for arch, list_box in self._list_boxes.items():
            list_box.invalidate_filter()
            self._update_catalogue_page_state(arch)
        self._update_download_button()

    def _on_catalogue_tab_changed(self, *_args: typing.Any) -> None:
        self._update_download_button()

    def _catalogue_row_metadata(self, arch: str, name: str) -> typing.Any:
        """Resolve one row without flattening equal labels across families."""
        family = FAMILY_BY_ARCH.get(arch)
        scoped = getattr(self.manager, "catalogue_meta_by_family", {})
        if family is not None:
            family_metadata = scoped.get(family, {})
            if name in family_metadata:
                return family_metadata[name]
        return getattr(self.manager, "catalogue_meta", {}).get(name)

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

        stem, sdr, stems_text = self._row_score(arch, name)

        display = self._catalogue_display(arch, name)
        action = Adw.ActionRow()
        set_row_title(action, display)
        action.add_prefix(check)
        action.set_activatable_widget(check)
        # Identity stays the raw catalogue label: resolve()/download() key on it.
        stash(action, "_uvr_model_name", name)
        stash(action, "_uvr_display_name", display)
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

        display = self._catalogue_display(arch, name)
        action = Adw.ActionRow()
        set_row_title(action, display)
        set_row_subtitle(action, f"Unsupported — {reason}")
        action.add_css_class("dim-label")
        action.set_sensitive(False)
        stash(action, "_uvr_model_name", name)
        stash(action, "_uvr_display_name", display)
        stash(action, "_uvr_unsupported", True)
        stash(action, "_uvr_unsupported_reason", reason)
        stash(action, "_uvr_sdr", parse_sdr_score(name))
        stash(action, "_uvr_sdr_stem", None)
        stash(action, "_uvr_stems_text", "")
        stash(action, "_uvr_sort_name", display.casefold())

        self._row_actions[key] = action
        self._list_boxes[arch].append(action)

    def _catalogue_display(self, arch: str, selection: str) -> str:
        family = FAMILY_BY_ARCH.get(arch)
        if family is None:
            return canonical_display_name(selection)
        catalogue = getattr(self.manager, f"{family}_download_list", {})
        raw = catalogue.get(selection) if isinstance(catalogue, dict) else None
        meta = catalogue_entry_meta(self.manager, family, selection)
        return project_catalogue_display(family, selection, raw, meta)

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
                idle_on_main(self._apply_row_size, lookup_id, key, text)

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
                idle_on_main(self._apply_row_size, lookup_id, key, text)

        for url in pending:
            request_url_size(url, on_url)

    def _apply_row_size(self, lookup_id: int, key: tuple[str, str], text: str) -> None:
        # Guard is keyed per-row: checking another model must not discard this
        # row's own in-flight lookup result.
        if self._size_lookup_ids.get(key) != lookup_id:
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
            if active_arch and (query or self._purpose != PURPOSE_ALL):
                network_label = next(
                    (label for label, arch in _NETWORKS if arch == active_arch),
                    "current network",
                )
                shown = self._matching_count(active_arch, query)
                if query:
                    message = (
                        f"{shown} match{'es' if shown != 1 else ''} for “{query}” "
                        f"in {network_label}"
                    )
                else:
                    purpose_label = next(
                        (
                            label
                            for value, label in PURPOSE_FILTER_OPTIONS
                            if value == self._purpose
                        ),
                        "selected purpose",
                    )
                    message = (
                        f"{shown} {purpose_label.casefold()} "
                        f"model{'s' if shown != 1 else ''} in {network_label}"
                    )
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
        except Exception as exc:  # noqa: BLE001 - surfaced through the UI/log
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
        self._finish_refresh_controls()
        self._catalogue_online = False
        if self._available:
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
        self._finish_refresh_controls()
        self._catalogue_online = is_online
        if not is_online and not available and not self._available:
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
            self._available = available
            self._unsupported = unsupported or {}
        self._catalogue_notice = "" if is_online else "Offline — showing saved catalogue · "
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
        self._ensure_background_listeners()
        self._pin_current_snapshot()
        self._schedule_stem_yaml_fetches()

    def _pin_current_snapshot(self) -> None:
        manager = getattr(self, "manager", None)
        coordinator = getattr(manager, "_coordinator", None) if manager is not None else None
        snapshot = getattr(coordinator, "_latest", None) if coordinator is not None else None
        self._pinned_snapshot = snapshot
        revision = getattr(snapshot, "revision", None)
        digest = getattr(revision, "digest", None)
        self._pinned_revision = digest() if callable(digest) else None

    def _pinned_catalogue(self, arch: str) -> dict | None:
        snapshot = getattr(self, "_pinned_snapshot", None)
        if snapshot is None:
            return None
        mapping = {
            VR_ARCH_TYPE: snapshot.vr,
            MDX_ARCH_TYPE: snapshot.mdx,
            DEMUCS_ARCH_TYPE: snapshot.demucs,
            APOLLO_ARCH_TYPE: snapshot.apollo,
        }
        catalogue = mapping.get(arch)
        return dict(catalogue) if catalogue is not None else None

    def _resolve_pinned(self, selection: str, arch: str) -> typing.Any:
        catalogue = self._pinned_catalogue(arch)
        return self.manager.resolve(selection, arch, catalogue=catalogue)

    def _ensure_background_listeners(self) -> None:
        """Listen for both background catalogue refinements.

        Stem YAML fetches rewrite subtitles; the size warmup's identity HEADs
        can drop whole rows. Both land after the list has rendered, and both
        notify from a worker thread.
        """
        from core.catalogue_stem_cache import ensure_worker_started, subscribe

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
        self._pending_source_delta = True

    def _schedule_catalogue_row_refresh(self) -> None:
        idle_on_main(self._arm_catalogue_row_refresh)

    def _arm_catalogue_row_refresh(self) -> None:
        if self._catalogue_refresh_armed:
            return
        self._catalogue_refresh_armed = True
        from gi.repository import GLib

        GLib.timeout_add(250, self._flush_catalogue_row_refresh)

    def _flush_catalogue_row_refresh(self) -> bool:
        """Drop rows the content dedupe removed, leaving the rest alone.

        Deliberately not ``_rebuild_catalogue``: this fires while the user is
        browsing, and a rebuild clears every list box — resetting scroll
        position and recreating ~500 rows to delete a handful. Dedupe only ever
        removes, so removal is the whole contract.
        """
        self._catalogue_refresh_armed = False
        self._available = self.manager.available_downloads()
        self._unsupported = self.manager.unsupported_downloads()

        live: set[tuple[str, str]] = set()
        for arch, names in self._available.items():
            for name in names:
                live.add((arch, name))
        for arch, rows in self._unsupported.items():
            for name, _reason in rows:
                live.add((arch, name))

        gone = [key for key in self._row_actions if key not in live]
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
        active = self.stack.get_visible_child_name()
        if active is not None and active in self._available:
            archs = [active]
        else:
            archs = list(self._available)
        entries: list[tuple[str, str]] = []
        for arch in archs:
            family = FAMILY_BY_ARCH.get(arch)
            if family is None:
                continue
            intents = self._catalogue_intents(family)
            query = ""
            entry = self._search_entries.get(arch)
            if entry is not None:
                query = entry.get_text() or ""
            entries.extend(
                (family, label)
                for label in catalogue_matches(
                    list(self._available.get(arch) or []),
                    query,
                    purpose=self._purpose,
                    intents=intents,
                )
            )
        return entries

    def _all_catalogue_entries(self) -> list[tuple[str, str]]:
        """Return all current rows as family-scoped canonical selections."""
        return [
            (family, label)
            for arch, labels in self._available.items()
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

    def _catalogue_intent(self, arch: str, label: str) -> str | None:
        manager = getattr(self, "manager", None)
        scoped = getattr(manager, "catalogue_meta_by_family", {})
        family = FAMILY_BY_ARCH.get(arch)
        metadata = scoped.get(family, {}) if isinstance(scoped, dict) and family else {}
        meta = metadata.get(label)
        return meta.intent if meta is not None else None

    def _pending_stem_yaml_urls(self, labels: list[str] | None = None) -> list[str]:
        """YAML URLs still missing from the stem cache for ``labels`` (or all)."""
        from core.catalog_sources import _needs_catalogue_config_evidence, _yaml_config_url
        from core.catalogue_stem_cache import catalogue_stems_enabled, lookup_stems

        if not catalogue_stems_enabled():
            return []
        if labels is None:
            metas = list(self.manager.catalogue_meta.values())
        else:
            metas = []
            for name in labels:
                meta = self.manager.catalogue_meta.get(name)
                if meta is not None:
                    metas.append(meta)
        urls: list[str] = []
        seen: set[str] = set()
        for meta in metas:
            if not _needs_catalogue_config_evidence(meta):
                continue
            url = _yaml_config_url(meta.files)
            if not url or url in seen:
                continue
            hit = lookup_stems(url)
            if hit is None or (hit.ok and not hit.content_sha256):
                seen.add(url)
                urls.append(url)
        return urls

    def _schedule_stem_yaml_fetches(self) -> None:
        """Arm a debounced rescan; a burst of typing costs one pass, not one each."""
        if self._stem_fetch_armed:
            return
        self._stem_fetch_armed = True
        from gi.repository import GLib

        GLib.timeout_add(250, self._flush_stem_yaml_fetches)

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
            arch, name = key
            if name not in updated:
                continue
            if fetch(action, "_uvr_unsupported", False):
                continue
            meta = self._catalogue_row_metadata(arch, name)
            stems_text = catalogue_semantics_subtitle(meta) if meta is not None else ""
            stash(action, "_uvr_stems_text", stems_text)
            set_tooltip(action, catalogue_evidence_detail(meta) if meta is not None else "")
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
        page.set_icon_name("network-offline-symbolic" if offline else "edit-find-symbolic")
        child = page.get_child()
        if child is not None:
            child.set_visible(offline)
        page.set_visible(True)
        if list_parent is not None:
            list_parent.set_visible(False)

    def _update_catalogue_page_state(self, arch: str) -> None:
        if self._catalogue_online is False and not self._available:
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
        matches = catalogue_matches(
            names,
            query,
            purpose=self._purpose,
            intents=self._catalogue_intents(FAMILY_BY_ARCH[arch]),
        )
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
        elif not catalogue_matches(names, "", purpose=PURPOSE_ALL) and not (
            self._unsupported.get(arch) or []
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
                if purpose_for_label(label, intent=self._catalogue_intent(arch, label))
                == self._purpose
            ]
        return [
            (label, reason)
            for label, reason in rows
            if catalogue_label_matches(label, query, extra=reason)
        ]

    def _matching_count(self, arch: str, query: str) -> int:
        supported = catalogue_matches(
            self._available.get(arch) or [],
            query,
            purpose=self._purpose,
            intents=self._catalogue_intents(FAMILY_BY_ARCH[arch]),
        )
        return len(supported) + len(self._unsupported_matches(arch, query))

    def _rebuild_catalogue(self) -> None:
        previously_selected = {(arch, name) for name, arch in self._selected_entries()}
        self._pin_current_snapshot()
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
        ids: list[str] = []
        for name, arch in entries:
            jobs = self._resolve_pinned(name, arch)
            item_id = self.queue.enqueue(name, arch, jobs=jobs)
            if item_id:
                ids.append(item_id)
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

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast.new(message))
