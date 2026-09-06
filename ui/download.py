"""Download Center entry point, manual dialog, and shared download services."""

from __future__ import annotations

import os
import threading
import typing

from gi.repository import Adw, GLib, Gtk

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    VR_ARCH_TYPE,
)
from core.debug_log import debug
from core.download_queue import DownloadQueue, DownloadQueueItem
from core.download_status import (
    STATUS_CANCELLED,
    STATUS_COMPLETE,
    STATUS_DOWNLOADING,
    STATUS_EXISTS,
    STATUS_FAILED,
)
from core.downloads import DownloadManager

from .lifetime import UiLifetime

if typing.TYPE_CHECKING:
    from .context import AppContext
    from .window import MainWindow

from .dialogs.utils import (
    configure_dialog_width,
    present_modal_dialog,
)
from .dispatch import idle_on_main, latest_main_thread
from .download_center import DownloadCenterWindow
from .files import open_folder_in_file_manager, open_uri_in_browser
from .help_text import OPEN_INSTALL_FOLDER_HINT
from .hints import set_icon_button_a11y
from .notifications import (
    NOTIFY_DOWNLOAD_COMPLETE,
    NOTIFY_DOWNLOAD_FAILED,
    send_desktop_notification,
)
from .template import load_builder, object_from_builder
from .widgets.download_queue_indicator import DownloadQueueIndicator


def download_batch_message(items: typing.Any) -> tuple[str, bool]:
    """Summarize terminal download outcomes for an honest in-app toast."""
    ready = sum(1 for item in items if item.status in (STATUS_COMPLETE, STATUS_EXISTS))
    failed = sum(1 for item in items if item.status == STATUS_FAILED)
    cancelled = sum(1 for item in items if item.status == STATUS_CANCELLED)
    if failed:
        message = f"{failed} download{'s' if failed != 1 else ''} failed"
        if ready:
            message += f"; {ready} succeeded"
        if cancelled:
            message += f"; {cancelled} cancelled"
        return message, True
    if cancelled:
        message = f"{cancelled} download{'s' if cancelled != 1 else ''} cancelled"
        if ready:
            message += f"; {ready} succeeded"
        return message, True
    if ready:
        return (
            f"{ready} model{'s' if ready != 1 else ''} ready to use",
            False,
        )
    return "Downloads finished", False


def _send_download_notifications(
    app: typing.Any,
    settings: typing.Any,
    queue: DownloadQueue,
    *,
    items: typing.Any = None,
) -> None:
    items = queue.items() if items is None else list(items)
    complete = sum(1 for item in items if item.status == "complete")
    existed = sum(1 for item in items if item.status == "exists")
    failed = sum(1 for item in items if item.status == "failed")
    debug(
        "download",
        f"download notification complete={complete} exists={existed} failed={failed}",
    )
    if failed:
        if failed == 1:
            body = "1 download failed"
        else:
            body = f"{failed} downloads failed"
        if complete or existed:
            body += f"; {complete + existed} succeeded"
        send_desktop_notification(
            app,
            settings,
            setting_key=NOTIFY_DOWNLOAD_FAILED,
            ident="uvr-download-failed",
            title="Model downloads finished with errors",
            body=body,
        )
        return
    if complete or existed:
        count = complete + existed
        if count == 1:
            body = "1 model is ready to use"
        else:
            body = f"{count} models are ready to use"
        send_desktop_notification(
            app,
            settings,
            setting_key=NOTIFY_DOWNLOAD_COMPLETE,
            ident="uvr-download-complete",
            title="Model downloads complete",
            body=body,
        )


