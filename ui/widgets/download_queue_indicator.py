"""Nautilus-style download queue chip and popover for the main window header."""

from __future__ import annotations
import typing

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional

from gi.repository import GLib, Gtk, Pango

from core.download_queue import DownloadQueueItem
from ui.hints import set_icon_button_a11y
from ui.widgets.download_queue_icons import (
    ICON_CANCEL,
    ICON_CANCELLED,
    ICON_CHIP_SUCCESS,
    ICON_RETRY,
    ICON_ROW_SUCCESS,
)
from ui.widgets.progress_ring import ProgressRing

if TYPE_CHECKING:
    from core.download_queue import DownloadQueue

from core.download_status import (
    ACTIVE_STATUSES,
    SUCCESS_STATUSES,
    TERMINAL_STATUSES,
    STATUS_CANCELLED,
    STATUS_COMPLETE,
    STATUS_DOWNLOADING,
    STATUS_EXISTS,
    STATUS_FAILED,
    STATUS_QUEUED,
    is_failed,
    row_action_tooltip_for,
    row_progress_for,
)

REMOVE_FINISHED_TIMEOUT_S = 3
ATTENTION_TIMEOUT_MS = 2000
CHIP_HEIGHT = 34


@dataclass(frozen=True)
class QueueSummary:
    chip_label: str
    has_active: bool
    has_failed: bool
    all_terminal: bool
    total: int
    finished_count: int


@dataclass(frozen=True)
class ChipRingState:
    progress: float
    outcome: str  # "active", "success", "partial", "failed", "cancelled"


def chip_ring_state(items: List[DownloadQueueItem], summary: QueueSummary) -> ChipRingState:
    """Aggregate progress and outcome for the single header chip ring."""
    if summary.has_active:
        active = [item for item in items if item.status in ACTIVE_STATUSES]
        if active:
            progress = sum(
                max(0.0, min(1.0, item.progress))
                if item.status == STATUS_DOWNLOADING
                else 0.0
                for item in active
            ) / len(active)
        else:
            progress = 0.0
        return ChipRingState(progress=progress, outcome="active")

    success_count = sum(1 for item in items if item.status in SUCCESS_STATUSES)
    failed_count = sum(1 for item in items if is_failed(item.status))
    cancelled_count = sum(1 for item in items if item.status == STATUS_CANCELLED)

    if failed_count > 0 and success_count > 0:
        return ChipRingState(progress=1.0, outcome="partial")
    if failed_count > 0:
        return ChipRingState(progress=0.0, outcome="failed")
    if success_count > 0:
        return ChipRingState(progress=1.0, outcome="success")
    if cancelled_count > 0:
        return ChipRingState(progress=1.0, outcome="cancelled")
    return ChipRingState(progress=0.0, outcome="active")


def summarize_queue(items: List[DownloadQueueItem]) -> QueueSummary:
    """Derive chip labels from queue items."""
    total = len(items)
    if total == 0:
        return QueueSummary(
            chip_label="",
            has_active=False,
            has_failed=False,
            all_terminal=True,
            total=0,
            finished_count=0,
        )

    active = [item for item in items if item.status in ACTIVE_STATUSES]
    failed = [item for item in items if is_failed(item.status)]
    finished = [item for item in items if item.status in TERMINAL_STATUSES]
    finished_count = len(finished)

    has_active = bool(active)
    has_failed = bool(failed)
    all_terminal = finished_count == total

    if has_active:
        count = len(active)
        if count == 1:
            chip_label = "Downloading 1 model"
        else:
            chip_label = f"Downloading {count} models"
    elif has_failed:
        failed_count = len(failed)
        success_count = sum(1 for item in items if item.status in SUCCESS_STATUSES)
        if success_count > 0:
            if failed_count == 1 and success_count == 1:
                chip_label = "1 failed, 1 downloaded"
            elif failed_count == 1:
                chip_label = f"1 failed, {success_count} downloaded"
            elif success_count == 1:
                chip_label = f"{failed_count} failed, 1 downloaded"
            else:
                chip_label = f"{failed_count} failed, {success_count} downloaded"
        elif failed_count == 1:
            chip_label = "1 download failed"
        else:
            chip_label = f"{failed_count} downloads failed"
    else:
        success = sum(1 for item in items if item.status in SUCCESS_STATUSES)
        cancelled = sum(1 for item in items if item.status == STATUS_CANCELLED)
        if success == 0 and cancelled > 0:
            if cancelled == 1:
                chip_label = "1 download cancelled"
            else:
                chip_label = f"{cancelled} downloads cancelled"
        elif success == 1:
            chip_label = "Downloaded 1 model"
        else:
            chip_label = f"Downloaded {success} models"

    return QueueSummary(
        chip_label=chip_label,
        has_active=has_active,
        has_failed=has_failed,
        all_terminal=all_terminal,
        total=total,
        finished_count=finished_count,
    )


