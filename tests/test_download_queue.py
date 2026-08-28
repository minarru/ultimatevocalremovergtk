"""Tests for the background download queue."""
import typing

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

from bundled.constants import MDX_ARCH_TYPE
from core.download_queue import DownloadQueue


class DownloadQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = MagicMock()
        self.manager.resolve.return_value = [
            ("https://example.com/a.onnx", os.path.join(tempfile.gettempdir(), "a.onnx")),
        ]
        self.manager.download.return_value = "complete"
        self.updates = 0
        self.queue = DownloadQueue(
            self.manager,
            on_changed=lambda: setattr(self, "updates", self.updates + 1),
        )

    def test_enqueue_starts_worker(self) -> None:
        item_id = self.queue.enqueue("Test Model", "MDX-Net")
        self.assertIsNotNone(item_id)
        deadline = threading.Event()

        def wait_done():
            for _ in range(100):
                if self.queue.active_count() == 0:
                    deadline.set()
                    return
                threading.Event().wait(0.05)
            deadline.set()

        threading.Thread(target=wait_done, daemon=True).start()
        deadline.wait(timeout=5)
        items = self.queue.items()
        self.assertEqual(len(items), 1)
        self.assertIn(items[0].status, ("complete", "failed", "cancelled", "exists"))

    def test_enqueue_many(self) -> None:
        ids = self.queue.enqueue_many([("A", "VR Arch"), ("B", "MDX-Net")])
        self.assertEqual(len(ids), 2)

    def test_cancel_queued_item_keeps_terminal_detail(self) -> None:
        from core.download_status import STATUS_CANCELLED, default_detail_for_status

        started = threading.Event()
        release = threading.Event()

        def blocking_download(jobs: typing.Any, **kwargs: typing.Any):
            started.set()
            release.wait(timeout=5)
            return "complete"

        self.manager.download.side_effect = blocking_download
        self.queue.enqueue("First", "MDX-Net")
        started.wait(timeout=5)
        second_id = self.queue.enqueue("Second", "MDX-Net")
        assert second_id is not None

        # Second item is still STATUS_QUEUED (worker is busy on the first).
        self.queue.cancel(second_id)
        items = {item.item_id: item for item in self.queue.items()}
        self.assertEqual(items[second_id].status, STATUS_CANCELLED)
        self.assertEqual(
            items[second_id].detail, default_detail_for_status(STATUS_CANCELLED)
        )

        release.set()

    def test_cancel_all_cancels_queued_and_signals_current_download(self) -> None:
        from core.download_status import STATUS_CANCELLED, STATUS_DOWNLOADING

        started = threading.Event()
        release = threading.Event()

        def blocking_download(jobs: typing.Any, **kwargs: typing.Any):
            started.set()
            release.wait(timeout=5)
            return "stopped"

        self.manager.download.side_effect = blocking_download
        first_id = self.queue.enqueue("First", "MDX-Net")
        self.assertTrue(started.wait(timeout=5))
        second_id = self.queue.enqueue("Second", "MDX-Net")

        self.assertEqual(self.queue.cancel_all(), 2)
        items = {item.item_id: item for item in self.queue.items()}
        assert first_id is not None and second_id is not None
        self.assertEqual(items[first_id].status, STATUS_DOWNLOADING)
        self.assertTrue(items[first_id].stop_event.is_set())
        self.assertEqual(items[first_id].detail, "Cancelling…")
        self.assertEqual(items[second_id].status, STATUS_CANCELLED)
        self.assertEqual(self.queue.active_count(), 1)

        release.set()
        for _ in range(100):
            if self.queue.active_count() == 0:
                break
            threading.Event().wait(0.01)
        self.assertEqual(self.queue.active_count(), 0)

    def test_ensure_worker_never_double_starts(self) -> None:
        spawn_count = {"n": 0}
        barrier = threading.Barrier(20)

        def fake_worker_main() -> None:
            spawn_count["n"] += 1
            threading.Event().wait(0.05)
            with self.queue._lock:
                self.queue._worker_active = False

        self.queue._worker_main = fake_worker_main  # type: ignore[method-assign]

        def call_ensure() -> None:
            barrier.wait()
            self.queue._ensure_worker()

        threads = [threading.Thread(target=call_ensure) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        threading.Event().wait(0.2)
        self.assertEqual(spawn_count["n"], 1)


if __name__ == "__main__":
    unittest.main()


class QueuePublicationTests(unittest.TestCase):
    """Each logical model publishes as it becomes usable, not per batch."""

    def _queue(self, results: list[str]):
        from core.download_queue import DownloadQueue

        manager = mock.MagicMock()
        manager.download.side_effect = list(results)
        repo = mock.MagicMock()
        return DownloadQueue(manager, repo=repo), repo

    def _item(self, queue: typing.Any, selection: str = "MDX-Net Model: A"):
        from core.download_queue import DownloadQueueItem

        return DownloadQueueItem(
            item_id=selection,
            selection=selection,
            arch_type=MDX_ARCH_TYPE,
            label=selection,
            jobs=[("u", "/tmp/does-not-matter.onnx")],
        )

    def test_finalizer_runs_once_per_successful_item(self) -> None:
        from core.download_queue import DownloadQueue
        from core.model_install import ModelInstallResult

        queue, repo = self._queue(["complete"])
        item = self._item(queue)

        with mock.patch(
            "core.model_install.finalize_downloaded_model",
            return_value=ModelInstallResult(ready=True, published=True),
        ) as finalize:
            DownloadQueue._process_item(queue, item)

        finalize.assert_called_once()
        kwargs = finalize.call_args.kwargs
        self.assertEqual(kwargs["family"], "mdx")
        self.assertEqual(kwargs["selection"], "MDX-Net Model: A")
        self.assertEqual(kwargs["transfer_result"], "complete")
        self.assertEqual(kwargs["repo"], repo)

    def test_queue_records_item_lifecycle_with_one_operation_id(self) -> None:
        from core import debug_log
        from core.download_queue import DownloadQueue
        from core.model_install import ModelInstallResult

        queue, _repo = self._queue(["complete"])
        item = self._item(queue)
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="debug", log_file=str(log_path))
            self.addCleanup(debug_log.configure, level="errors", log_file="")
            with mock.patch(
                "core.model_install.finalize_downloaded_model",
                return_value=ModelInstallResult(ready=True, published=True),
            ):
                DownloadQueue._process_item(queue, item)

            lines = log_path.read_text(encoding="utf-8").splitlines()
            started = next(line for line in lines if "event=download_item_started" in line)
            completed = next(line for line in lines if "event=download_item_completed" in line)
            operation = f"operation=download-{item.item_id}"
            self.assertIn(operation, started)
            self.assertIn(operation, completed)

    def test_each_of_two_items_gets_its_own_publication(self) -> None:
        from core.download_queue import DownloadQueue
        from core.model_install import ModelInstallResult

        queue, _repo = self._queue(["complete", "complete"])
        first = self._item(queue, "MDX-Net Model: A")
        second = self._item(queue, "MDX-Net Model: B")

        with mock.patch(
            "core.model_install.finalize_downloaded_model",
            return_value=ModelInstallResult(ready=True, published=True),
        ) as finalize:
            DownloadQueue._process_item(queue, first)
            self.assertEqual(finalize.call_count, 1)  # before the second starts
            DownloadQueue._process_item(queue, second)

        self.assertEqual(finalize.call_count, 2)

    def test_a_stopped_transfer_never_finalizes(self) -> None:
        from core.download_queue import DownloadQueue

        queue, _repo = self._queue(["stopped"])
        item = self._item(queue)
        item.stop_event.set()

        with mock.patch("core.model_install.finalize_downloaded_model") as finalize:
            DownloadQueue._process_item(queue, item)

        finalize.assert_not_called()

    def test_a_failed_transfer_never_finalizes(self) -> None:
        from core.download_queue import DownloadQueue

        queue, _repo = self._queue([])
        queue.manager.download.side_effect = RuntimeError("boom")
        item = self._item(queue)

        with mock.patch("core.model_install.finalize_downloaded_model") as finalize:
            DownloadQueue._process_item(queue, item)

        finalize.assert_not_called()

    def test_an_unusable_result_fails_the_item_with_its_detail(self) -> None:
        from core.download_queue import DownloadQueue
        from core.download_status import STATUS_FAILED
        from core.model_install import ModelInstallResult

        queue, _repo = self._queue(["complete"])
        item = self._item(queue)

        with mock.patch(
            "core.model_install.finalize_downloaded_model",
            return_value=ModelInstallResult(
                ready=False, published=False, detail="missing config.yaml"
            ),
        ):
            ok = DownloadQueue._process_item(queue, item)

        self.assertFalse(ok)
        self.assertEqual(item.status, STATUS_FAILED)
        self.assertEqual(item.detail, "missing config.yaml")

    def test_a_finalizer_exception_fails_only_that_item(self) -> None:
        from core.download_queue import DownloadQueue
        from core.download_status import STATUS_FAILED

        queue, _repo = self._queue(["complete"])
        item = self._item(queue)

        with mock.patch(
            "core.model_install.finalize_downloaded_model",
            side_effect=RuntimeError("registry exploded"),
        ):
            ok = DownloadQueue._process_item(queue, item)

        self.assertFalse(ok)
        self.assertEqual(item.status, STATUS_FAILED)
        self.assertIn("registry exploded", item.detail)

    def test_download_is_called_without_a_repository(self) -> None:
        from core.download_queue import DownloadQueue
        from core.model_install import ModelInstallResult

        queue, _repo = self._queue(["complete"])
        item = self._item(queue)

        with mock.patch(
            "core.model_install.finalize_downloaded_model",
            return_value=ModelInstallResult(ready=True, published=True),
        ):
            DownloadQueue._process_item(queue, item)

        self.assertNotIn("repo", queue.manager.download.call_args.kwargs)


class DownloadUiInterfaceTests(unittest.TestCase):
    """Batch completion is aggregate UI; it owns no model publication.

    The `on_models_changed` parameter existed so a finished batch could refresh
    the pickers once, late. Publication is now per item, so the parameter is
    gone and the repository event is the only refresh source.
    """

    def test_no_ui_entry_point_accepts_a_models_changed_callback(self) -> None:
        import inspect

        from ui.download import init_download_queue_ui, open_download_center
        from ui.download_center import DownloadCenterWindow

        for func in (init_download_queue_ui, open_download_center,
                     DownloadCenterWindow.__init__):
            with self.subTest(entry=getattr(func, "__qualname__", func)):
                self.assertNotIn(
                    "on_models_changed", inspect.signature(func).parameters
                )

    def test_batch_completion_does_not_invalidate(self) -> None:
        """No invalidation call survives anywhere in the batch UI path."""
        import inspect

        from ui import download as download_mod

        source = inspect.getsource(download_mod)
        self.assertNotIn("invalidate_models", source)
        self.assertNotIn("invalidate_model_presentation", source)
        self.assertNotIn("on_models_changed", source)