class DownloadQueueUiBinding:
    """Own the cached browser and the queue's current UI callback deliveries."""

    terminal_statuses = {STATUS_CANCELLED, STATUS_COMPLETE, STATUS_EXISTS, STATUS_FAILED}

    def __init__(self, main_window: MainWindow, app_context: AppContext):
        self.window = main_window
        self.context = app_context
        self.queue = app_context.download_queue
        self.indicator = main_window._download_queue_indicator
        self.center: DownloadCenterWindow | None = None
        self._lifetime = UiLifetime()
        self.indicator.bind(self.queue, owner=self)
        self.reported_terminal_ids = {
            item.item_id for item in self.queue.items() if item.status in self.terminal_statuses
        }
        self._changed_callback = latest_main_thread(self.refresh)
        self._batch_callback = lambda: idle_on_main(self.after_batch)
        self.queue.set_on_changed(self._changed_callback)
        self.queue.set_on_batch_complete(self._batch_callback)
        self._changed_callback()

    def refresh(self) -> None:
        if not self._lifetime.disposed:
            self.indicator.refresh()

    def after_batch(self) -> None:
        if self._lifetime.disposed:
            return
        queue = self.queue
        indicator = self.indicator
        reported_terminal_ids = self.reported_terminal_ids
        terminal_statuses = self.terminal_statuses
        main_window = self.window
        app_context = self.context
        batch_items = [
            item
            for item in queue.items()
            if item.status in terminal_statuses and item.item_id not in reported_terminal_ids
        ]
        reported_terminal_ids.update(item.item_id for item in batch_items)
        indicator.on_batch_complete()
        center = self.center
        if center is not None:
            center.refresh_after_downloads()
        message, needs_attention = download_batch_message(batch_items)
        toast = Adw.Toast.new(message)
        if needs_attention:
            indicator.hold_finished(10)
            toast.set_priority(Adw.ToastPriority.HIGH)
            toast.set_timeout(8)
            toast.set_button_label("View Queue")
            toast.connect("button-clicked", lambda *_: indicator.popup())
        main_window.toast_overlay.add_toast(toast)
        _send_download_notifications(
            main_window.get_application(),
            app_context.settings,
            queue,
            items=batch_items,
        )

    def present_center(self) -> DownloadCenterWindow:
        if self.center is None:
            self.center = DownloadCenterWindow(
                self.window, self.context, self.context.download_manager, self.queue
            )
        self.center.present()
        return self.center

    def dispose(self) -> None:
        if self._lifetime.disposed:
            return
        self._lifetime.dispose()
        self.queue.clear_callbacks(
            on_changed=self._changed_callback, on_batch_complete=self._batch_callback
        )
        if self.center is not None:
            self.center.dispose()
        self.indicator.dispose(owner=self)


def init_download_queue_ui(
    main_window: MainWindow, app_context: AppContext
) -> DownloadQueueIndicator:
    prior = main_window._download_ui
    center = None
    if prior is not None:
        # Transfer the cache before releasing the old UI binding. Rebinding
        # callbacks has never meant closing the retained browser.
        center, prior.center = prior.center, None
        prior.dispose()
    binding = DownloadQueueUiBinding(main_window, app_context)
    binding.center = center
    main_window._download_ui = binding
    queue, indicator = binding.queue, binding.indicator
    if os.environ.get("UVR_DEBUG_QUEUE"):
        _seed_debug_queue(queue)
    chip_debug_scenarios = parse_chip_debug_scenarios()
    if chip_debug_scenarios:
        _start_chip_debug_cycle(queue, indicator, chip_debug_scenarios)
    if os.environ.get("UVR_DEBUG_QUEUE_POPUP"):
        _auto_open_popover(main_window, indicator)
    return indicator


def _auto_open_popover(main_window: typing.Any, indicator: DownloadQueueIndicator) -> None:
    """Dev-only (UVR_DEBUG_QUEUE_POPUP): open the popover once the window maps.

    Autohide is disabled so the popover stays open when focus moves to the GTK
    Inspector (Ctrl+Shift+I) for styling/layout work.
    """
    indicator.dev_disable_autohide()

    def open_once(*_args: typing.Any) -> None:
        indicator.refresh()
        indicator.popup()
        if handler_id[0] is not None:
            main_window.disconnect(handler_id[0])
            handler_id[0] = None

    handler_id = [None]
    handler_id[0] = main_window.connect("map", lambda *_a: idle_on_main(open_once))


def _seed_debug_queue(queue: DownloadQueue) -> None:
    """Inject fake queue items so the header chip/popover can be styled offline.

    Enabled with ``UVR_DEBUG_QUEUE=1``. One item stays ``downloading`` so the
    auto-dismiss timer never fires and the chip remains visible.
    """
    samples = [
        ("UVR-MDX-NET Main", "MDX-Net", "downloading", 0.42, "12.3 / 29.1 MB (file 1/1)"),
        ("Kim Vocal 2", "MDX-Net", "complete", 1.0, "Complete"),
        ("Demucs v4 (htdemucs)", "Demucs", "failed", 0.0, "ConnectionError"),
        ("5_HP-Karaoke-UVR", "VR Arch", "queued", 0.0, "Waiting"),
        ("UVR-DeEcho-DeReverb", "VR Arch", "cancelled", 0.0, "Cancelled"),
    ]
    items = [
        DownloadQueueItem(
            item_id=f"debug-{index}",
            selection=name,
            arch_type=arch,
            label=name,
            jobs=[],
            status=status,
            progress=progress,
            detail=detail,
        )
        for index, (name, arch, status, progress, detail) in enumerate(samples)
    ]
    with queue._lock:  # dev-only seeding of the shared queue
        queue._items.extend(items)
    debug("download", f"seeded debug queue with {len(items)} items")


