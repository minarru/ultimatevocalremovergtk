"""Floating model-options sheet (``Adw.Dialog``) with per-architecture tabs."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Sequence

from gi.repository import Adw, Gtk

from ..dialogs.utils import present_modal_dialog
from ..spacing import inset_md
from .applicability import (
    OPEN_CONTEXT_AUDIO_TOOLS,
    OPEN_CONTEXT_ENSEMBLE,
    applicability_banner,
    applicable_stack_names,
    default_stack_name,
    ensemble_context_banner,
    member_arch_counts,
    should_hide_unused_stacks,
)

#: The sheet is a modal options surface, not a second window: it is capped
#: rather than sized to the parent. Dropping parent-width tracking also drops
#: the sheet's two call sites into the parent-width helper in dialogs/utils.py.
_SHEET_WIDTH = 760
#: Used when the parent's allocated height is not yet known (unrealized window).
_SHEET_FALLBACK_HEIGHT = 560
#: Never take more than this share of the parent's height.
_SHEET_MAX_HEIGHT_FRACTION = 0.9
#: Below this content width the two columns stack into one.
_STACK_BREAKPOINT = 700
#: Floor below which the dialog must not be allocated. Without it libadwaita
#: warns and can size the dialog under its content's minimum, clipping rows.
_SHEET_MIN_WIDTH = 360
_SHEET_MIN_HEIGHT = 294


def _build_sheet_columns():
    """Two content-sized columns for one tab page.

    Unlike ``ui.widgets.columns.build_columns_box`` these are **not**
    homogeneous: the Inference group and the Extra models + Model maintenance
    stack have genuinely different natural widths, and forcing them equal is
    what left the MDX-Net tab showing two rows beside a column of expanders.
    """
    col_start = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=18,
        hexpand=True,
        valign=Gtk.Align.START,
    )
    col_end = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL,
        spacing=18,
        hexpand=True,
        valign=Gtk.Align.START,
    )
    columns_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
    columns_box.set_homogeneous(False)
    columns_box.set_hexpand(True)
    columns_box.append(col_start)
    columns_box.append(col_end)
    return columns_box, col_start, col_end


def _set_sheet_columns_stacked(columns_box, stacked: bool) -> None:
    """Flip a sheet columns box between stacked (narrow) and side-by-side."""
    columns_box.set_orientation(
        Gtk.Orientation.VERTICAL if stacked else Gtk.Orientation.HORIZONTAL
    )


class ModelOptionsSheet:
    """Tabbed dialog surfacing each method view's advanced and extra-model groups."""

    def __init__(
        self,
        parent: Gtk.Window,
        *,
        views: Sequence,
        views_by_stack: Dict[str, object],
        settings,
        on_switch_method: Optional[Callable[[str], None]] = None,
    ):
        self._parent = parent
        self._views = list(views)
        self._views_by_stack = views_by_stack
        self._settings = settings
        self._on_switch_method = on_switch_method
        self._context = ""
        self._active_method_key = ""
        self._selected_models: list[str] = []
        self._tab_columns: Dict[str, Gtk.Box] = {}
        self._tab_pages: Dict[str, Gtk.Widget] = {}
        self._tab_stack_pages: Dict[str, Adw.ViewStackPage] = {}
        # One banner for the whole sheet, living in the toolbar's top bars right
        # under the header rather than one per page inside the content. That is
        # the libadwaita placement for ``Adw.Banner`` -- it renders flush with
        # the dialog edges and attached to the header, instead of floating
        # inside the page's inset margins.
        self._banner = Adw.Banner()
        self._banner.set_revealed(False)
        self._banner.connect("button-clicked", self._on_banner_switch)

        self.dialog = Adw.Dialog()
        self.dialog.set_title("Model options")
        self.dialog.set_content_width(_SHEET_WIDTH)
        self.dialog.set_content_height(self._sheet_height())
        self.dialog.set_follows_content_size(False)
        # libadwaita warns ("AdwDialog does not have a minimum size") and will
        # happily allocate the dialog below its content's minimum, which clips
        # the children. Content width/height are only *preferred* sizes; these
        # are the floor. Kept small enough that the stacked single-column layout
        # below the breakpoint still fits.
        self.dialog.set_size_request(_SHEET_MIN_WIDTH, _SHEET_MIN_HEIGHT)

        # ``notify::content-width`` only fires when code calls
        # ``set_content_width`` -- it is the *requested* size, which after the
        # width-cap change nothing updates post-construction, so it never fires
        # again. An ``Adw.Breakpoint`` reacts to the dialog's real allocated
        # width instead (the same mechanism ``MainWindow`` uses for its own
        # narrow layout), so it fires whenever the parent window is actually
        # narrower than the sheet's cap.
        self._narrow_breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse(f"max-width: {_STACK_BREAKPOINT}sp")
        )
        self._narrow_breakpoint.connect("apply", self._on_narrow_breakpoint_apply)
        self._narrow_breakpoint.connect("unapply", self._on_narrow_breakpoint_unapply)
        self.dialog.add_breakpoint(self._narrow_breakpoint)

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
        toolbar.add_top_bar(self._banner)
        # The default FLAT style draws a shadow under the top bars *only while
        # the content is scrolled*. The banner's 250ms slide shrinks the viewport
        # frame by frame, so the content briefly overflows, the scroll state
        # flips, and the shadow flashes on and off under the banner -- a tearing
        # line for the duration of the reveal. A constant border removes the
        # dynamic decision, so the animation can stay.
        toolbar.set_top_bar_style(Adw.ToolbarStyle.RAISED_BORDER)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inset_md(body)
        body.append(self._stack)
        toolbar.set_content(body)
        self.dialog.set_child(toolbar)

    def _build_tab_page(self, view) -> Gtk.Widget:
        columns_box, col_start, col_end = _build_sheet_columns()
        self._tab_columns[view.stack_name] = columns_box

        if view.advanced_group.get_parent() is not None:
            view.advanced_group.get_parent().remove(view.advanced_group)
        view.advanced_group.set_title("Inference")
        view.advanced_group.set_description(
            "Advanced processing options for this architecture"
        )
        col_start.append(view.advanced_group)

        for group in (view.secondary_group, view.maintenance_group):
            if group.get_parent() is not None:
                group.get_parent().remove(group)
            col_end.append(group)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        scroller.set_child(columns_box)

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page_box.set_vexpand(True)
        page_box.append(scroller)
        self._tab_pages[view.stack_name] = page_box
        return page_box

    def _sheet_height(self) -> int:
        """Content height: follow the content, bounded by the parent's height.

        An ``Adw.Dialog`` cannot exceed its parent window, so the parent's
        allocated height is the real ceiling. Before the parent is realized
        ``get_height()`` returns 0 and the fallback applies.
        """
        parent_height = self._parent.get_height() if self._parent is not None else 0
        if parent_height <= 1:
            return _SHEET_FALLBACK_HEIGHT
        return int(parent_height * _SHEET_MAX_HEIGHT_FRACTION)

    def _on_narrow_breakpoint_apply(self, *_args) -> None:
        for columns_box in self._tab_columns.values():
            _set_sheet_columns_stacked(columns_box, True)

    def _on_narrow_breakpoint_unapply(self, *_args) -> None:
        for columns_box in self._tab_columns.values():
            _set_sheet_columns_stacked(columns_box, False)

    def _on_tab_changed(self, *_args) -> None:
        self._refresh_applicability()

    def _on_banner_switch(self, *_args) -> None:
        """Hand the architecture switch back to the window, then re-read state.

        The banner belongs to the sheet rather than to a page, so the target
        architecture is whichever tab is on screen -- that is the one the banner
        is describing.

        The sheet cannot switch methods itself: a correct switch also updates
        the main page's method combo and rebuilds its columns. The window owns
        both, so it does the work and the sheet just refreshes in place -- it
        deliberately does not close, so the user can keep editing.
        """
        if self._on_switch_method is None:
            return
        stack_name = self._stack.get_visible_child_name()
        if stack_name is None:
            return
        self._on_switch_method(stack_name)
        view = self._views_by_stack.get(stack_name)
        self.update_context(
            context=self._context,
            active_method_key=getattr(view, "method_key", self._active_method_key),
            selected_models=self._selected_models,
            initial_stack=stack_name,
        )

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

        # The standing ensemble explanation is context, not an alert, so it
        # rides on the Inference group's description rather than a banner.
        description = ensemble_context_banner(context) or (
            "Advanced processing options for this architecture"
        )
        for view in self._views:
            view.advanced_group.set_description(description)

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

    def _refresh_applicability(self) -> None:
        applicable = applicable_stack_names(
            self._context,
            active_method_key=self._active_method_key,
            selected_models=self._selected_models,
        )
        empty_ensemble = self._context == OPEN_CONTEXT_ENSEMBLE and not applicable
        counts = (
            member_arch_counts(self._selected_models)
            if self._context == OPEN_CONTEXT_ENSEMBLE
            else {}
        )
        # Separation: keep every architecture tab visible so options are never
        # wiped by hiding the active ViewStack child. Ensemble: hide arches
        # that no selected member uses (still show all when the list is empty).
        hide_unused = should_hide_unused_stacks(self._context, applicable)

        self._refresh_banner()

        for stack_name, page in self._tab_pages.items():
            is_applicable = stack_name in applicable

            stack_page = self._tab_stack_pages.get(stack_name)
            if stack_page is not None:
                stack_page.set_visible(is_applicable if hide_unused else True)
                if hasattr(stack_page, "set_badge_number"):
                    stack_page.set_badge_number(counts.get(stack_name, 0))

            # Separation keeps non-active arches editable for pre-config; the
            # page banner communicates that those values are unused.
            # Empty ensemble dims everything until members are chosen.
            if empty_ensemble:
                page.set_sensitive(False)
            elif hide_unused:
                page.set_sensitive(is_applicable)
            else:
                page.set_sensitive(True)
            page.set_opacity(1.0)

    def _refresh_banner(self) -> None:
        """Reveal, hide or relabel the sheet banner for the visible tab.

        There is one banner for the whole sheet, so it always describes whatever
        tab is on screen; ``_on_tab_changed`` brings us back here on every switch.
        """
        banner = self._banner
        stack_name = self._stack.get_visible_child_name()
        if stack_name is None:
            banner.set_revealed(False)
            return
        result = applicability_banner(
            self._context,
            stack_name,
            active_method_key=self._active_method_key,
            selected_models=self._selected_models,
        )
        if result is None:
            banner.set_revealed(False)
            # ``Adw.Banner``'s reveal is animated, so a stale title/button from a
            # previous context would flash before the hide finishes -- clear both
            # so a re-reveal always starts from a blank banner.
            banner.set_title("")
            banner.set_button_label("")
            return
        text, button_label = result
        banner.set_title(text)
        # Offering a switch we cannot perform would be a dead button.
        banner.set_button_label(
            button_label if button_label and self._on_switch_method else ""
        )
        banner.set_revealed(True)

    def present(
        self,
        *,
        context: str,
        active_method_key: str,
        selected_models: Sequence[str],
        initial_stack: Optional[str] = None,
    ) -> None:
        self.dialog.set_content_width(_SHEET_WIDTH)
        self.dialog.set_content_height(self._sheet_height())
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
    on_switch_method: Optional[Callable[[str], None]] = None,
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
            on_switch_method=on_switch_method,
        )
    sheet.present(
        context=context,
        active_method_key=active_method_key,
        selected_models=selected_models,
        initial_stack=initial_stack,
    )
    return sheet
