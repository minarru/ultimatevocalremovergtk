"""Collapsible log panel with run controls (progress + Start/Stop).

Replaces ``Adw.BottomSheet`` with a simple revealer-based panel: the log body
expands above the always-visible run controls, toggled by an ExpanderRow-style
arrow button (no drag gestures).
"""

import typing
from typing import Callable, Optional

from gi.repository import GLib, Gtk

from core.debug_log import debug

from ..hints import set_icon_button_a11y
from ..resources import RESOURCE_PREFIX, require_resource_bundle
from .console import ConsoleView

# Layout constants below mirror ``resources/style.css``. Used when the panel has
# not been allocated yet and :meth:`Gtk.Widget.measure` is not meaningful.
#: Log body height ↔ ``.uvr-log-body { min-height }``.
_LOG_BODY_HEIGHT = 200
#: Meta row ↔ ``.uvr-log-meta`` min-height 32 + padding-bottom 8.
_LOG_META_ROW_RESERVE = 40
#: Log body wrap ↔ ``.uvr-log-body-wrap`` padding-bottom.
_LOG_BODY_WRAP_RESERVE = 12
#: Overlay bottom gap ↔ ``MainWindow`` ``set_margin_bottom`` on the log panel.
OVERLAY_MARGIN_BOTTOM = 12
#: Run controls vertical padding ↔ ``.uvr-run-controls { padding }`` (12 + 12).
_RUN_CONTROLS_PADDING_Y = 24
#: Action row height ↔ ``.uvr-run-actions { min-height }``.
_RUN_ACTIONS_MIN_HEIGHT = 36
#: Progress bar block ↔ ``.uvr-progress-section`` + ``.uvr-progress-label`` margins.
_PROGRESS_SECTION_RESERVE = 34
#: Card border in ``.uvr-log-panel``.
_PANEL_BORDER_RESERVE = 2

_PROGRESS_DONE_LABEL = "Done"
#: Delay before a finished run's 100% / "Done" bar collapses on its own.
_DONE_COLLAPSE_MS = 5000
_TEMPLATE_RESOURCE = f"{RESOURCE_PREFIX}/ui/log_panel.ui"
require_resource_bundle(_TEMPLATE_RESOURCE)