_CHIP_DEBUG_ORDER = ("active", "success", "partial", "failed", "cancelled")

_CHIP_DEBUG_SCENARIOS: dict[str, list[tuple[str, str, str, float, str]]] = {
    "active": [
        ("UVR-MDX-NET Main", "MDX-Net", STATUS_DOWNLOADING, 0.65, "12.3 / 29.1 MB (file 1/1)"),
        ("Kim Vocal 2", "MDX-Net", STATUS_DOWNLOADING, 0.35, "4.1 / 11.8 MB (file 1/1)"),
    ],
    "success": [
        ("Kim Vocal 2", "MDX-Net", STATUS_COMPLETE, 1.0, "Complete"),
        ("Demucs v4 (htdemucs)", "Demucs", STATUS_EXISTS, 1.0, "Already on disk"),
    ],
    "partial": [
        ("Kim Vocal 2", "MDX-Net", STATUS_COMPLETE, 1.0, "Complete"),
        ("5_HP-Karaoke-UVR", "VR Arch", STATUS_FAILED, 0.0, "ConnectionError"),
    ],
    "failed": [
        ("5_HP-Karaoke-UVR", "VR Arch", STATUS_FAILED, 0.0, "ConnectionError"),
        ("UVR-DeEcho-DeReverb", "VR Arch", STATUS_FAILED, 0.0, "TimeoutError"),
    ],
    "cancelled": [
        ("UVR-DeEcho-DeReverb", "VR Arch", STATUS_CANCELLED, 0.0, "Cancelled"),
    ],
}


def parse_chip_debug_scenarios() -> list[str] | None:
    """Parse ``UVR_DEBUG_QUEUE_CHIP`` for chip state visual QA.

    Values:
    - ``1``, ``true``, ``cycle``, ``all`` — rotate through every chip outcome
    - ``active``, ``success``, … — pin to one scenario
    - comma-separated list — rotate through the named scenarios only
    """
    raw = os.environ.get("UVR_DEBUG_QUEUE_CHIP", "").strip()
    if not raw:
        return None
    if raw.lower() in {"1", "true", "yes", "cycle", "all"}:
        return list(_CHIP_DEBUG_ORDER)
    names = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [name for name in names if name not in _CHIP_DEBUG_SCENARIOS]
    if unknown:
        debug("download", f"chip debug ignored unknown scenario(s): {', '.join(unknown)}")
    selected = [name for name in names if name in _CHIP_DEBUG_SCENARIOS]
    return selected or None


def chip_debug_items_for(scenario: str) -> list[DownloadQueueItem]:
    """Build fake queue rows that produce a specific chip outcome."""
    rows = _CHIP_DEBUG_SCENARIOS[scenario]
    return [
        DownloadQueueItem(
            item_id=f"chip-debug-{scenario}-{index}",
            selection=name,
            arch_type=arch,
            label=name,
            jobs=[],
            status=status,
            progress=progress,
            detail=detail,
        )
        for index, (name, arch, status, progress, detail) in enumerate(rows)
    ]


def _replace_queue_items(queue: DownloadQueue, items: list[DownloadQueueItem]) -> None:
    with queue._lock:  # dev-only queue seeding
        queue._items.clear()
        queue._items.extend(items)
    queue._notify()  # dev-only queue seeding