def _status_subtitle(item: DownloadQueueItem) -> str:
    return item.detail or item.status.replace("_", " ").title()


def _details_markup(text: str) -> str:
    if not text:
        return ""
    escaped = GLib.markup_escape_text(text)
    return f"<span size='small'>{escaped}</span>"


def _row_button_state(item: DownloadQueueItem) -> tuple[str, bool]:
    if item.status in ACTIVE_STATUSES:
        return ICON_CANCEL, True
    if item.status in SUCCESS_STATUSES:
        return ICON_ROW_SUCCESS, False
    if item.status == STATUS_CANCELLED:
        return ICON_CANCELLED, False
    if item.status == STATUS_FAILED:
        return ICON_RETRY, True
    return ICON_CANCEL, False


def should_schedule_remove_finished(
    summary: QueueSummary,
    *,
    popover_visible: bool,
    defer_remove_on_close: bool,
) -> bool:
    """Return whether finished queue items should auto-clear after a delay.

    Failed items are kept so the user can retry; auto-clear only runs when
    every terminal item succeeded or was cancelled.
    """
    return (
        summary.all_terminal
        and summary.total > 0
        and not summary.has_failed
        and not popover_visible
        and not defer_remove_on_close
    )


class DownloadQueueIndicator:
    """Header chip + popover bound to a :class:`DownloadQueue`."""

    def __init__(self) -> None:
        self._queue: Optional[DownloadQueue] = None
        self._queue_rows: dict[str, Gtk.ListBoxRow] = {}
        self._remove_finished_timeout_id: int = 0
        self._attention_timeout_id: int = 0
        self._popover_visible = False
        self._defer_remove_on_close = False
        # Dev-only (UVR_DEBUG_QUEUE_STICKY): never auto-dismiss finished items
        # and keep the chip visible even when the queue empties, so the finished
        # state can be styled without the 3s timer clearing it.
        self._sticky = bool(os.environ.get("UVR_DEBUG_QUEUE_STICKY"))

        self._chip_ring = ProgressRing()

        self._chip_label = Gtk.Label()
        self._chip_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._chip_label.add_css_class("uvr-download-queue-chip-label")

        chip_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chip_content.add_css_class("uvr-chip-content")
        chip_content.set_valign(Gtk.Align.CENTER)
        chip_content.append(self._chip_ring)
        chip_content.append(self._chip_label)

        self.widget = Gtk.MenuButton()
        self.widget.add_css_class("uvr-download-queue-chip")
        self.widget.set_valign(Gtk.Align.CENTER)
        self.widget.set_size_request(-1, CHIP_HEIGHT)
        self.widget.set_child(chip_content)
        set_icon_button_a11y(self.widget, "Show download queue")
        self.widget.set_visible(False)
        self.widget.connect("map", self._on_menu_button_mapped)

        self._queue_list = Gtk.ListBox()
        self._queue_list.add_css_class("operations-list")
        self._queue_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._queue_list.set_activate_on_single_click(False)
        self._queue_list.set_margin_start(6)
        self._queue_list.set_margin_end(6)
        self._queue_list.set_margin_top(6)
        self._queue_list.set_margin_bottom(6)

        list_scroller = Gtk.ScrolledWindow()
        list_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scroller.set_max_content_height(270)
        list_scroller.set_propagate_natural_height(True)
        list_scroller.set_child(self._queue_list)

        self._popover = Gtk.Popover()
        self._popover.set_child(list_scroller)
        self._popover.connect("notify::visible", self._on_popover_notify_visible)
        self.widget.set_popover(self._popover)

    def popup(self) -> None:
        """Show the download queue popover (toggle pressed state on the chip)."""
        self.widget.popup()

    def _on_menu_button_mapped(self, *_args: typing.Any) -> None:
        """Apply libadwaita chip styling to the inner toggle (not the MenuButton shell)."""
        toggle = self.widget.get_first_child()
        if toggle is None:
            return
        if not toggle.has_css_class("chip"):
            toggle.add_css_class("chip")

    def dev_disable_autohide(self) -> None:
        """Keep the popover open when focus leaves it (e.g. the GTK Inspector).

        Dev-only: an autohide popover dismisses itself on outside focus, which
        makes it impossible to inspect. Disabling autohide keeps it pinned.
        """
        self._popover.set_autohide(False)

    def bind(self, queue: DownloadQueue) -> None:
        self._queue = queue

    def refresh(self) -> None:
        if self._queue is None:
            return

        items = self._queue.items()
        summary = summarize_queue(items)

        if not items:
            if not self._sticky:
                self.widget.set_visible(False)
            self._unschedule_remove_finished()
            return

        self.widget.set_visible(True)
        if self._chip_label.get_label() != summary.chip_label:
            self._chip_label.set_label(summary.chip_label)
        accessible_label = (
            f"Show download queue: {summary.chip_label}"
            if summary.chip_label
            else "Show download queue"
        )
        set_icon_button_a11y(self.widget, accessible_label)
        self._chip_ring.update_from_state(chip_ring_state(items, summary))
        self._render_rows(items)

        if summary.has_active:
            self._unschedule_remove_finished()
            self._defer_remove_on_close = False
        elif summary.all_terminal:
            if self._popover_visible:
                self._defer_remove_on_close = True
                self._unschedule_remove_finished()
            elif should_schedule_remove_finished(
                summary,
                popover_visible=self._popover_visible,
                defer_remove_on_close=self._defer_remove_on_close,
            ):
                self._schedule_remove_finished()

    def on_batch_complete(self) -> None:
        if not self._popover_visible:
            self._add_attention()

    def hold_finished(self, seconds: int) -> None:
        """Keep terminal rows available while an actionable toast is visible."""
        self._unschedule_remove_finished()
        if self._popover_visible:
            self._defer_remove_on_close = True
            return
        self._remove_finished_timeout_id = GLib.timeout_add_seconds(
            max(1, seconds),
            self._on_remove_finished_timeout,
        )

    def on_popover_visibility_changed(self, visible: bool) -> None:
        self._popover_visible = visible
        if visible:
            self._unschedule_remove_finished()
            self._defer_remove_on_close = False
            return
        if self._defer_remove_on_close and self._queue is not None:
            summary = summarize_queue(self._queue.items())
            if should_schedule_remove_finished(
                summary,
                popover_visible=False,
                defer_remove_on_close=False,
            ):
                self._schedule_remove_finished()
            self._defer_remove_on_close = False

    def _on_popover_notify_visible(self, _popover: typing.Any, _pspec: typing.Any) -> None:
        self.on_popover_visibility_changed(self._popover.get_visible())

    def _on_cancel_clicked(self, _button: typing.Any, item_id: str) -> None:
        if self._queue is None:
            return
        for item in self._queue.items():
            if item.item_id == item_id and item.status == STATUS_FAILED:
                self._queue.retry(item_id)
                return
        self._queue.cancel(item_id)

    def _render_rows(self, items: List[DownloadQueueItem]) -> None:
        seen = {item.item_id for item in items}

        for item_id in list(self._queue_rows):
            if item_id not in seen:
                row = self._queue_rows.pop(item_id)
                self._queue_list.remove(row)

        for item in items:
            row = self._queue_rows.get(item.item_id)
            if row is None:
                row = self._make_queue_row(item)
                self._queue_list.append(row)
                self._queue_rows[item.item_id] = row
            self._update_queue_row(row, item)

    def _make_queue_row(self, item: DownloadQueueItem) -> Gtk.ListBoxRow:
        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        grid.set_margin_start(6)
        grid.set_margin_end(6)
        grid.set_margin_top(6)
        grid.set_margin_bottom(6)

        status = Gtk.Label(xalign=0.0)
        status.set_size_request(300, -1)
        status.set_margin_bottom(6)
        status.set_hexpand(True)
        status.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        status.set_max_width_chars(40)

        progress = Gtk.ProgressBar()
        progress.set_show_text(False)
        progress.set_valign(Gtk.Align.CENTER)
        progress.set_margin_start(2)
        progress.set_margin_bottom(4)
        progress.set_hexpand(True)
        progress.set_pulse_step(0.05)

        detail = Gtk.Label(xalign=0.0)
        detail.set_wrap(True)
        detail.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        detail.set_ellipsize(Pango.EllipsizeMode.END)
        detail.add_css_class("dim-label")
        detail.add_css_class("numeric")
        detail.set_use_markup(True)

        action_button = Gtk.Button(icon_name=ICON_CANCEL)
        action_button.add_css_class("circular")
        action_button.set_valign(Gtk.Align.CENTER)
        action_button.set_margin_start(20)
        set_icon_button_a11y(action_button, "Cancel download")
        action_button.connect("clicked", self._on_cancel_clicked, item.item_id)

        grid.attach(status, 0, 0, 1, 1)
        grid.attach(progress, 0, 1, 1, 1)
        grid.attach(detail, 0, 2, 1, 1)
        grid.attach(action_button, 1, 0, 1, 3)

        grid._uvr_status = status  # type: ignore[attr-defined]
        grid._uvr_detail = detail  # type: ignore[attr-defined]
        grid._uvr_progress = progress  # type: ignore[attr-defined]
        grid._uvr_action = action_button  # type: ignore[attr-defined]
        grid._uvr_item_id = item.item_id  # type: ignore[attr-defined]

        list_row = Gtk.ListBoxRow()
        list_row.set_child(grid)
        return list_row

    def _update_queue_row(self, list_row: Gtk.ListBoxRow, item: DownloadQueueItem) -> None:
        grid = list_row.get_child()
        if not isinstance(grid, Gtk.Grid):
            return
        status: Gtk.Label = grid._uvr_status  # type: ignore[attr-defined]
        detail: Gtk.Label = grid._uvr_detail  # type: ignore[attr-defined]
        progress: Gtk.ProgressBar = grid._uvr_progress  # type: ignore[attr-defined]
        action: Gtk.Button = grid._uvr_action  # type: ignore[attr-defined]

        if status.get_label() != item.label:
            status.set_label(item.label)
        subtitle = _status_subtitle(item)
        markup = _details_markup(subtitle)
        if getattr(grid, "_uvr_detail_markup", None) != markup:
            grid._uvr_detail_markup = markup  # type: ignore[attr-defined]
            detail.set_markup(markup)
        detail.set_visible(bool(subtitle))

        presentation = row_progress_for(item.status)
        progress.set_visible(presentation.visible)
        if not presentation.visible:
            pass
        elif presentation.mode == "pulse":
            progress.set_fraction(0.0)
            progress.pulse()
        elif presentation.mode == "fraction":
            progress.set_fraction(max(0.0, min(1.0, item.progress)))
        elif presentation.mode == "full":
            progress.set_fraction(1.0)
        else:
            progress.set_fraction(0.0)

        icon_name, sensitive = _row_button_state(item)
        action.set_icon_name(icon_name)
        action.set_sensitive(sensitive)
        set_icon_button_a11y(action, row_action_tooltip_for(item.status))

    def _schedule_remove_finished(self) -> None:
        if self._sticky:
            return
        if self._remove_finished_timeout_id != 0:
            return
        self._remove_finished_timeout_id = GLib.timeout_add_seconds(
            REMOVE_FINISHED_TIMEOUT_S,
            self._on_remove_finished_timeout,
        )

    def _unschedule_remove_finished(self) -> None:
        if self._remove_finished_timeout_id != 0:
            GLib.source_remove(self._remove_finished_timeout_id)
            self._remove_finished_timeout_id = 0

    def _on_remove_finished_timeout(self) -> bool:
        self._remove_finished_timeout_id = 0
        if self._queue is not None:
            self._queue.clear_finished()
            self.refresh()
        return GLib.SOURCE_REMOVE

    def _add_attention(self) -> None:
        self._remove_attention(immediate=True)
        self.widget.add_css_class("needs-attention")
        self._attention_timeout_id = GLib.timeout_add(
            ATTENTION_TIMEOUT_MS,
            self._on_attention_timeout,
        )

    def _remove_attention(self, *, immediate: bool = False) -> None:
        if self._attention_timeout_id != 0:
            if not immediate:
                return
            GLib.source_remove(self._attention_timeout_id)
            self._attention_timeout_id = 0
        self.widget.remove_css_class("needs-attention")

    def _on_attention_timeout(self) -> bool:
        self._attention_timeout_id = 0
        self.widget.remove_css_class("needs-attention")
        return GLib.SOURCE_REMOVE
