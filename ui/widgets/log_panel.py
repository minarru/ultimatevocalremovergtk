"""Collapsible log panel with run controls (progress + Start/Stop).

Replaces ``Adw.BottomSheet`` with a simple revealer-based panel: the log body
expands above the always-visible run controls, toggled by an ExpanderRow-style
arrow button (no drag gestures).
"""

import typing
from typing import Callable, Optional

from gi.repository import Adw, GLib, Gtk

from core.debug_log import debug

from ..hints import set_icon_button_a11y
from ..resources import RESOURCE_PREFIX, require_resource_bundle
from .console import ConsoleView
from .log_layout import PanelLayout, StableLogLayout

# Fallback before the overlay's first allocation. Actual clearance is measured
# at the target width before starting the animation.
_LOG_BODY_HEIGHT = 200
OVERLAY_MARGIN_BOTTOM = 12

_PROGRESS_DONE_LABEL = "Done"
#: Delay before a finished run's 100% / "Done" bar collapses on its own.
_DONE_COLLAPSE_MS = 5000
_TEMPLATE_RESOURCE = f"{RESOURCE_PREFIX}/ui/log_panel.ui"
require_resource_bundle(_TEMPLATE_RESOURCE)


@Gtk.Template(resource_path=_TEMPLATE_RESOURCE)
class LogPanel(Gtk.Box):
    __gtype_name__ = "LogPanel"

    _panel_clamp: Adw.Clamp = Gtk.Template.Child("panel_clamp")
    _run_actions: Gtk.CenterBox = Gtk.Template.Child("run_actions")
    _control_content: Gtk.Box = Gtk.Template.Child("control_content")
    _log_content: Gtk.Box = Gtk.Template.Child("log_content")
    _log_viewport: Gtk.Box = Gtk.Template.Child("log_viewport")
    _detail_label: Gtk.Label = Gtk.Template.Child("detail_label")
    _percentage: Gtk.Label = Gtk.Template.Child("percentage")
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
        Adw.init()
        super().__init__()

        self._on_console_changed = on_console_changed
        self._on_expanded_changed = on_expanded_changed
        self._syncing_expand = False
        self._pulse_source_id: Optional[int] = None
        self._done_collapse_id: Optional[int] = None
        self._available_size = (0, 0)
        self._geometry_idle: int | None = None
        self._geometry_key: tuple[object, ...] | None = None
        self._width_target = 400
        self._width_animation: Adw.TimedAnimation | None = None
        self._clearance = self.default_bottom_inset()
        self._on_layout_changed: Callable[[], None] | None = None
        self._log_height = _LOG_BODY_HEIGHT
        self._run_label = ""
        self._preparing = False
        self._progress_title: str | None = None
        self._result_status = ""
        self._blocked_reason: str | None = None
        self._progress_status = ""

        self._log_revealer.connect("notify::child-revealed", self._on_log_revealed)

        self.console = ConsoleView(on_changed=self._handle_console_changed)
        self.console.add_css_class("uvr-log-console")
        self.console.set_min_content_height(_LOG_BODY_HEIGHT)
        self.console.set_max_content_height(_LOG_BODY_HEIGHT)
        self._stable_layout = StableLogLayout()
        self._log_viewport.set_layout_manager(self._stable_layout)
        self._log_viewport.append(self.console)
        self.set_layout_manager(PanelLayout(self._queue_geometry))
        self.connect("notify::scale-factor", lambda *_: self._update_geometry())
        self.get_settings().connect_object(
            "notify::gtk-xft-dpi", lambda panel, *_: panel._update_geometry(), self
        )
        self._sync_expand_button_a11y(False)
        self.expand_button.connect("toggled", self._on_expand_toggled)

        self.start_button = self._start_button
        self.stop_button = self._stop_button

        self._handle_console_changed(self.console.is_empty())

    def do_contains(self, x: float, y: float) -> bool:
        """Target the visible card, not the full-size overlay allocation.

        Keeping the ancestors targetable allows buttons and the text view to
        receive pointer events. The card's padding also blocks clicks through
        to options behind it, while space outside the card stays interactive.
        """
        surface = self._panel_clamp.get_child()
        if surface is None:
            return False
        valid, bounds = surface.compute_bounds(self)
        return bool(
            valid
            and bounds.get_x() <= x < bounds.get_x() + bounds.get_width()
            and bounds.get_y() <= y < bounds.get_y() + bounds.get_height()
        )

    @property
    def progressbar(self) -> Gtk.ProgressBar:
        """Raw progress bar (prefer :meth:`set_progress_fraction` / :meth:`set_progress_text`)."""
        return self._progressbar

    @classmethod
    def default_bottom_inset(cls) -> int:
        """Initial reserve before the target layout can be measured."""
        return 112

    def options_overlay_clearance(self) -> int:
        """Bottom inset for the options scroller to clear the floating log panel."""
        return self._clearance

    def set_layout_changed_callback(self, callback: Callable[[], None]) -> None:
        self._on_layout_changed = callback

    def _queue_geometry(self, width: int, height: int) -> None:
        if (width, height) == self._available_size:
            return
        self._available_size = (width, height)
        if self._geometry_idle is None:
            self._geometry_idle = GLib.idle_add(self._apply_geometry)

    def _apply_geometry(self) -> bool:
        self._geometry_idle = None
        self._update_geometry()
        return GLib.SOURCE_REMOVE

    def _update_geometry(self) -> None:
        available_width, available_height = self._available_size
        if not available_width or not available_height:
            return
        scale = Adw.length_unit_to_px(Adw.LengthUnit.SP, 1, self.get_settings())
        width = max(1, round(min(self._width_target * scale, available_width - 48)) - 2)
        self._stable_layout.set_text_width(
            max(1, round(min(560 * scale, available_width - 48)) - 30)
        )
        key = (
            self._available_size,
            scale,
            self._width_target,
            self._progress_label.get_text(),
            self._detail_label.get_visible(),
            self._percentage.get_visible(),
            self._progress_revealer.get_reveal_child(),
            self.get_expanded(),
        )
        if key == self._geometry_key:
            return
        self._geometry_key = key
        # Measure the final child composition, never an intermediate revealer
        # allocation. No work remains scheduled once allocation settles.
        status = self._progress_section.measure(Gtk.Orientation.VERTICAL, max(1, width - 16))[0]
        actions = self._run_actions.measure(Gtk.Orientation.VERTICAL, max(1, width - 16))[0]
        controls = 16 + status + actions
        if self._progress_revealer.get_reveal_child():
            controls += self._progressbar.measure(Gtk.Orientation.VERTICAL, width)[0]
        log_content = self._log_content.measure(Gtk.Orientation.VERTICAL, width)[0]
        stack = self._log_stack.measure(Gtk.Orientation.VERTICAL, max(1, width - 16))[0]
        overhead = controls + log_content - stack + 2
        if not self._progress_revealer.get_reveal_child():
            overhead += self._progressbar.measure(Gtk.Orientation.VERTICAL, width)[0]
        height = round(min(360 * scale, max(80, available_height * 0.65 - overhead)))
        if height != self._log_height:
            self._log_height = height
            if height > self.console.get_max_content_height():
                self.console.set_max_content_height(height)
                self.console.set_min_content_height(height)
            else:
                self.console.set_min_content_height(height)
                self.console.set_max_content_height(height)
            self._log_stack.set_size_request(-1, height)
        clearance = controls + 2 + OVERLAY_MARGIN_BOTTOM
        if self.get_expanded():
            clearance += log_content - stack + height
        if clearance != self._clearance:
            self._clearance = clearance
            if self._on_layout_changed is not None:
                self._on_layout_changed()

    def _sync_width(self) -> None:
        target = 560 if self.get_expanded() and not self.console.is_empty() else 400
        if target == self._width_target:
            self._update_geometry()
            return
        self._width_target = target
        if self._width_animation is not None:
            self._width_animation.pause()
        self._update_geometry()
        self._width_animation = Adw.TimedAnimation.new(
            self,
            self._panel_clamp.get_maximum_size(),
            target,
            220,
            Adw.CallbackAnimationTarget.new(self._set_panel_width),
        )
        self._width_animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self._width_animation.play()

    def _set_panel_width(self, value: float) -> None:
        width = round(value)
        self._panel_clamp.set_maximum_size(width)
        self._panel_clamp.set_tightening_threshold(width)

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

    def set_progress_text(self, text: str, *, title: str | None = None) -> None:
        self._progress_title = title
        self._progress_status = text or ""
        if text:
            self._result_status = ""
            self._progress_label.remove_css_class("error")
        self._render_status()
        self._sync_progress_section_visible()

    def set_preparing(self, preparing: bool) -> None:
        self._preparing = preparing
        self._render_status()
        self._update_geometry()

    def set_start_blocked_reason(self, reason: str | None) -> None:
        self._blocked_reason = reason
        self._render_status()
        self._update_geometry()

    def set_run_result(self, text: str, *, error: bool = False) -> None:
        """Retain a terminal result without suggesting that progress is live."""
        self._cancel_done_collapse()
        self._result_status = text
        self.stop_progress_pulse()
        self._progress_status = ""
        self._render_status()
        self._sync_progress_section_visible()
        if error:
            self._progress_label.add_css_class("error")
        else:
            self._progress_label.remove_css_class("error")

    def _render_status(self) -> None:
        if self._preparing:
            title = "Preparing…"
            detail = "Checking model configuration and output options"
        elif self._progress_status:
            title = self._progress_title or self._progress_status
            detail = self._progress_status if self._progress_title else ""
            # The dedicated numeric label already displays the percentage.
            first, separator, rest = detail.partition(" · ")
            if separator and first.endswith("%") and first[:-1].isdigit():
                detail = rest
            if self._run_label:
                title = f"{self._run_label} — {title}"
        else:
            title = self._result_status or self._blocked_reason or "Ready to process"
            detail = self._blocked_reason if self._result_status and self._blocked_reason else ""
        self._progress_label.set_label(title)
        self._progress_label.set_visible(True)
        self._detail_label.set_label(detail or "")
        self._detail_label.set_tooltip_text(detail or None)
        self._detail_label.set_visible(bool(detail))

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
        """Reset the progress track while retaining the terminal or readiness status."""
        self.stop_progress_pulse()
        self._progressbar.set_fraction(0.0)
        self._progress_status = ""
        self._render_status()
        self._sync_progress_section_visible()

    def mark_run_complete(self) -> None:
        """Dismiss the finished progress track after five seconds, retaining its result."""
        self._cancel_done_collapse()
        self._done_collapse_id = GLib.timeout_add(_DONE_COLLAPSE_MS, self._on_done_collapse)

    def _on_done_collapse(self) -> bool:
        self._done_collapse_id = None
        self._result_status = f"{self._run_label or 'Processing'} complete"
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
            self._cancel_done_collapse()
            self._on_done_collapse()

    def prepare_for_run(self) -> None:
        """Show the console and reset scroll before worker output arrives."""
        self._cancel_done_collapse()
        revealed = self._log_revealer.get_child_revealed()
        debug("ui", f"log_panel.prepare_for_run child_revealed={revealed}")
        self._log_stack.set_visible_child_name("console")
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
        self._sync_width()
        self._notify_expanded_changed(expanded)
        self._syncing_expand = False

    def _on_pulse_tick(self) -> bool:
        self._progressbar.pulse()
        return GLib.SOURCE_CONTINUE

    def _sync_progress_section_visible(self) -> None:
        busy = not self._result_status and (
            bool(self._progress_status)
            or self._progressbar.get_fraction() > 0.0
            or self._pulse_source_id is not None
        )
        self._progress_revealer.set_reveal_child(busy)
        self._percentage.set_label(f"{round(self._progressbar.get_fraction() * 100)}%")
        self._percentage.set_visible(busy and self._pulse_source_id is None)
        self._update_geometry()

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
        self._sync_width()
        self._notify_expanded_changed(expanded)

    def _on_log_revealed(self, revealer: Gtk.Revealer, _pspec: typing.Any) -> None:
        if (
            not revealer.get_child_revealed()
            or self._log_stack.get_visible_child_name() != "console"
        ):
            return
        debug("ui", "log_panel child revealed resume_scroll")
        self.console.resume_scroll()
        debug("ui", "log_panel scroll_to_end_stable")
        self.console.scroll_to_end_stable()

    def _handle_console_changed(self, is_empty: bool) -> None:
        self._log_stack.set_visible_child_name("empty" if is_empty else "console")
        self._sync_width()
        self.log_clear_button.set_sensitive(not is_empty)
        self.log_copy_button.set_sensitive(not is_empty)
        if self._on_console_changed is not None:
            self._on_console_changed(is_empty)
