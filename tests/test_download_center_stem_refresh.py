"""DownloadManager stem-cache patch and Download Center debounced subtitle flush."""

from __future__ import annotations

import typing
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

    def test_flush_preserves_stashed_download_size(self) -> None:
        from ui.widget_state import fetch, stash

        win = self._bare_window()
        win._stem_refresh_armed = True
        action = mock.MagicMock()
        stash(action, "_uvr_size", "12 MB")
        stash(action, "_uvr_sdr", None)
        stash(action, "_uvr_sdr_stem", None)
        stash(action, "_uvr_unsupported", False)
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

        with mock.patch("ui.download_center.set_row_subtitle") as set_subtitle:
            win._flush_stem_subtitles()

        subtitle = set_subtitle.call_args[0][1]
        self.assertIn("Vocals, other", subtitle)
        self.assertIn("12 MB", subtitle)
        self.assertEqual(fetch(action, "_uvr_stems_text"), "Vocals, other")

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
    def test_ensure_background_listeners_subscribes_and_starts_worker(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._stem_refresh_armed = False
        win.manager = mock.MagicMock()

        with mock.patch(
            "core.catalogue_stem_cache.subscribe"
        ) as subscribe, mock.patch(
            "core.catalogue_stem_cache.ensure_worker_started"
        ) as ensure:
            DownloadCenterWindow._ensure_background_listeners(win)

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
        win._ensure_background_listeners = mock.MagicMock()
        win._schedule_stem_yaml_fetches = mock.MagicMock()

        DownloadCenterWindow._refresh_done(win, True, {MDX_ARCH_TYPE: ["M"]}, {})

        win._ensure_background_listeners.assert_called_once_with()
        win._schedule_stem_yaml_fetches.assert_called_once_with()

    def test_schedule_coalesces_repeated_calls(self) -> None:
        """Every keystroke scans the whole catalogue twice on the main thread.

        Arming a single timeout means a burst of typing costs one scan, not one
        per character.
        """
        from ui.download_center import DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._stem_fetch_armed = False

        with mock.patch("gi.repository.GLib.timeout_add") as timeout_add:
            for _ in range(5):
                DownloadCenterWindow._schedule_stem_yaml_fetches(win)

        self.assertEqual(timeout_add.call_count, 1)
        callback = timeout_add.call_args[0][1]

        # Once the timeout fires the next burst must arm again.
        with mock.patch.object(win, "_visible_catalogue_labels", return_value=[]), (
            mock.patch.object(win, "_pending_stem_yaml_urls", return_value=[])
        ):
            self.assertFalse(callback())
        with mock.patch("gi.repository.GLib.timeout_add") as timeout_add2:
            DownloadCenterWindow._schedule_stem_yaml_fetches(win)
        self.assertEqual(timeout_add2.call_count, 1)

    def test_visible_labels_scoped_to_active_tab(self) -> None:
        """"Visible" must mean the tab on screen, not every tab's filter result."""
        from ui.download_center import PURPOSE_ALL, DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._available = {
            MDX_ARCH_TYPE: ["MDX Model"],
            "VR Arc": ["VR Model"],
        }
        win._search_entries = {}
        win._purpose = PURPOSE_ALL
        win.stack = mock.MagicMock()
        win.stack.get_visible_child_name.return_value = MDX_ARCH_TYPE

        self.assertEqual(win._visible_catalogue_labels(), ["MDX Model"])

    def test_visible_labels_fall_back_when_no_active_tab(self) -> None:
        from ui.download_center import PURPOSE_ALL, DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._available = {MDX_ARCH_TYPE: ["MDX Model"], "VR Arc": ["VR Model"]}
        win._search_entries = {}
        win._purpose = PURPOSE_ALL
        win.stack = mock.MagicMock()
        win.stack.get_visible_child_name.return_value = None

        self.assertEqual(
            sorted(win._visible_catalogue_labels()), ["MDX Model", "VR Model"]
        )

    def test_schedule_stem_yaml_fetches_prioritizes_visible(self) -> None:
        """Drive the real URL selection, not a scripted list of return values.

        Exercises `_yaml_config_url`, the already-has-stems skip, the stem-cache
        hit predicate and the visible/bulk split against real `catalogue_meta`
        and a real seeded stem cache. Only `enqueue_missing` /
        `ensure_worker_started` are stubbed — they are the boundary under test.
        """
        import os
        import tempfile

        import core.catalogue_stem_cache as csc
        from ui.download_center import PURPOSE_ALL, DownloadCenterWindow

        def meta_for(label: str, yaml_url: str | None, stems: list[str]) -> EntryMeta:
            files = {"m.ckpt": f"https://example.test/{label}.ckpt"}
            if yaml_url:
                files["m.yaml"] = yaml_url
            return EntryMeta(
                label=label,
                display=label,
                arch=MDX_ARCH_TYPE,
                files=files,
                stems=stems,
            )

        cached_url = "https://example.test/cached.yaml"
        catalogue_meta = {
            # Matches the "kim" query; needs a fetch.
            "Kim Vocal 1": meta_for("Kim Vocal 1", "https://example.test/kim.yaml", []),
            # Matches, but its stems are already known — must be skipped.
            "Kim Inst 2": meta_for("Kim Inst 2", "https://example.test/inst.yaml", ["Vocals"]),
            # Matches, but the stem cache already answers for it — must be skipped.
            "Kim Cached 3": meta_for("Kim Cached 3", cached_url, []),
            # Does not match the query, so it belongs in the bulk half.
            "Other Model": meta_for("Other Model", "https://example.test/other.yaml", []),
            # No YAML config at all — must never be enqueued.
            "No Yaml": meta_for("No Yaml", None, []),
        }

        class _Entry:
            def __init__(self, text: str) -> None:
                self._text = text

            def get_text(self) -> str:
                return self._text

        win = object.__new__(DownloadCenterWindow)
        win.manager = mock.MagicMock()
        win.manager.catalogue_meta = catalogue_meta
        win._available = {MDX_ARCH_TYPE: list(catalogue_meta)}
        # Stands in for a Gtk.SearchEntry, which needs a display to construct;
        # _visible_catalogue_labels only ever calls get_text() on it.
        win._search_entries = typing.cast(
            "dict[str, Any]", {MDX_ARCH_TYPE: _Entry("kim")}
        )
        win._purpose = PURPOSE_ALL
        win.stack = mock.MagicMock()
        win.stack.get_visible_child_name.return_value = MDX_ARCH_TYPE

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "catalogue_stem_cache.json")
            with mock.patch.object(csc, "_cache_path", return_value=cache_path):
                with mock.patch("core.model_display.clear_display_cache"):
                    csc.clear_catalogue_stem_cache()
                    csc.remember_stems(cached_url, ["Vocals", "other"], "Vocals", ok=True)
                    with mock.patch.object(csc, "enqueue_missing") as enqueue, (
                        mock.patch.object(csc, "ensure_worker_started")
                    ) as ensure:
                        DownloadCenterWindow._flush_stem_yaml_fetches(win)
                    csc.clear_catalogue_stem_cache()

        self.assertEqual(
            enqueue.call_args_list,
            [
                mock.call(["https://example.test/kim.yaml"], priority=True),
                mock.call(["https://example.test/other.yaml"], priority=False),
            ],
        )
        ensure.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
