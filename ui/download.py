"""Download Center entry point, VIP / manual dialogs, and shared download services."""

from __future__ import annotations
import typing

import os
import threading

from gi.repository import Adw, GLib, Gtk

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    DONATE_LINK_BMAC,
    DONATE_LINK_PATREON,
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
from core.model_naming import canonical_display_name

from .dispatch import idle_on_main
from .dialogs.utils import configure_dialog_width, fill_dialog_width, present_modal_dialog, set_dialog_content
from .files import open_folder_in_file_manager, open_uri_in_browser
from .help_text import OPEN_EXTERNAL_LINK_HINT, OPEN_INSTALL_FOLDER_HINT
from .hints import set_icon_button_a11y
from .notifications import (
    NOTIFY_DOWNLOAD_COMPLETE,
    NOTIFY_DOWNLOAD_FAILED,
    send_desktop_notification,
)
from .spacing import inset_md
from .download_center import DownloadCenterWindow
from .widgets.download_queue_indicator import DownloadQueueIndicator


def download_batch_message(items: typing.Any) -> tuple[str, bool]:
    """Summarize terminal download outcomes for an honest in-app toast."""
    ready = sum(
        1 for item in items if item.status in (STATUS_COMPLETE, STATUS_EXISTS)
    )
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


def _get_manager(app_context: typing.Any) -> DownloadManager:
    manager = getattr(app_context, "_download_manager", None)
    if manager is None:
        manager = DownloadManager()
        setattr(app_context, "_download_manager", manager)
    return manager


def _get_queue(app_context: typing.Any, manager: DownloadManager) -> DownloadQueue:
    queue = getattr(app_context, "_download_queue", None)
    if queue is None:
        queue = DownloadQueue(manager, on_changed=lambda: None, repo=app_context.repo)
        setattr(app_context, "_download_queue", queue)
    return queue


