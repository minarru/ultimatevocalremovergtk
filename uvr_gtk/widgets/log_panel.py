"""Collapsible log panel with run controls (progress + Start/Stop).

Replaces ``Adw.BottomSheet`` with a simple revealer-based panel: the log body
expands above the always-visible run controls, toggled by an ExpanderRow-style
arrow button (no drag gestures).
"""

from typing import Callable, Optional

from gi.repository import GLib, Gtk

from uvr_core.debug_log import debug

from ..hints import set_icon_button_a11y
from .console import ConsoleView

_PANEL_WIDTH = 520
#: Log body height; keep in sync with ``.uvr-log-body { min-height }`` in
#: :mod:`uvr_gtk.application`.
_LOG_BODY_HEIGHT = 200
#: Bottom margin applied to the panel in :class:`uvr_gtk.window.MainWindow`.
OVERLAY_MARGIN_BOTTOM = 12
#: Layout reserves derived from ``application.py`` (``.uvr-run-controls``,
#: ``.uvr-run-actions``, ``.uvr-progress-section``). Used when the panel has
#: not been allocated yet and :meth:`Gtk.Widget.measure` is not meaningful.
_RUN_CONTROLS_PADDING_Y = 24
_RUN_ACTIONS_MIN_HEIGHT = 36
_PROGRESS_SECTION_RESERVE = 34
_PANEL_BORDER_RESERVE = 2

_LOG_EMPTY_ICON = "utilities-terminal-symbolic"
_LOG_EMPTY_TITLE = "No activity yet"
_LOG_EMPTY_DESCRIPTION = "Start a process to see its log here."


