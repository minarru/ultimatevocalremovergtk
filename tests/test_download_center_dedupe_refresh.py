"""Download Center reaction to the post-warmup content dedupe.

The identity HEAD pass lands tens of seconds after the window has rendered, so
rows the dedupe removed have to leave the list without a full rebuild — a
rebuild would reset the user's scroll position mid-browse.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.access_policy import AccessPolicy
from core.catalogue_coordinator import CatalogueCoordinator
from core.catalogue_types import RefreshMode, SourceId
from core.downloads import DownloadManager
from core.remote_catalog_cache import RemoteJsonSource


def _bare_window() -> Any:
    from ui.download_center import DownloadCenterWindow

    win = object.__new__(DownloadCenterWindow)
    from ui.catalogue_browser import CatalogueBrowserState
    win.browser = CatalogueBrowserState()
    from ui.lifetime import UiLifetime
    win._lifetime = UiLifetime()
    win._listening = False
    win._sort_mode = "name"
    win._arch_filter = "all"
    win.manager = mock.MagicMock()
    win.manager.latest_snapshot = None
    win._catalogue_refresh_armed = False
    win._row_checks = {}
    win._row_actions = {}
    win._size_lookup_ids = {}
    win._list_boxes = {}
    win.browser.available = {}
    win.browser.unsupported = {}
    win._downloads_dirty = False
    win.browser.snapshot = None
    win.browser.pending_source = False
    return win


def _disabled_source(source_id: SourceId) -> RemoteJsonSource:
    return RemoteJsonSource(source_id=source_id, enabled=lambda: False)


def _injected_coordinator(payload: dict[str, Any]) -> CatalogueCoordinator:
    return CatalogueCoordinator(
        sources={
            SourceId.UPSTREAM: RemoteJsonSource(
                source_id=SourceId.UPSTREAM, local_loader=lambda: payload
            ),
            SourceId.POLITREES: _disabled_source(SourceId.POLITREES),
            SourceId.EXTRAS: _disabled_source(SourceId.EXTRAS),
            SourceId.MVSEPLESS: _disabled_source(SourceId.MVSEPLESS),
        }
    )


def _seed_row(win: Any, arch: str, name: str, *, checked: bool = False) -> Any:
    action = mock.MagicMock(name=f"row:{name}")
    check = mock.MagicMock(name=f"check:{name}")
    check.get_active.return_value = checked
    win._row_actions[(arch, name)] = action
    win._row_checks[(arch, name)] = check
    from ui.catalogue_browser import BrowserRow
    win.browser.rows[(arch, name)] = BrowserRow((arch, name), name, arch)
    win.browser.set_selected((arch, name), checked)
    win._size_lookup_ids[(arch, name)] = 1
    win._list_boxes.setdefault(arch, mock.MagicMock(name=f"listbox:{arch}"))
    return action


class CatalogueRefreshDebounceTests(unittest.TestCase):
    def test_repeated_notifies_arm_one_timeout(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        timeout_calls: list[tuple[int, Any]] = []

        with mock.patch(
            "gi.repository.GLib.timeout_add",
            side_effect=lambda ms, cb: (timeout_calls.append((ms, cb)), 1)[1],
        ), mock.patch(
            "ui.download_center.idle_on_main", side_effect=lambda fn: fn()
        ):
            for _ in range(5):
                DownloadCenterWindow._schedule_catalogue_row_refresh(win)

        self.assertTrue(win._catalogue_refresh_armed)
        self.assertEqual(len(timeout_calls), 1)
        self.assertEqual(timeout_calls[0][0], 250)

    def test_notify_hops_to_main_thread(self) -> None:
        """The manager fires this from the size-warmup thread."""
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        idle_calls: list[Any] = []

        with mock.patch(
            "ui.download_center.idle_on_main",
            side_effect=lambda fn, *a, **k: idle_calls.append(fn),
        ):
            DownloadCenterWindow._schedule_catalogue_row_refresh(win)

        self.assertEqual(idle_calls, [win._arm_catalogue_row_refresh])


class CatalogueRowRemovalTests(unittest.TestCase):
    def test_removes_only_rows_the_dedupe_dropped(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        kept = _seed_row(win, MDX_ARCH_TYPE, "Kept Model")
        dropped = _seed_row(win, MDX_ARCH_TYPE, "Rehosted Copy")
        other_tab = _seed_row(win, VR_ARCH_TYPE, "VR Model")

        win.manager.available_downloads.return_value = {
            MDX_ARCH_TYPE: ["Kept Model"],
            VR_ARCH_TYPE: ["VR Model"],
        }
        win.manager.unsupported_downloads.return_value = {}
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()

        DownloadCenterWindow._flush_catalogue_row_refresh(win)

        win._list_boxes[MDX_ARCH_TYPE].remove.assert_called_once_with(dropped)
        win._list_boxes[VR_ARCH_TYPE].remove.assert_not_called()
        self.assertNotIn((MDX_ARCH_TYPE, "Rehosted Copy"), win._row_actions)
        self.assertNotIn((MDX_ARCH_TYPE, "Rehosted Copy"), win._row_checks)
        self.assertNotIn((MDX_ARCH_TYPE, "Rehosted Copy"), win._size_lookup_ids)
        self.assertIn((MDX_ARCH_TYPE, "Kept Model"), win._row_actions)
        self.assertIn((VR_ARCH_TYPE, "VR Model"), win._row_actions)
        self.assertIsNotNone(kept)
        self.assertIsNotNone(other_tab)

    def test_keeps_unsupported_rows_that_are_not_in_available(self) -> None:
        """Unsupported rows live in a second dict — comparing against
        ``available`` alone would sweep every one of them off the list."""
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        _seed_row(win, MDX_ARCH_TYPE, "Kept Model")
        _seed_row(win, MDX_ARCH_TYPE, "Broken Model")

        win.manager.available_downloads.return_value = {MDX_ARCH_TYPE: ["Kept Model"]}
        win.manager.unsupported_downloads.return_value = {
            MDX_ARCH_TYPE: [("Broken Model", "needs a newer build")]
        }
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()

        DownloadCenterWindow._flush_catalogue_row_refresh(win)

        win._list_boxes[MDX_ARCH_TYPE].remove.assert_not_called()
        self.assertIn((MDX_ARCH_TYPE, "Broken Model"), win._row_actions)

    def test_refreshes_button_when_a_checked_row_disappears(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        _seed_row(win, MDX_ARCH_TYPE, "Kept Model", checked=True)
        _seed_row(win, MDX_ARCH_TYPE, "Rehosted Copy", checked=True)

        win.manager.available_downloads.return_value = {MDX_ARCH_TYPE: ["Kept Model"]}
        win.manager.unsupported_downloads.return_value = {}
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()

        DownloadCenterWindow._flush_catalogue_row_refresh(win)

        win._update_download_button.assert_called_once_with()
        win._update_tab_counts.assert_called_once_with()
        # The surviving checkbox keeps its state: nothing rebuilt it.
        self.assertTrue(win._row_checks[(MDX_ARCH_TYPE, "Kept Model")].get_active())

    def test_no_op_when_nothing_was_dropped(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        _seed_row(win, MDX_ARCH_TYPE, "Kept Model")

        win.manager.available_downloads.return_value = {MDX_ARCH_TYPE: ["Kept Model"]}
        win.manager.unsupported_downloads.return_value = {}
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()

        DownloadCenterWindow._flush_catalogue_row_refresh(win)

        win._list_boxes[MDX_ARCH_TYPE].remove.assert_not_called()
        win._update_download_button.assert_not_called()


class DownloadCompletionRefreshTests(unittest.TestCase):
    def test_hidden_window_is_marked_dirty_without_touching_rows(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        win.window = mock.MagicMock()
        win.window.get_visible.return_value = False
        win._flush_catalogue_row_refresh = mock.MagicMock()

        DownloadCenterWindow.refresh_after_downloads(win)

        self.assertTrue(win._downloads_dirty)
        win._flush_catalogue_row_refresh.assert_not_called()

    def test_visible_window_uses_incremental_removal_not_rebuild(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        win.window = mock.MagicMock()
        win.window.get_visible.return_value = True
        win._flush_catalogue_row_refresh = mock.MagicMock()
        win._rebuild_catalogue = mock.MagicMock()

        DownloadCenterWindow.refresh_after_downloads(win)

        self.assertFalse(win._downloads_dirty)
        win._flush_catalogue_row_refresh.assert_called_once_with()
        win._rebuild_catalogue.assert_not_called()

    def test_present_consumes_hidden_window_dirty_marker(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        win.window = mock.MagicMock()
        win.browser.available = {MDX_ARCH_TYPE: ["Still available"]}
        win._downloads_dirty = True
        win._apply_download_completion_refresh = mock.MagicMock()
        win.start_refresh = mock.MagicMock()

        DownloadCenterWindow.present(win)

        win.window.present.assert_called_once_with()
        win._apply_download_completion_refresh.assert_called_once_with()
        win.start_refresh.assert_not_called()


class CatalogueListenerWiringTests(unittest.TestCase):
    def test_background_listeners_subscribe_to_the_manager(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()

        with mock.patch("core.catalogue_stem_cache.subscribe"), mock.patch(
            "core.catalogue_stem_cache.ensure_worker_started"
        ):
            DownloadCenterWindow._ensure_background_listeners(win)

        win.manager.subscribe_catalogue_changed.assert_called_once_with(
            win._schedule_catalogue_row_refresh
        )


class PinnedSnapshotDeltaTests(unittest.TestCase):
    def test_source_delta_marks_pending_without_rebuild(self) -> None:
        from core.catalogue_types import CatalogueDelta, DeltaKind
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        win.browser.pending_source = False
        win._rebuild_catalogue = mock.MagicMock()
        win._schedule_catalogue_row_refresh = mock.MagicMock()

        delta = CatalogueDelta(kind=DeltaKind.SOURCES_CHANGED, added={"mdx": ("New",)})
        DownloadCenterWindow._on_catalogue_delta(win, delta)

        self.assertTrue(win.browser.pending_source)
        win._rebuild_catalogue.assert_not_called()
        win._schedule_catalogue_row_refresh.assert_not_called()

    def test_identity_delta_uses_incremental_removal(self) -> None:
        from core.catalogue_types import CatalogueDelta, DeltaKind
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        win._schedule_catalogue_row_refresh = mock.MagicMock()
        delta = CatalogueDelta(
            kind=DeltaKind.IDENTITY_REFINED, removed={"mdx": ("Rehosted Copy",)}
        )
        DownloadCenterWindow._on_catalogue_delta(win, delta)
        win._schedule_catalogue_row_refresh.assert_called_once_with()

    def test_pin_uses_sole_public_snapshot(self) -> None:
        from ui.download_center import DownloadCenterWindow

        public = mock.MagicMock(name="public")
        public.revision.digest.return_value = "public"
        public.mdx = {
            "Public": {"p.ckpt": "https://u/p.ckpt"},
            "VIP": {"v.ckpt": "https://u/v.ckpt"},
        }
        coordinator = mock.MagicMock()
        coordinator._latest = public

        win = _bare_window()
        win.manager.latest_snapshot = public
        DownloadCenterWindow._pin_current_snapshot(win)
        self.assertIs(win.browser.snapshot, public)

    def test_queue_resolve_uses_pinned_snapshot_not_live_manager(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        win.browser.snapshot = mock.MagicMock()
        win.browser.snapshot.vr = {}
        win.browser.snapshot.mdx = {"Pinned": {"p.ckpt": "https://pin/p.ckpt"}}
        win.browser.snapshot.demucs = {}
        win.browser.snapshot.apollo = {}
        win.manager.mdx_download_list = {"Live": {"l.ckpt": "https://live/l.ckpt"}}
        win.manager.resolve.return_value = [("https://pin/p.ckpt", "/tmp/p.ckpt")]
        jobs = DownloadCenterWindow._resolve_pinned(win, "Pinned", MDX_ARCH_TYPE)
        win.manager.resolve.assert_called_once()
        kwargs = win.manager.resolve.call_args
        self.assertEqual(kwargs.kwargs.get("catalogue") or kwargs[1].get("catalogue"), {"Pinned": {"p.ckpt": "https://pin/p.ckpt"}})
        self.assertEqual(jobs, [("https://pin/p.ckpt", "/tmp/p.ckpt")])

    def test_present_adopts_pending_source_delta(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = _bare_window()
        win.window = mock.MagicMock()
        win.browser.available = {MDX_ARCH_TYPE: ["Still available"]}
        win.browser.pending_source = True
        win.start_refresh = mock.MagicMock()
        win._apply_download_completion_refresh = mock.MagicMock()
        DownloadCenterWindow.present(win)
        win.start_refresh.assert_called_once_with()
        win._apply_download_completion_refresh.assert_not_called()


class ComposedPublicJourneyTests(unittest.TestCase):
    """Pin and resolve against a real coordinator, not mocked snapshots."""

    _PAYLOAD = {
        "mdx_download_list": {"Public": {"p.ckpt": "https://u/p.ckpt"}},
        "mdx_download_vip_list": {
            "MDX-Net Model VIP: Added": "added.onnx"
        },
        "vr_download_list": {},
        "demucs_download_list": {},
    }

    def setUp(self) -> None:
        self.coordinator = _injected_coordinator(self._PAYLOAD)
        self.addCleanup(self.coordinator.close)
        self.policy = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        self.public = self.coordinator.snapshot(
            mode=RefreshMode.OFFLINE, policy=self.policy
        )
        self.manager = DownloadManager(self.coordinator)
        self.manager._apply_snapshot(self.public)

    def test_pin_and_resolve_uses_public_snapshot_for_former_vip(self) -> None:
        from ui.download_center import DownloadCenterWindow

        label = "MDX-Net Model VIP: Added"
        self.assertIn("Public", self.public.mdx)
        self.assertIn(label, self.public.mdx)
        self.assertIn(label, self.manager.mdx_download_list)

        win = _bare_window()
        win.manager = self.manager
        DownloadCenterWindow._pin_current_snapshot(win)
        self.assertIs(win.browser.snapshot, self.public)

        jobs = DownloadCenterWindow._resolve_pinned(win, label, MDX_ARCH_TYPE)
        self.assertEqual(
            jobs[0][0],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/added.onnx",
        )

    def test_enqueue_selected_queues_former_vip_from_public_snapshot(self) -> None:
        from ui.download_center import DownloadCenterWindow

        label = "MDX-Net Model VIP: Added"
        win = _bare_window()
        win.manager = self.manager
        _seed_row(win, MDX_ARCH_TYPE, label, checked=True)
        win.queue = mock.MagicMock()
        win.queue.active_item_id.return_value = None
        win.queue.enqueue.return_value = "item-1"
        win._toast = mock.MagicMock()
        win._update_download_button = mock.MagicMock()
        DownloadCenterWindow._pin_current_snapshot(win)
        DownloadCenterWindow._enqueue_selected(win)

        win.queue.enqueue.assert_called_once()
        args, kwargs = win.queue.enqueue.call_args
        self.assertEqual(args[0], label)
        self.assertEqual(args[1], MDX_ARCH_TYPE)
        jobs = kwargs.get("jobs") or (args[2] if len(args) > 2 else None)
        self.assertIsNotNone(jobs)
        assert jobs is not None
        self.assertEqual(
            jobs[0][0],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/added.onnx",
        )
        win._toast.assert_called_once()
        win._update_download_button.assert_called_once_with()

    def test_enqueue_selected_retains_the_row_display_label_in_the_real_queue(self) -> None:
        from core.download_queue import DownloadQueue
        from ui.download_center import DownloadCenterWindow
        from ui.widget_state import stash

        selection = "MDX-Net Model VIP: Added"
        display = "MDX-Net — Added"
        win = _bare_window()
        win.manager = self.manager
        action = _seed_row(win, MDX_ARCH_TYPE, selection, checked=True)
        stash(action, "_uvr_display_name", display)
        win.queue = DownloadQueue(self.manager)
        win.queue._ensure_worker = mock.MagicMock()
        win._toast = mock.MagicMock()
        win._update_download_button = mock.MagicMock()
        DownloadCenterWindow._pin_current_snapshot(win)

        DownloadCenterWindow._enqueue_selected(win)

        [item] = win.queue.items()
        self.assertEqual(item.selection, selection)
        self.assertEqual(item.label, display)

    def test_enqueue_selected_reports_model_that_is_already_active(self) -> None:
        from ui.download_center import DownloadCenterWindow

        label = "MDX-Net Model VIP: Added"
        win = _bare_window()
        win.manager = self.manager
        _seed_row(win, MDX_ARCH_TYPE, label, checked=True)
        win.queue = mock.MagicMock()
        win.queue.active_item_id.return_value = "active-item"
        win._toast = mock.MagicMock()
        win._update_download_button = mock.MagicMock()
        DownloadCenterWindow._pin_current_snapshot(win)

        DownloadCenterWindow._enqueue_selected(win)

        win.queue.enqueue.assert_not_called()
        win._toast.assert_called_once_with("1 download already queued")
        win._row_checks[(MDX_ARCH_TYPE, label)].set_active.assert_called_once_with(False)
        win._update_download_button.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