def _start_chip_debug_cycle(
    queue: DownloadQueue,
    indicator: DownloadQueueIndicator,
    scenarios: list[str],
) -> None:
    """Cycle chip outcomes for headless-incompatible visual QA.

    Enabled with ``UVR_DEBUG_QUEUE_CHIP``. Keeps the chip visible (sticky) and
    optionally pairs with ``UVR_DEBUG_QUEUE_POPUP=1`` to inspect popover rows.
    Interval seconds: ``UVR_DEBUG_QUEUE_CHIP_INTERVAL`` (default 4).
    """
    interval_s = max(1, int(os.environ.get("UVR_DEBUG_QUEUE_CHIP_INTERVAL", "4")))
    indicator._sticky = True  # dev-only sticky chip
    index = 0

    def apply_scenario() -> None:
        nonlocal index
        scenario = scenarios[index]
        items = chip_debug_items_for(scenario)
        _replace_queue_items(queue, items)
        indicator.widget.set_tooltip_text(f"Chip debug: {scenario}")
        debug("download", f"chip debug scenario={scenario}")

    def on_timeout() -> bool:
        nonlocal index
        index = (index + 1) % len(scenarios)
        apply_scenario()
        return GLib.SOURCE_CONTINUE

    apply_scenario()
    GLib.timeout_add_seconds(interval_s, on_timeout)


def start_download_size_cache_warmup(app_context: typing.Any) -> None:
    """Prefetch checkpoint download sizes (7-day TTL).

    Intended for Download Center open / refresh — not app startup — so a cold
    size cache does not HEAD hundreds of URLs before the user needs sizes.
    """
    if getattr(app_context, "_size_cache_warmup_started", False):
        return
    app_context._size_cache_warmup_started = True

    def worker() -> None:
        manager = app_context.download_manager
        if manager.ensure_catalogues():
            manager.schedule_size_cache_warmup()
        else:
            debug("download", "size_cache_warmup refresh catalogues (no bundled cache)")
            manager.refresh()

    threading.Thread(target=worker, daemon=True).start()


def open_download_center(
    parent_window: typing.Any,
    app_context: typing.Any,
    *,
    purpose: str | None = None,
    arch: str | None = None,
):
    """Open or raise the Download Center utility window.

    ``purpose`` and ``arch`` target a catalogue page and network filter when
    an empty-state banner opens the window. Omit them for the menu and
    shortcut so an already-open window is not reset.
    """
    start_download_size_cache_warmup(app_context)
    if parent_window._download_ui is None:
        init_download_queue_ui(parent_window, app_context)
    binding = parent_window._download_ui
    assert binding is not None
    center = binding.present_center()
    if purpose is not None or arch is not None:
        center.select_catalogue(purpose=purpose, arch=arch)
    return center


# ---------------------------------------------------------------------------
# Manual downloads dialog
# ---------------------------------------------------------------------------


def open_manual_downloads(parent: typing.Any, app_context: typing.Any):
    manager = app_context.download_manager
    data = manager.manual_download_rows()

    builder = load_builder("manual-downloads")
    dialog = object_from_builder(builder, "dialog", Adw.Dialog)
    configure_dialog_width(dialog, parent, fallback=520)
    page = object_from_builder(builder, "page", Adw.PreferencesPage)

    catalogue = [
        ("VR models", VR_ARCH_TYPE, data["vr"]),
        ("MDX-Net models", MDX_ARCH_TYPE, data["mdx"]),
        ("Demucs models", DEMUCS_ARCH_TYPE, data["demucs"]),
    ]

    for group_title, arch, models in catalogue:
        if not models:
            continue
        group = Adw.PreferencesGroup(title=group_title)
        for manual_row in models:
            selectable = manual_row.selection
            row = Adw.ExpanderRow()
            row.set_use_markup(False)
            row.set_title(manual_row.display)
            links = manual_row.resolve_links()
            for label, url in links:
                link_builder = load_builder("manual-download-link")
                link_row = object_from_builder(link_builder, "row", Adw.ActionRow)
                link_row.set_title(label)
                link_row.set_subtitle(url)
                open_button = object_from_builder(link_builder, "open_button", Gtk.Button)
                set_icon_button_a11y(open_button, f"Open {label} in default browser")
                open_button.connect(
                    "clicked",
                    lambda _b, u=url: open_uri_in_browser(parent, u),
                )
                row.add_row(link_row)
            folder_builder = load_builder("manual-download-folder")
            dir_row = object_from_builder(folder_builder, "row", Adw.ActionRow)
            install_folder = DownloadManager.model_directory(arch, selectable)
            dir_row.set_subtitle(install_folder)
            dir_button = object_from_builder(folder_builder, "open_button", Gtk.Button)
            set_icon_button_a11y(dir_button, OPEN_INSTALL_FOLDER_HINT)
            dir_button.connect(
                "clicked",
                lambda _b, d=install_folder: open_folder_in_file_manager(parent, d),
            )
            row.add_row(dir_row)
            group.add(row)
        page.add(group)

    present_modal_dialog(dialog, parent)
    return dialog
