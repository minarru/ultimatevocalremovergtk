"""Collapsible log panel with run controls (progress + Start/Stop).

Replaces ``Adw.BottomSheet`` with a simple revealer-based panel: the log body
expands above the always-visible run controls, toggled by an ExpanderRow-style
arrow button (no drag gestures).
"""

from typing import Callable, Optional

from gi.repository import Gtk

from ..hints import set_tooltip
from .console import ConsoleView

_PANEL_WIDTH = 520

#: Extra bottom margin for scrollable option columns so the last rows can clear
#: the floating panel (collapsed height + overlay margin).
LOG_PANEL_BOTTOM_INSET = 120
_LOG_EMPTY_ICON = "utilities-terminal-symbolic"
_LOG_EMPTY_TITLE = "No activity yet"
_LOG_EMPTY_DESCRIPTION = "Start a process to see its log here."


def _bind_progress_label(progressbar: Gtk.ProgressBar, label: Gtk.Label) -> Gtk.ProgressBar:
    """Route ``ProgressBar.set_text`` to a label rendered below the bar."""

    def set_text(text: str) -> None:
        display = text or ""
        label.set_text(display)
        label.set_visible(bool(display))
        Gtk.ProgressBar.set_text(progressbar, "")

    progressbar.set_text = set_text  # type: ignore[method-assign]
    progressbar.set_show_text(False)
    return progressbar


class LogPanel(Gtk.Box):
    def __init__(
        self,
        on_console_changed: Optional[Callable[[bool], None]] = None,
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
        self._syncing_expand = False

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.add_css_class("uvr-run-controls")

        progress_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        progress_section.add_css_class("uvr-progress-section")

        self._progress_label = Gtk.Label(label="")
        self._progress_label.add_css_class("uvr-progress-label")
        self._progress_label.set_xalign(0.5)
        self._progress_label.set_halign(Gtk.Align.CENTER)
        self._progress_label.set_visible(False)

        self._progressbar = Gtk.ProgressBar()
        self._progressbar.add_css_class("uvr-progress-bar")
        _bind_progress_label(self._progressbar, self._progress_label)
        progress_section.append(self._progressbar)
        progress_section.append(self._progress_label)
        body.append(progress_section)

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
        set_tooltip(self.log_copy_button, "Copy the full log to the clipboard")
        self._log_meta_row.append(self.log_copy_button)

        self.log_clear_button = Gtk.Button(icon_name="user-trash-symbolic")
        self.log_clear_button.add_css_class("flat")
        set_tooltip(self.log_clear_button, "Clear the log")
        self._log_meta_row.append(self.log_clear_button)

        body.append(self._log_meta_row)

        self._log_revealer = Gtk.Revealer()
        self._log_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self._log_revealer.set_transition_duration(200)
        self._log_revealer.set_reveal_child(False)

        log_body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        log_body.add_css_class("uvr-log-body-wrap")

        self._log_stack = Gtk.Stack()
        self._log_stack.add_css_class("uvr-log-body")
        self._log_stack.set_size_request(-1, 200)

        empty_state = self._build_empty_state()
        self._log_stack.add_named(empty_state, "empty")

        self.console = ConsoleView(on_changed=self._handle_console_changed)
        self.console.add_css_class("uvr-log-console")
        self.console.set_size_request(-1, 200)
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
        set_tooltip(self.expand_button, "Show or hide the processing log")
        self.expand_button.connect("toggled", self._on_expand_toggled)
        action_row.append(self.expand_button)

        self._start_button = Gtk.Button(label="Start Processing", hexpand=True)
        self._start_button.add_css_class("suggested-action")
        action_row.append(self._start_button)

        self._stop_button = Gtk.Button(icon_name="process-stop-symbolic")
        self._stop_button.add_css_class("destructive-action")
        self._stop_button.set_sensitive(False)
        action_row.append(self._stop_button)

        body.append(action_row)
        self.append(body)

        self.progressbar = self._progressbar
        self.start_button = self._start_button
        self.stop_button = self._stop_button

        self._update_expanded_visibility(False)
        self._handle_console_changed(self.console.is_empty())

    def get_expanded(self) -> bool:
        return self._log_revealer.get_reveal_child()

    def set_expanded(self, expanded: bool) -> None:
        if self.get_expanded() == expanded and self.expand_button.get_active() == expanded:
            self._update_expanded_visibility(expanded)
            return
        self._syncing_expand = True
        self.expand_button.set_active(expanded)
        self._log_revealer.set_reveal_child(expanded)
        self._update_expanded_visibility(expanded)
        self._syncing_expand = False

    def _on_expand_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._syncing_expand:
            return
        expanded = button.get_active()
        self._log_revealer.set_reveal_child(expanded)
        self._update_expanded_visibility(expanded)

    def _update_expanded_visibility(self, expanded: bool) -> None:
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
