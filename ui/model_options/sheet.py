"""Floating model-options sheet (``Adw.Dialog``) with per-architecture tabs."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence

from gi.repository import Adw, GLib, Gtk

from ..dialogs.utils import configure_dialog_width, parent_window_width, present_modal_dialog
from ..spacing import inset_md
from ..widgets.columns import build_columns_box, set_columns_narrow
from .applicability import (
    OPEN_CONTEXT_AUDIO_TOOLS,
    applicable_stack_names,
    applicability_subtitle,
    default_stack_name,
    ensemble_context_banner,
    non_applicable_toast,
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
        on_toast: Callable[[str], None],
    ):
        self._parent = parent
        self._views = list(views)
        self._views_by_stack = views_by_stack
        self._settings = settings
        self._on_toast = on_toast
        self._context = ""
        self._active_method_key = ""
        self._selected_models: list[str] = []
        self._toast_shown: set[str] = set()
        self._settings_wrappers: Dict[object, Callable[[], None]] = {}
        self._tab_columns: Dict[str, Gtk.Box] = {}
        self._tab_pages: Dict[str, Gtk.Widget] = {}
        self._tab_subtitles: Dict[str, Gtk.Label] = {}
        self._last_parent_width: int = 0
        self._resize_poll_source: int = 0

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
            self._stack.add_titled(page, view.stack_name, view.title)
            self._wrap_settings_callback(view)

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

    def _poll_parent_width(self) -> bool:
        """Poll parent width to keep the sheet responsive (GTK4 has no size-allocate signal)."""
        width = parent_window_width(self._parent, fallback=_SHEET_WIDE_WIDTH)
        if width > 0 and width != self._last_parent_width:
            self._last_parent_width = width
            self.dialog.set_content_width(width)
            self._sync_narrow_layout()
        return True

    def _wrap_settings_callback(self, view) -> None:
        if view in self._settings_wrappers:
            return
        original = view._on_settings_changed

        def wrapped() -> None:
            self._maybe_toast_non_applicable(view.stack_name)
            original()

        self._settings_wrappers[view] = original
        view._on_settings_changed = wrapped

    def _restore_settings_callback(self, view) -> None:
        original = self._settings_wrappers.pop(view, None)
        if original is not None:
            view._on_settings_changed = original

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
        self._toast_shown.clear()

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
        for stack_name, page in self._tab_pages.items():
            subtitle = applicability_subtitle(
                self._context,
                stack_name,
                active_method_key=self._active_method_key,
                selected_models=self._selected_models,
            )
            self._tab_subtitles[stack_name].set_label(subtitle)
            page.set_opacity(1.0 if stack_name in applicable else 0.55)

    def _maybe_toast_non_applicable(self, stack_name: str) -> None:
        if stack_name in self._toast_shown:
            return
        message = non_applicable_toast(
            self._context,
            stack_name,
            active_method_key=self._active_method_key,
            selected_models=self._selected_models,
        )
        if message:
            self._toast_shown.add(stack_name)
            self._on_toast(message)

    def _on_closed(self, *_args) -> None:
        if self._resize_poll_source:
            GLib.source_remove(self._resize_poll_source)
            self._resize_poll_source = 0

    def present(
        self,
        *,
        context: str,
        active_method_key: str,
        selected_models: Sequence[str],
        initial_stack: Optional[str] = None,
    ) -> None:
        configure_dialog_width(self.dialog, self._parent, fallback=_SHEET_WIDE_WIDTH)
        if not self._resize_poll_source:
            # Keep it lightweight; only needed while the dialog is open.
            self._resize_poll_source = GLib.timeout_add(200, self._poll_parent_width)
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
    on_toast: Callable[[str], None],
    context: str,
    active_method_key: str,
    selected_models: Sequence[str],
    initial_stack: Optional[str] = None,
    existing: Optional[ModelOptionsSheet] = None,
) -> ModelOptionsSheet:
    if context == OPEN_CONTEXT_AUDIO_TOOLS:
        on_toast("Model options apply to Separation and Ensemble runs.")
        return existing  # type: ignore[return-value]

    sheet = existing
    if sheet is None:
        sheet = ModelOptionsSheet(
            parent,
            views=views,
            views_by_stack=views_by_stack,
            settings=settings,
            on_toast=on_toast,
        )
    sheet.present(
        context=context,
        active_method_key=active_method_key,
        selected_models=selected_models,
        initial_stack=initial_stack,
    )
    return sheet