def _send_download_notifications(
    app: typing.Any,
    settings: typing.Any,
    queue: DownloadQueue,
    *,
    items: typing.Any=None,
) -> None:
    items = queue.items() if items is None else list(items)
    complete = sum(1 for item in items if item.status == "complete")
    existed = sum(1 for item in items if item.status == "exists")
    failed = sum(1 for item in items if item.status == "failed")
    debug(
        "download",
        "download notification "
        f"complete={complete} exists={existed} failed={failed}",
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


def init_download_queue_ui(main_window: typing.Any, app_context: typing.Any, *, on_models_changed: typing.Any=None) -> DownloadQueueIndicator:
    """Wire the header download indicator and app-level queue callbacks."""
    manager = _get_manager(app_context)
    queue = _get_queue(app_context, manager)
    indicator = getattr(main_window, "_download_queue_indicator", None)
    if indicator is None:
        indicator = DownloadQueueIndicator()
        main_window._download_queue_indicator = indicator
    indicator.bind(queue)
    app_context._download_queue_indicator = indicator
    terminal_statuses = {
        STATUS_CANCELLED,
        STATUS_COMPLETE,
        STATUS_EXISTS,
        STATUS_FAILED,
    }
    reported_terminal_ids: set[str] = {
        item.item_id
        for item in queue.items()
        if item.status in terminal_statuses
    }

    def refresh() -> None:
        indicator.refresh()

    def after_batch() -> None:
        batch_items = [
            item
            for item in queue.items()
            if item.status in terminal_statuses
            and item.item_id not in reported_terminal_ids
        ]
        reported_terminal_ids.update(item.item_id for item in batch_items)
        indicator.on_batch_complete()
        center = getattr(app_context, "_download_center_window", None)
        if center is not None:
            center.refresh_after_downloads()
        if on_models_changed is not None:
            on_models_changed()
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

    queue.set_on_changed(lambda: idle_on_main(refresh))
    queue.set_on_batch_complete(lambda: idle_on_main(after_batch))
    if os.environ.get("UVR_DEBUG_QUEUE"):
        _seed_debug_queue(queue)
    chip_debug_scenarios = parse_chip_debug_scenarios()
    if chip_debug_scenarios:
        _start_chip_debug_cycle(queue, indicator, chip_debug_scenarios)
    if os.environ.get("UVR_DEBUG_QUEUE_POPUP"):
        _auto_open_popover(main_window, indicator)
    idle_on_main(refresh)
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
    handler_id[0] = main_window.connect(
        "map", lambda *_a: idle_on_main(open_once)
    )


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
    with queue._lock:  # noqa: SLF001 - dev-only seeding of the shared queue
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
    with queue._lock:  # noqa: SLF001 - dev-only queue seeding
        queue._items.clear()
        queue._items.extend(items)
    queue._notify()  # noqa: SLF001 - dev-only queue seeding


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
    indicator._sticky = True  # noqa: SLF001 - dev-only sticky chip
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
        manager = _get_manager(app_context)
        code = app_context.settings.process.user_code
        if code:
            manager.validate_vip_code(code)
        if manager.ensure_catalogues():
            manager.schedule_size_cache_warmup()
        else:
            debug("download", "size_cache_warmup refresh catalogues (no bundled cache)")
            manager.refresh()

    threading.Thread(target=worker, daemon=True).start()


def open_download_center(parent_window: typing.Any, app_context: typing.Any, on_models_changed: typing.Any=None):
    """Open or raise the Download Center utility window."""
    start_download_size_cache_warmup(app_context)
    center = getattr(app_context, "_download_center_window", None)
    if center is not None:
        center.present()
        return center

    manager = _get_manager(app_context)
    queue = _get_queue(app_context, manager)
    center = DownloadCenterWindow(
        parent_window,
        app_context,
        manager,
        queue,
        on_models_changed=on_models_changed,
    )
    app_context._download_center_window = center
    center.present()
    return center


# ---------------------------------------------------------------------------
# VIP code dialog
# ---------------------------------------------------------------------------

def open_vip_code_dialog(parent: typing.Any, app_context: typing.Any, on_validated: typing.Any=None):
    manager = _get_manager(app_context)
    settings = app_context.settings

    dialog = Adw.Dialog()
    dialog.set_title("Unlock VIP models")
    configure_dialog_width(dialog, parent, fallback=520)

    toast_overlay = Adw.ToastOverlay()
    fill_dialog_width(toast_overlay)

    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup(
        title="Download code",
        description=(
            "Obtain a code from the links below. Donations are appreciated but not required."
        ),
    )
    page.add(group)

    code_row = Adw.EntryRow(title="Code")
    code_row.set_text(settings.process.user_code)
    group.add(code_row)

    def toast(message: str) -> None:
        toast_overlay.add_toast(Adw.Toast.new(message))

    def on_confirm(_button: typing.Any):
        code = code_row.get_text().strip()
        unlocked = manager.validate_vip_code(code)
        if unlocked:
            settings.process.user_code = code
            error = app_context.try_save_settings(trigger="vip")
            if error:
                toast(error)
            else:
                toast("VIP models unlocked")
        else:
            toast("Incorrect code")
        debug("download", f"ui vip_code_confirm unlocked={unlocked}")
        if on_validated is not None:
            on_validated(unlocked)

    confirm_button = Gtk.Button(label="_Unlock", use_underline=True, valign=Gtk.Align.CENTER)
    confirm_button.add_css_class("suggested-action")
    confirm_button.connect("clicked", on_confirm)
    code_row.add_suffix(confirm_button)

    links_group = Adw.PreferencesGroup(title="Support UVR")
    for title, link in (
        ("Patreon", DONATE_LINK_PATREON),
        ("Buy Me a Coffee", DONATE_LINK_BMAC),
    ):
        row = Adw.ActionRow(title=title)
        button = Gtk.Button(icon_name="adw-external-link-symbolic", valign=Gtk.Align.CENTER)
        set_icon_button_a11y(button, f"{OPEN_EXTERNAL_LINK_HINT}: {title}")
        button.connect(
            "clicked",
            lambda _b, url=link: open_uri_in_browser(parent, url, on_error=toast),
        )
        row.add_suffix(button)
        row.set_activatable_widget(button)
        links_group.add(row)
    page.add(links_group)

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    inset_md(content)
    fill_dialog_width(content)
    fill_dialog_width(page)
    content.append(page)

    toast_overlay.set_child(content)
    set_dialog_content(dialog, toast_overlay)
    present_modal_dialog(dialog, parent)
    return dialog


# ---------------------------------------------------------------------------
# Manual downloads dialog
# ---------------------------------------------------------------------------

def open_manual_downloads(parent: typing.Any, app_context: typing.Any):
    manager = _get_manager(app_context)
    data = manager.manual_download_data()

    dialog = Adw.Dialog()
    dialog.set_title("Manual downloads")
    configure_dialog_width(dialog, parent, fallback=520)
    dialog.set_content_height(560)

    page = Adw.PreferencesPage()

    catalogue = [
        ("VR models", VR_ARCH_TYPE, data["vr"]),
        ("MDX-Net models", MDX_ARCH_TYPE, data["mdx"]),
        ("Demucs models", DEMUCS_ARCH_TYPE, data["demucs"]),
    ]

    for group_title, arch, models in catalogue:
        if not models:
            continue
        group = Adw.PreferencesGroup(title=group_title)
        for selectable, model in models.items():
            row = Adw.ExpanderRow()
            row.set_use_markup(False)
            # Canonical name for display; ``selectable`` stays the raw catalogue
            # label that manual_links resolves against.
            row.set_title(canonical_display_name(selectable))
            links = DownloadManager.manual_links(arch, model)
            for label, url in links:
                link_row = Adw.ActionRow()
                link_row.set_use_markup(False)
                link_row.set_title(label)
                link_row.set_subtitle(url)
                open_button = Gtk.Button(icon_name="adw-external-link-symbolic", valign=Gtk.Align.CENTER)
                set_icon_button_a11y(open_button, f"{OPEN_EXTERNAL_LINK_HINT}: {label}")
                open_button.connect(
                    "clicked",
                    lambda _b, u=url: open_uri_in_browser(parent, u),
                )
                link_row.add_suffix(open_button)
                link_row.set_activatable_widget(open_button)
                row.add_row(link_row)
            dir_row = Adw.ActionRow()
            dir_row.set_use_markup(False)
            dir_row.set_title("Install folder")
            dir_row.set_subtitle(DownloadManager.model_directory(arch, selectable))
            dir_button = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
            set_icon_button_a11y(dir_button, OPEN_INSTALL_FOLDER_HINT)
            dir_button.connect(
                "clicked",
                lambda _b, d=DownloadManager.model_directory(arch, selectable): open_folder_in_file_manager(
                    parent, d
                ),
            )
            dir_row.add_suffix(dir_button)
            row.add_row(dir_row)
            group.add(row)
        page.add(group)

    scroller = Gtk.ScrolledWindow(propagate_natural_height=False, vexpand=True)
    fill_dialog_width(scroller)
    fill_dialog_width(page)
    scroller.set_child(page)
    set_dialog_content(dialog, scroller)
    present_modal_dialog(dialog, parent)
    return dialog

