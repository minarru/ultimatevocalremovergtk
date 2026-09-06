"""Real worker, coalesced GLib dispatch and rendered download completion."""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from typing import Any, Callable, cast
from unittest import mock

from tests.private_gtk import require_private_gtk


def setUpModule() -> None:
    # Run before any optional-display skip, so required private runs fail closed.
    require_private_gtk()


class DownloadQueueCompletionUiTests(unittest.TestCase):
    def test_worker_burst_coalesces_then_indicator_and_center_render_completion(self) -> None:
        try:
            import gi

            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Adw, Gdk, GLib, Gtk
        except (ImportError, ValueError) as exc:
            self.skipTest(f"GTK4/libadwaita unavailable: {exc}")

        from bundled.constants import MDX_ARCH_TYPE
        from core.catalog_sources import EntryMeta
        from core.catalogue_types import StemSemanticProjection
        from core.download_queue import DownloadQueue
        from core.download_status import RESULT_COMPLETE, STATUS_COMPLETE
        from core.downloads import DownloadManager
        from core.model_install import ModelInstallResult
        from core.settings import Settings
        from ui.download import init_download_queue_ui
        from ui.widgets.download_queue_indicator import DownloadQueueIndicator

        Gtk.init()
        if Gdk.Display.get_default() is None:
            self.skipTest("GTK widget construction needs a display")
        main_thread = threading.get_ident()
        burst_ready = threading.Event()
        release = threading.Event()
        transferred = threading.Event()
        installed = threading.Event()
        worker_threads: list[int] = []
        transfer_threads: list[threading.Thread] = []
        observed: list[tuple[int, float, str]] = []

        def drain_until(predicate: Callable[[], bool]) -> None:
            deadline = time.monotonic() + 8
            context = GLib.MainContext.default()
            while not predicate():
                self.assertLess(
                    time.monotonic(),
                    deadline,
                    f"GTK predicate timed out: {labels(center.window) if center else []}",
                )
                context.iteration(False)
                threading.Event().wait(0.001)

        def labels(widget: Gtk.Widget) -> list[str]:
            result = [widget.get_label()] if isinstance(widget, Gtk.Label) else []
            child = widget.get_first_child()
            while child is not None:
                result.extend(labels(child))
                child = child.get_next_sibling()
            return result

        def download(
            jobs: list[Any],
            *,
            on_progress: Callable[[float], None],
            on_info: Callable[[str], None],
            stop_event: threading.Event,
        ) -> str:
            worker_threads.append(threading.get_ident())
            transfer_threads.append(threading.current_thread())
            try:
                for index in range(1, 9):
                    on_progress(index / 10)
                    on_info(f"fixture burst {index}")
                burst_ready.set()
                if not release.wait(8):
                    raise AssertionError("fixture transfer was not released")
                if stop_event.is_set():
                    raise AssertionError("fixture transfer unexpectedly cancelled")
                installed.set()
                return RESULT_COMPLETE
            finally:
                transferred.set()

        manager = DownloadManager()
        meta = EntryMeta(
            "Fixture Vocals",
            "Fixture Vocals",
            MDX_ARCH_TYPE,
            files={"fixture.onnx": "https://example.test/fixture.onnx"},
            intent="vocals",
            stems=["Vocals", "Instrumental"],
            stem_semantics=StemSemanticProjection(
                backend_primary_stem="Vocals",
                backend_target_stem="Vocals",
                logical_primary_role="vocals",
                logical_secondary_role="instrumental",
                status="reviewed",
                context="full_mix",
                routes=(),
            ),
        )
        manager.mdx_download_list = {meta.label: meta.files}
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        queue = DownloadQueue(manager, repo=SimpleNamespace())
        context = SimpleNamespace(
            settings=Settings.defaults(), download_manager=manager, download_queue=queue
        )
        context.settings.process.auto_update_model_params = False

        class Parent(Adw.Window):
            def __init__(self) -> None:
                super().__init__()
                self._download_ui: Any = None
                self._download_queue_indicator = DownloadQueueIndicator()
                self.toast_overlay = Adw.ToastOverlay()
                self.toast_overlay.set_child(self._download_queue_indicator.widget)
                self.set_content(self.toast_overlay)

        parent = Parent()
        parent.present()
        binding: Any = None
        center: Any = None
        try:
            with (
                mock.patch.object(manager, "refresh", return_value=True),
                mock.patch.object(manager, "ensure_catalogues", return_value=True),
                mock.patch("core.model_scores._fetch_model_scores", return_value={}),
                mock.patch.object(
                    manager,
                    "available_downloads",
                    side_effect=lambda: {MDX_ARCH_TYPE: [] if installed.is_set() else [meta.label]},
                ),
                mock.patch.object(manager, "unsupported_downloads", return_value={}),
                mock.patch.object(manager, "describe_selection_download_size", return_value=""),
                mock.patch.object(manager, "queue_catalogue_evidence", return_value=()),
                mock.patch("core.catalogue_stem_cache.ensure_worker_started"),
                mock.patch.object(manager, "download", side_effect=download),
                mock.patch(
                    "core.model_install.finalize_downloaded_model",
                    return_value=ModelInstallResult(ready=True, published=False),
                ) as finalize,
            ):
                indicator = init_download_queue_ui(cast(Any, parent), cast(Any, context))
                binding = parent._download_ui
                center = binding.present_center()
                drain_until(lambda: "Fixture Vocals" in labels(center.window))
                drain_until(lambda: not GLib.MainContext.default().pending())
                original_refresh = indicator.refresh

                def observe() -> None:
                    original_refresh()
                    items = queue.items()
                    if items:
                        observed.append((threading.get_ident(), items[0].progress, items[0].detail))

                with (
                    mock.patch.object(indicator, "refresh", side_effect=observe),
                    mock.patch.object(
                        center, "refresh_after_downloads", wraps=center.refresh_after_downloads
                    ) as center_refresh,
                ):
                    item_id = queue.enqueue(
                        meta.label,
                        MDX_ARCH_TYPE,
                        [("https://example.test/fixture.onnx", "/unused/fixture.onnx")],
                    )
                    self.assertIsNotNone(item_id)
                    self.assertTrue(burst_ready.wait(8), "worker burst timed out")
                    # No main-context iteration between enqueue and this barrier.
                    drain_until(lambda: bool(observed) and observed[-1][2] == "fixture burst 8")
                    self.assertEqual(observed, [(main_thread, 0.8, "fixture burst 8")])
                    release.set()
                    drain_until(
                        lambda: (
                            queue.active_count() == 0
                            and "Downloaded 1 model" in labels(indicator.widget)
                            and "0 vocals models" in labels(center.window)
                        )
                    )
                    self.assertEqual(queue.items()[0].status, STATUS_COMPLETE)
                    self.assertEqual(worker_threads, [transfer_threads[0].ident])
                    self.assertNotEqual(worker_threads[0], main_thread)
                    self.assertTrue(all(thread == main_thread for thread, _, _ in observed))
                    center_refresh.assert_called_once_with()
                    popover = indicator.widget.get_popover()
                    assert popover is not None
                    self.assertIn("Fixture Vocals", labels(popover))
                    self.assertNotIn("Fixture Vocals", labels(center.window))
                    finalize.assert_called_once()
                    self.assertEqual(finalize.call_args.kwargs["selection"], meta.label)
                    self.assertEqual(finalize.call_args.kwargs["transfer_result"], RESULT_COMPLETE)
        finally:
            release.set()
            if queue.active_count():
                queue.cancel_all()
            for thread in transfer_threads:
                thread.join(8)
                self.assertFalse(thread.is_alive(), "queue worker leaked")
            if binding is not None:
                binding.dispose()
            if center is not None:
                center.window.set_visible(False)
            parent.set_visible(False)
        self.assertTrue(transferred.is_set())