class LogPanel(Gtk.Box):
    def __init__(
        self,
        on_console_changed: Optional[Callable[[bool], None]] = None,
        on_expanded_changed: Optional[Callable[[bool], None]] = None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("uvr-log-panel")
        self.add_css_class("card")
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.END)
        self.set_size_request(_PANEL_WIDTH, -1)
        self.set_overflow(Gtk.Overflow.HIDDEN)

        self._on_console_changed = on_console_changed
        self._on_expanded_changed = on_expanded_changed
        self._syncing_expand = False
        self._defer_collapse_visibility = False
        self._pulse_source_id: Optional[int] = None

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.add_css_class("uvr-run-controls")

        self._progress_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._progress_section.add_css_class("uvr-progress-section")
        self._progress_section.set_visible(False)

        self._progress_label = Gtk.Label(label="")
        self._progress_label.add_css_class("uvr-progress-label")
        self._progress_label.set_xalign(0.5)
        self._progress_label.set_halign(Gtk.Align.CENTER)
        self._progress_label.set_visible(False)

        self._progressbar = Gtk.ProgressBar()
        self._progressbar.add_css_class("uvr-progress-bar")
        self._progressbar.set_show_text(False)
        self._progress_section.append(self._progressbar)
        self._progress_section.append(self._progress_label)
        body.append(self._progress_section)

        self._log_meta_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._log_meta_row.add_css_class("uvr-log-meta")

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_box.set_hexpand(True)
        title_icon = Gtk.Image.new_from_icon_name("utilities-terminal-symbolic")
        title_icon.set_pixel_size(16)
        title_icon.add_css_class("dim-label")
        title = Gtk.Label(label="Log", xalign=0.0)
        title.add_css_class("heading")
        title_box.append(title_icon)
        title_box.append(title)
        self._log_meta_row.append(title_box)

        self.log_copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self.log_copy_button.add_css_class("flat")
        set_icon_button_a11y(self.log_copy_button, "Copy the full log to the clipboard")
        self._log_meta_row.append(self.log_copy_button)

        self.log_clear_button = Gtk.Button(icon_name="user-trash-symbolic")
        self.log_clear_button.add_css_class("flat")
        set_icon_button_a11y(self.log_clear_button, "Clear the log")
        self._log_meta_row.append(self.log_clear_button)

        body.append(self._log_meta_row)

        self._log_revealer = Gtk.Revealer()
        self._log_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self._log_revealer.set_transition_duration(200)
        self._log_revealer.set_reveal_child(False)
        self._log_revealer.connect("notify::child-revealed", self._on_log_revealed)

        log_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        log_body.add_css_class("uvr-log-body-wrap")

        self._log_stack = Gtk.Stack()
        self._log_stack.add_css_class("uvr-log-body")
        self._log_stack.set_size_request(-1, _LOG_BODY_HEIGHT)

        empty_state = self._build_empty_state()
        self._log_stack.add_named(empty_state, "empty")

        self.console = ConsoleView(on_changed=self._handle_console_changed)
        self.console.add_css_class("uvr-log-console")
        self.console.set_min_content_height(_LOG_BODY_HEIGHT)
        self.console.set_max_content_height(_LOG_BODY_HEIGHT)
        self._log_stack.add_named(self.console, "console")

        log_body.append(self._log_stack)
        self._log_revealer.set_child(log_body)
        body.append(self._log_revealer)

        self._log_run_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._log_run_separator.set_visible(False)
        body.append(self._log_run_separator)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_row.add_css_class("uvr-run-actions")

        self.expand_button = Gtk.ToggleButton()
        self.expand_button.set_icon_name("adw-expander-arrow-symbolic")
        self.expand_button.add_css_class("flat")
        self.expand_button.add_css_class("uvr-log-expander-arrow")
        self.expand_button.set_valign(Gtk.Align.CENTER)
        set_icon_button_a11y(self.expand_button, "Show or hide the processing log")
        self.expand_button.connect("toggled", self._on_expand_toggled)
        action_row.append(self.expand_button)

        self._start_button = Gtk.Button(label="Start Processing", hexpand=True)
        self._start_button.add_css_class("suggested-action")
        self._start_button.set_valign(Gtk.Align.CENTER)
        action_row.append(self._start_button)

        self._stop_button = Gtk.Button(icon_name="process-stop-symbolic")
        self._stop_button.add_css_class("destructive-action")
        self._stop_button.set_sensitive(False)
        self._stop_button.set_valign(Gtk.Align.CENTER)
        action_row.append(self._stop_button)

        body.append(action_row)
        self.append(body)

        self.start_button = self._start_button
        self.stop_button = self._stop_button

        self._apply_expanded_visibility(False)
        self._handle_console_changed(self.console.is_empty())

    @property
    def progressbar(self) -> Gtk.ProgressBar:
        """Raw progress bar (prefer :meth:`set_progress_fraction` / :meth:`set_progress_text`)."""
        return self._progressbar

    @classmethod
    def _collapsed_body_height(cls, *, include_progress: bool = True) -> int:
        height = _RUN_CONTROLS_PADDING_Y + _RUN_ACTIONS_MIN_HEIGHT + _PANEL_BORDER_RESERVE
        if include_progress:
            height += _PROGRESS_SECTION_RESERVE
        return height

    @classmethod
    def default_bottom_inset(cls) -> int:
        """Scroll padding so option columns clear the collapsed floating panel."""
        # Progress is hidden until a run starts; reserve it only when visible
        # (see :meth:`collapsed_overlay_height`).
        return cls._collapsed_body_height(include_progress=False) + OVERLAY_MARGIN_BOTTOM

    def collapsed_overlay_height(self) -> int:
        """Bottom inset for the options scroller (always the collapsed panel height)."""
        include_progress = self._progress_section.get_visible()
        return self._collapsed_body_height(include_progress=include_progress) + OVERLAY_MARGIN_BOTTOM

    def set_progress_pulse_step(self, step: float) -> None:
        self._progressbar.set_pulse_step(step)

    def set_progress_fraction(self, fraction: float) -> None:
        self._progressbar.set_fraction(fraction)
        self._sync_progress_section_visible()

    def set_progress_text(self, text: str) -> None:
        display = text or ""
        self._progress_label.set_text(display)
        self._progress_label.set_visible(bool(display))
        self._sync_progress_section_visible()

    def start_progress_pulse(self, interval_ms: int) -> None:
        if self._pulse_source_id is not None:
            return
        self._progressbar.pulse()
        self._pulse_source_id = GLib.timeout_add(interval_ms, self._on_pulse_tick)
        self._sync_progress_section_visible()

    def stop_progress_pulse(self) -> None:
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None
        self._sync_progress_section_visible()

    def prepare_for_run(self) -> None:
        """Show the console and reset scroll before worker output arrives."""
        revealed = self._log_revealer.get_child_revealed()
        debug("ui", f"log_panel.prepare_for_run child_revealed={revealed}")
        self._log_stack.set_visible_child_name("console")
        self.console._reset_scroll()
        if self._log_revealer.get_child_revealed():
            self.console.resume_scroll()
            self.console.scroll_to_end_stable()
        else:
            debug("ui", "log_panel.prepare_for_run defer_scroll")
            self.console.defer_scroll_until_settled()

    def get_expanded(self) -> bool:
        return self._log_revealer.get_reveal_child()

    def set_expanded(self, expanded: bool) -> None:
        if self.get_expanded() == expanded and self.expand_button.get_active() == expanded:
            if expanded:
                self._apply_expanded_visibility(True)
            elif not self._defer_collapse_visibility:
                self._apply_expanded_visibility(self._log_revealer.get_child_revealed())
            return
        self._syncing_expand = True
        self.expand_button.set_active(expanded)
        self._log_revealer.set_reveal_child(expanded)
        if expanded:
            self._defer_collapse_visibility = False
            self._apply_expanded_visibility(True)
        else:
            self._defer_collapse_visibility = True
        self._notify_expanded_changed(expanded)
        self._syncing_expand = False

    def _on_pulse_tick(self) -> bool:
        self._progressbar.pulse()
        return GLib.SOURCE_CONTINUE

    def _sync_progress_section_visible(self) -> None:
        busy = (
            self._progress_label.get_visible()
            or self._progressbar.get_fraction() > 0.0
            or self._pulse_source_id is not None
        )
        self._progress_section.set_visible(busy)

    def _notify_expanded_changed(self, expanded: bool) -> None:
        if self._on_expanded_changed is not None:
            self._on_expanded_changed(expanded)

    def _on_expand_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._syncing_expand:
            return
        expanded = button.get_active()
        self._log_revealer.set_reveal_child(expanded)
        if expanded:
            self._defer_collapse_visibility = False
            self._apply_expanded_visibility(True)
        else:
            self._defer_collapse_visibility = True
        self._notify_expanded_changed(expanded)

    def _on_log_revealed(self, revealer: Gtk.Revealer, _pspec) -> None:
        if revealer.get_child_revealed():
            debug("ui", "log_panel child revealed resume_scroll")
            self._apply_expanded_visibility(True)
            self._defer_collapse_visibility = False
            self.console.resume_scroll()
            debug("ui", "log_panel scroll_to_end_stable")
            self.console.scroll_to_end_stable()
            return
        if self._defer_collapse_visibility:
            self._apply_expanded_visibility(False)
            self._defer_collapse_visibility = False

    def _apply_expanded_visibility(self, expanded: bool) -> None:
        self._log_meta_row.set_visible(expanded)
        self._log_run_separator.set_visible(expanded)

    def _handle_console_changed(self, is_empty: bool) -> None:
        self._log_stack.set_visible_child_name("empty" if is_empty else "console")
        self.log_clear_button.set_sensitive(not is_empty)
        self.log_copy_button.set_sensitive(not is_empty)
        if self._on_console_changed is not None:
            self._on_console_changed(is_empty)

    def _build_empty_state(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_vexpand(True)
        outer.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("uvr-log-empty")
        box.set_valign(Gtk.Align.CENTER)
        box.set_vexpand(True)
        box.set_halign(Gtk.Align.CENTER)

        icon = Gtk.Image.new_from_icon_name(_LOG_EMPTY_ICON)
        icon.set_pixel_size(36)
        icon.set_opacity(0.45)
        box.append(icon)

        title = Gtk.Label(label=_LOG_EMPTY_TITLE)
        title.add_css_class("title-4")
        box.append(title)

        description = Gtk.Label(
            label=_LOG_EMPTY_DESCRIPTION,
            wrap=True,
            justify=Gtk.Justification.CENTER,
            max_width_chars=36,
        )
        description.add_css_class("dim-label")
        box.append(description)
        outer.append(box)
        return outer