@Gtk.Template(resource_path=_TEMPLATE_RESOURCE)
class LogPanel(Gtk.Box):
    __gtype_name__ = "LogPanel"

    _progress_section: Gtk.Box = Gtk.Template.Child("progress_section")
    _progress_label: Gtk.Label = Gtk.Template.Child("progress_label")
    _progressbar: Gtk.ProgressBar = Gtk.Template.Child("progressbar")
    _progress_revealer: Gtk.Revealer = Gtk.Template.Child("progress_revealer")
    _log_meta_row: Gtk.Box = Gtk.Template.Child("log_meta_row")
    _log_title: Gtk.Label = Gtk.Template.Child("log_title")
    log_copy_button: Gtk.Button = Gtk.Template.Child("log_copy_button")
    log_clear_button: Gtk.Button = Gtk.Template.Child("log_clear_button")
    _log_revealer: Gtk.Revealer = Gtk.Template.Child("log_revealer")
    _log_stack: Gtk.Stack = Gtk.Template.Child("log_stack")
    expand_button: Gtk.ToggleButton = Gtk.Template.Child("expand_button")
    _start_button: Gtk.Button = Gtk.Template.Child("start_button")
    _stop_button: Gtk.Button = Gtk.Template.Child("stop_button")

    #: Public alias so callers don't reach for the module-private constant.
    DONE_COLLAPSE_MS = _DONE_COLLAPSE_MS

    def __init__(
        self,
        on_console_changed: Optional[Callable[[bool], None]] = None,
        on_expanded_changed: Optional[Callable[[bool], None]] = None,
    ):
        super().__init__()

        self._on_console_changed = on_console_changed
        self._on_expanded_changed = on_expanded_changed
        self._syncing_expand = False
        self._pulse_source_id: Optional[int] = None
        self._done_collapse_id: Optional[int] = None
        self._run_label = ""
        self._progress_status = ""

        set_icon_button_a11y(self.log_copy_button, "Copy full log")
        set_icon_button_a11y(self.log_clear_button, "Clear the log")
        self._log_revealer.connect("notify::child-revealed", self._on_log_revealed)

        self.console = ConsoleView(on_changed=self._handle_console_changed)
        self.console.add_css_class("uvr-log-console")
        self.console.set_min_content_height(_LOG_BODY_HEIGHT)
        self.console.set_max_content_height(_LOG_BODY_HEIGHT)
        self._log_stack.add_named(self.console, "console")
        self._sync_expand_button_a11y(False)
        self.expand_button.connect("toggled", self._on_expand_toggled)
        set_icon_button_a11y(self._stop_button, "Stop processing")

        self.start_button = self._start_button
        self.stop_button = self._stop_button

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
        # (see :meth:`options_overlay_clearance`).
        return cls._collapsed_body_height(include_progress=False) + OVERLAY_MARGIN_BOTTOM

    def options_overlay_clearance(self) -> int:
        """Bottom inset for the options scroller to clear the floating log panel."""
        height = self._collapsed_body_height(include_progress=False)
        if self._progress_revealer.get_reveal_child():
            height += _PROGRESS_SECTION_RESERVE
        if self._log_revealer.get_reveal_child():
            height += _LOG_META_ROW_RESERVE + _LOG_BODY_HEIGHT + _LOG_BODY_WRAP_RESERVE
        return height + OVERLAY_MARGIN_BOTTOM

    def collapsed_overlay_height(self) -> int:
        """Alias for :meth:`options_overlay_clearance`."""
        return self.options_overlay_clearance()

    def set_progress_pulse_step(self, step: float) -> None:
        self._progressbar.set_pulse_step(step)

    def set_run_label(self, label: str) -> None:
        """Identify the job whose output remains pinned in the shared log."""
        self._run_label = label or ""
        self._log_title.set_label(f"{label} log" if label else "Log")

    def set_progress_fraction(self, fraction: float) -> None:
        self._progressbar.set_fraction(fraction)
        self._sync_progress_section_visible()

    def set_progress_text(self, text: str) -> None:
        self._progress_status = text or ""
        display = self._progress_status
        if display and self._run_label:
            display = f"{self._run_label} — {display}"
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

    def clear_progress(self) -> None:
        """Reset the progress bar and collapse the progress revealer."""
        self.stop_progress_pulse()
        self._progressbar.set_fraction(0.0)
        self._progress_status = ""
        self._progress_label.set_text("")
        self._progress_label.set_visible(False)
        self._sync_progress_section_visible()

    def mark_run_complete(self) -> None:
        """Collapse the finished progress block after a short grace period.

        The completion toast and the log both persist the result, so the 100% /
        "Done" bar only needs to be visible long enough to be read. Collapsing
        it also returns ``_PROGRESS_SECTION_RESERVE`` px of scroll clearance to
        the option columns (see :meth:`options_overlay_clearance`).
        """
        self._cancel_done_collapse()
        self._done_collapse_id = GLib.timeout_add(_DONE_COLLAPSE_MS, self._on_done_collapse)

    def _on_done_collapse(self) -> bool:
        self._done_collapse_id = None
        self.clear_progress()
        return GLib.SOURCE_REMOVE

    def _cancel_done_collapse(self) -> None:
        if self._done_collapse_id is not None:
            GLib.source_remove(self._done_collapse_id)
            self._done_collapse_id = None

    def clear_log(self) -> None:
        """Clear the console; collapse the progress block after a finished run."""
        self.console.clear()
        self._collapse_progress_if_done()

    def _collapse_progress_if_done(self) -> None:
        if (
            self._pulse_source_id is None
            and self._progressbar.get_fraction() >= 1.0
            and self._progress_status == _PROGRESS_DONE_LABEL
        ):
            self.clear_progress()

    def prepare_for_run(self) -> None:
        """Show the console and reset scroll before worker output arrives."""
        self._cancel_done_collapse()
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
            self._sync_expand_button_a11y(expanded)
            return
        self._syncing_expand = True
        self.expand_button.set_active(expanded)
        self._log_revealer.set_reveal_child(expanded)
        self._sync_expand_button_a11y(expanded)
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
        self._progress_revealer.set_reveal_child(busy)

    def _notify_expanded_changed(self, expanded: bool) -> None:
        if self._on_expanded_changed is not None:
            self._on_expanded_changed(expanded)

    def _sync_expand_button_a11y(self, expanded: bool) -> None:
        action = "Hide" if expanded else "Show"
        set_icon_button_a11y(self.expand_button, f"{action} processing log")

    def _on_expand_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._syncing_expand:
            return
        expanded = button.get_active()
        self._log_revealer.set_reveal_child(expanded)
        self._sync_expand_button_a11y(expanded)
        self._notify_expanded_changed(expanded)

    def _on_log_revealed(self, revealer: Gtk.Revealer, _pspec: typing.Any) -> None:
        if not revealer.get_child_revealed():
            return
        debug("ui", "log_panel child revealed resume_scroll")
        self.console.resume_scroll()
        debug("ui", "log_panel scroll_to_end_stable")
        self.console.scroll_to_end_stable()

    def _handle_console_changed(self, is_empty: bool) -> None:
        self._log_stack.set_visible_child_name("empty" if is_empty else "console")
        self.log_clear_button.set_sensitive(not is_empty)
        self.log_copy_button.set_sensitive(not is_empty)
        if self._on_console_changed is not None:
            self._on_console_changed(is_empty)
