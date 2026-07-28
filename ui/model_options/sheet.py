"""Floating model-options sheet (``Adw.Dialog``) with per-architecture tabs."""

from __future__ import annotations

from typing import Dict, Optional, Sequence

from gi.repository import Adw, Gtk

from ..dialogs.utils import configure_dialog_width, parent_window_width, present_modal_dialog
from ..spacing import inset_md
from ..widgets.columns import build_columns_box, set_columns_narrow
from .applicability import (
    OPEN_CONTEXT_AUDIO_TOOLS,
    OPEN_CONTEXT_ENSEMBLE,
    applicable_stack_names,
    applicability_subtitle,
    default_stack_name,
    ensemble_context_banner,
    should_hide_unused_stacks,
)

_SHEET_WIDE_WIDTH = 900
_SHEET_WIDE_HEIGHT = 560
# Match the main window’s wide/narrow breakpoint (880sp) closely in pixels.
# This keeps the sheet’s column flip aligned with the rest of the UI.
_NARROW_BREAKPOINT = 880


class ModelOptionsSheet:
    """Tabbed dialog surfacing each method view's advanced and extra-model groups."""

    def __init__(
        self,
        parent: Gtk.Window,
        *,
        views: Sequence,
        views_by_stack: Dict[str, object],
        settings,
    ):
        self._parent = parent
        self._views = list(views)
        self._views_by_stack = views_by_stack
        self._settings = settings
        self._context = ""
        self._active_method_key = ""
        self._selected_models: list[str] = []
        self._tab_columns: Dict[str, Gtk.Box] = {}
        self._tab_pages: Dict[str, Gtk.Widget] = {}
        self._tab_stack_pages: Dict[str, Adw.ViewStackPage] = {}
        self._tab_subtitles: Dict[str, Gtk.Label] = {}
        self._last_parent_width: int = 0
        self._surface_handler: int = 0
        self._parent_map_handler: int = 0

        self.dialog = Adw.Dialog()
        self.dialog.set_title("Model options")
        # Initial desktop size (will be re-synced to parent on present()).
        self.dialog.set_content_width(_SHEET_WIDE_WIDTH)
        self.dialog.set_content_height(_SHEET_WIDE_HEIGHT)
        self.dialog.set_follows_content_size(False)
        self.dialog.connect("closed", self._on_closed)
        self.dialog.connect("notify::content-width", self._sync_narrow_layout)

        self._ensemble_banner = Gtk.Label(wrap=True, xalign=0.0)
        self._ensemble_banner.add_css_class("dim-label")
        self._ensemble_banner.set_visible(False)

        self._stack = Adw.ViewStack()
        if hasattr(Adw, "InlineViewSwitcher"):
            self._switcher = Adw.InlineViewSwitcher()
            self._switcher.set_stack(self._stack)
            self._switcher.set_display_mode(Adw.InlineViewSwitcherDisplayMode.LABELS)
            self._switcher.set_homogeneous(True)
        else:
            self._switcher = Adw.ViewSwitcher()
            self._switcher.set_stack(self._stack)
            self._switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        self._stack.connect("notify::visible-child-name", self._on_tab_changed)

        for view in self._views:
            page = self._build_tab_page(view)
            stack_page = self._stack.add_titled(page, view.stack_name, view.title)
            self._tab_stack_pages[view.stack_name] = stack_page

        # Header: left-aligned title + centered tab switcher (like Download Center).
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(self._switcher)
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inset_md(body)
        body.append(self._ensemble_banner)
        body.append(self._stack)
        toolbar.set_content(body)
        self.dialog.set_child(toolbar)

    def _build_tab_page(self, view) -> Gtk.Widget:
        subtitle = Gtk.Label(xalign=0.0, wrap=True)
        subtitle.add_css_class("dim-label")
        self._tab_subtitles[view.stack_name] = subtitle

        columns_box, col_start, col_end = build_columns_box()
        self._tab_columns[view.stack_name] = columns_box

        if view.advanced_group.get_parent() is not None:
            view.advanced_group.get_parent().remove(view.advanced_group)
        view.advanced_group.set_title("Inference")
        view.advanced_group.set_description(
            "Advanced processing options for this architecture"
        )
        col_start.append(view.advanced_group)

        if view.secondary_group.get_parent() is not None:
            view.secondary_group.get_parent().remove(view.secondary_group)
        col_end.append(view.secondary_group)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        scroller.set_child(columns_box)

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page_box.set_vexpand(True)
        page_box.append(subtitle)
        page_box.append(scroller)
        self._tab_pages[view.stack_name] = page_box
        return page_box

    def _sync_narrow_layout(self, *_args) -> None:
        # Drive stacking off actual allocated content width (not the initial
        # requested width), so the sheet adapts as the parent/window shrinks.
        width = self.dialog.get_content_width()
        if width <= 0:
            width = self._parent.get_width() if self._parent is not None else 0
        narrow = width > 0 and width < _NARROW_BREAKPOINT
        for columns_box in self._tab_columns.values():
            set_columns_narrow(columns_box, narrow)

    def _sync_from_parent_width(self, *_args) -> None:
        """Resize the sheet when the parent window's allocated width changes."""
        width = parent_window_width(self._parent, fallback=_SHEET_WIDE_WIDTH)
        if width <= 0 or width == self._last_parent_width:
            return
        self._last_parent_width = width
        self.dialog.set_content_width(width)
        self._sync_narrow_layout()

    def _start_width_tracking(self) -> None:
        """Track parent surface width instead of a fixed 200ms poll."""
        self._stop_width_tracking()
        self._sync_from_parent_width()
        if self._parent is None:
            return

        def attach_surface(*_args) -> None:
            surface = self._parent.get_surface()
            if surface is None or self._surface_handler:
                return
            self._surface_handler = surface.connect(
                "notify::width", self._sync_from_parent_width
            )

        if self._parent.get_mapped():
            attach_surface()
        else:
            self._parent_map_handler = self._parent.connect("map", attach_surface)

    def _stop_width_tracking(self) -> None:
        if self._surface_handler and self._parent is not None:
            surface = self._parent.get_surface()
            if surface is not None:
                try:
                    surface.disconnect(self._surface_handler)
                except TypeError:
                    pass
            self._surface_handler = 0
        if self._parent_map_handler and self._parent is not None:
            try:
                self._parent.disconnect(self._parent_map_handler)
            except TypeError:
                pass
            self._parent_map_handler = 0

    def _on_tab_changed(self, *_args) -> None:
        self._refresh_applicability()

    def update_context(
        self,
        *,
        context: str,
        active_method_key: str,
        selected_models: Sequence[str],
        initial_stack: Optional[str] = None,
    ) -> None:
        self._context = context
        self._active_method_key = active_method_key
        self._selected_models = list(selected_models or [])

        for view in self._views:
            view.sync_dynamic_option_state()

        banner_text = ensemble_context_banner(context)
        if banner_text:
            self._ensemble_banner.set_label(banner_text)
            self._ensemble_banner.set_visible(True)
        else:
            self._ensemble_banner.set_visible(False)

        start_stack = initial_stack or default_stack_name(
            context,
            active_method_key=active_method_key,
            selected_models=selected_models,
            views_by_stack=self._views_by_stack,
        )
        # Select the target tab while every page is still visible. Hiding the
        # current ViewStack child first can leave the stack blank.
        for stack_page in self._tab_stack_pages.values():
            stack_page.set_visible(True)
        if start_stack in self._views_by_stack:
            self._stack.set_visible_child_name(start_stack)
        self._refresh_applicability()
        self._sync_narrow_layout()

    def _refresh_applicability(self) -> None:
        applicable = applicable_stack_names(
            self._context,
            active_method_key=self._active_method_key,
            selected_models=self._selected_models,
        )
        empty_ensemble = (
            self._context == OPEN_CONTEXT_ENSEMBLE and not applicable
        )
        if empty_ensemble:
            self._ensemble_banner.set_label(
                "Select ensemble member models before editing "
                "architecture-specific options."
            )
            self._ensemble_banner.set_visible(True)
        elif self._context == OPEN_CONTEXT_ENSEMBLE:
            self._ensemble_banner.set_label(
                ensemble_context_banner(self._context) or ""
            )
            self._ensemble_banner.set_visible(True)
        # Separation: keep every architecture tab visible so options are never
        # wiped by hiding the active ViewStack child. Ensemble: hide arches
        # that no selected member uses (still show all when the list is empty).
        hide_unused = should_hide_unused_stacks(self._context, applicable)
        for stack_name, page in self._tab_pages.items():
            is_applicable = stack_name in applicable
            subtitle = applicability_subtitle(
                self._context,
                stack_name,
                active_method_key=self._active_method_key,
                selected_models=self._selected_models,
            )
            self._tab_subtitles[stack_name].set_label(subtitle)
            stack_page = self._tab_stack_pages.get(stack_name)
            if stack_page is not None:
                stack_page.set_visible(is_applicable if hide_unused else True)
            # Separation keeps non-active arches editable for pre-config; the
            # tab subtitle communicates that those values are unused.
            # Empty ensemble dims everything until members are chosen.
            if empty_ensemble:
                page.set_sensitive(False)
            elif hide_unused:
                page.set_sensitive(is_applicable)
            else:
                page.set_sensitive(True)
            page.set_opacity(1.0)

    def _on_closed(self, *_args) -> None:
        self._stop_width_tracking()

    def present(
        self,
        *,
        context: str,
        active_method_key: str,
        selected_models: Sequence[str],
        initial_stack: Optional[str] = None,
    ) -> None:
        configure_dialog_width(self.dialog, self._parent, fallback=_SHEET_WIDE_WIDTH)
        self._start_width_tracking()
        self.update_context(
            context=context,
            active_method_key=active_method_key,
            selected_models=selected_models,
            initial_stack=initial_stack,
        )
        present_modal_dialog(self.dialog, self._parent)


def open_model_options_sheet(
    parent: Gtk.Window,
    *,
    views: Sequence,
    views_by_stack: Dict[str, object],
    settings,
    context: str,
    active_method_key: str,
    selected_models: Sequence[str],
    initial_stack: Optional[str] = None,
    existing: Optional[ModelOptionsSheet] = None,
) -> ModelOptionsSheet:
    if context == OPEN_CONTEXT_AUDIO_TOOLS:
        return existing  # type: ignore[return-value]

    sheet = existing
    if sheet is None:
        sheet = ModelOptionsSheet(
            parent,
            views=views,
            views_by_stack=views_by_stack,
            settings=settings,
        )
    sheet.present(
        context=context,
        active_method_key=active_method_key,
        selected_models=selected_models,
        initial_stack=initial_stack,
    )
    return sheet
