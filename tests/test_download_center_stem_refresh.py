"""DownloadManager stem-cache patch and Download Center debounced subtitle flush."""

from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE
from core.catalog_sources import EntryMeta
from core.catalogue_stem_cache import StemCacheHit
from core.downloads import DownloadManager


_YAML_URL = "https://example.test/model.yaml"


class ApplyCatalogueStemCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = DownloadManager.__new__(DownloadManager)
        self.manager.catalogue_meta = {}

    def test_patches_empty_stems_from_cache(self) -> None:
        meta = EntryMeta(
            label="M",
            display="M",
            arch=MDX_ARCH_TYPE,
            files={"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL},
            stems=[],
        )
        self.manager.catalogue_meta = {"M": meta}
        hit = StemCacheHit(
            stems=("Vocals", "other"),
            target_instrument="Vocals",
            ok=True,
        )
        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            updated = self.manager.apply_catalogue_stem_cache()

        self.assertEqual(updated, {"M"})
        patched = self.manager.catalogue_meta["M"]
        self.assertEqual(patched.stems, ["Vocals", "other"])
        self.assertEqual(patched.target_instrument, "Vocals")

    def test_skips_when_stems_already_set(self) -> None:
        meta = EntryMeta(
            label="M",
            display="M",
            arch=MDX_ARCH_TYPE,
            files={"m.yaml": _YAML_URL},
            stems=["Drums"],
            target_instrument="Drums",
        )
        self.manager.catalogue_meta = {"M": meta}
        with mock.patch("core.catalogue_stem_cache.lookup_stems") as lookup:
            updated = self.manager.apply_catalogue_stem_cache()
        self.assertEqual(updated, set())
        lookup.assert_not_called()

    def test_skips_without_yaml_url(self) -> None:
        meta = EntryMeta(
            label="M",
            display="M",
            arch=MDX_ARCH_TYPE,
            files={"m.ckpt": "https://example.test/m.ckpt"},
            stems=[],
        )
        self.manager.catalogue_meta = {"M": meta}
        with mock.patch("core.catalogue_stem_cache.lookup_stems") as lookup:
            updated = self.manager.apply_catalogue_stem_cache()
        self.assertEqual(updated, set())
        lookup.assert_not_called()

    def test_preserves_existing_target_instrument(self) -> None:
        meta = EntryMeta(
            label="M",
            display="M",
            arch=MDX_ARCH_TYPE,
            files={"m.yaml": _YAML_URL},
            stems=[],
            target_instrument="Bass",
        )
        self.manager.catalogue_meta = {"M": meta}
        hit = StemCacheHit(stems=("Vocals", "other"), target_instrument="Vocals", ok=True)
        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            self.manager.apply_catalogue_stem_cache()
        self.assertEqual(self.manager.catalogue_meta["M"].target_instrument, "Bass")


class StemSubtitleDebounceTests(unittest.TestCase):
    def _bare_window(self) -> Any:
        from core.model_scores import PURPOSE_ALL, SORT_NAME
        from ui.download_center import DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win.manager = mock.MagicMock()
        win._stem_refresh_armed = False
        win._row_checks = {}
        win._row_actions = {}
        return win

    def test_multiple_notifies_arm_one_timeout(self) -> None:
        win = self._bare_window()
        timeout_calls: list[tuple[int, Any]] = []

        def fake_timeout_add(ms: int, cb: Any) -> int:
            timeout_calls.append((ms, cb))
            return len(timeout_calls)

        with mock.patch("gi.repository.GLib.timeout_add", side_effect=fake_timeout_add):
            with mock.patch("ui.download_center.idle_on_main", side_effect=lambda fn: fn()):
                for _ in range(5):
                    win._schedule_stem_subtitle_refresh()

        self.assertTrue(win._stem_refresh_armed)
        self.assertEqual(len(timeout_calls), 1)
        self.assertEqual(timeout_calls[0][0], 200)

    def test_flush_clears_arm_and_updates_subtitles(self) -> None:
        win = self._bare_window()
        win._stem_refresh_armed = True
        action = mock.MagicMock()
        win._row_actions[(MDX_ARCH_TYPE, "M")] = action
        win.manager.apply_catalogue_stem_cache.return_value = {"M"}
        win.manager.catalogue_meta = {
            "M": EntryMeta(
                label="M",
                display="M",
                arch=MDX_ARCH_TYPE,
                files={},
                stems=["Vocals", "other"],
            )
        }

        with mock.patch("ui.download_center.stash"), mock.patch(
            "ui.download_center.fetch", side_effect=lambda _row, key, default=None: default
        ), mock.patch("ui.download_center.set_row_subtitle") as set_subtitle:
            result = win._flush_stem_subtitles()

        self.assertFalse(result)
        self.assertFalse(win._stem_refresh_armed)
        set_subtitle.assert_called_once()
        args = set_subtitle.call_args[0]
        self.assertIn("Vocals, other", args[1])

    def test_schedule_hops_to_main_via_idle_on_main(self) -> None:
        win = self._bare_window()
        idle_calls: list[Any] = []

        def fake_idle(fn: Any, *args: Any, **kwargs: Any) -> None:
            idle_calls.append(fn)

        with mock.patch("ui.download_center.idle_on_main", side_effect=fake_idle):
            win._schedule_stem_subtitle_refresh()

        self.assertEqual(len(idle_calls), 1)
        self.assertEqual(idle_calls[0], win._arm_stem_subtitle_refresh)


class DownloadCenterStemSubscriptionTests(unittest.TestCase):
    def test_ensure_stem_cache_listener_subscribes_and_starts_worker(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._stem_refresh_armed = False

        with mock.patch(
            "core.catalogue_stem_cache.subscribe"
        ) as subscribe, mock.patch(
            "core.catalogue_stem_cache.ensure_worker_started"
        ) as ensure:
            DownloadCenterWindow._ensure_stem_cache_listener(win)

        subscribe.assert_called_once_with(win._schedule_stem_subtitle_refresh)
        ensure.assert_called_once_with()

    def test_refresh_done_wires_listener_when_online(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._refreshing = True
        win.refresh_button = mock.MagicMock()
        win._refresh_spinner = mock.MagicMock()
        win.status_label = mock.MagicMock()
        win.download_button = mock.MagicMock()
        win._rebuild_catalogue = mock.MagicMock()
        win._update_tab_counts = mock.MagicMock()
        win._update_status_from_catalogue = mock.MagicMock()
        win._update_download_button = mock.MagicMock()
        win._ensure_stem_cache_listener = mock.MagicMock()

        DownloadCenterWindow._refresh_done(win, True, {MDX_ARCH_TYPE: ["M"]}, {})

        win._ensure_stem_cache_listener.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
