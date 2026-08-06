"""`invalidate_models` has to be observable.

Two of its call sites are in `core/` with no path to the UI at all
(`update_model_settings`, and downloads' MDX-C registration), so without a
notification their effect only reaches the screen if some unrelated UI action
happens to refresh afterwards.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from core.model_data import ModelRepository


class ModelsChangedSubscriberTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = self._tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
        self.repo = ModelRepository()

    def test_every_subscriber_fires_once(self) -> None:
        calls: list[str] = []
        self.repo.subscribe_models_changed(lambda: calls.append("a"))
        self.repo.subscribe_models_changed(lambda: calls.append("b"))

        self.repo.invalidate_models()

        self.assertEqual(sorted(calls), ["a", "b"])

    def test_a_raising_subscriber_neither_blocks_the_next_nor_propagates(self) -> None:
        """Subscribers run on the download worker thread; one bad listener
        must not take the thread down mid-invalidation."""
        calls: list[str] = []

        def boom() -> None:
            raise RuntimeError("listener blew up")

        self.repo.subscribe_models_changed(boom)
        self.repo.subscribe_models_changed(lambda: calls.append("survivor"))

        self.repo.invalidate_models()

        self.assertEqual(calls, ["survivor"])

    def test_unsubscribe_removes(self) -> None:
        calls: list[str] = []

        def listener() -> None:
            calls.append("x")

        self.repo.subscribe_models_changed(listener)
        self.repo.unsubscribe_models_changed(listener)
        self.repo.invalidate_models()

        self.assertEqual(calls, [])

    def test_double_subscribe_is_idempotent(self) -> None:
        """A window re-registering on every refresh must not stack listeners."""
        calls: list[str] = []

        def listener() -> None:
            calls.append("x")

        for _ in range(4):
            self.repo.subscribe_models_changed(listener)
        self.repo.invalidate_models()

        self.assertEqual(calls, ["x"])

    def test_unsubscribing_an_unknown_listener_is_a_noop(self) -> None:
        self.repo.unsubscribe_models_changed(lambda: None)  # must not raise

    def test_a_subscriber_that_invalidates_does_not_recurse(self) -> None:
        calls: list[str] = []

        def reentrant() -> None:
            calls.append("x")
            self.repo.invalidate_models()

        self.repo.subscribe_models_changed(reentrant)
        self.repo.invalidate_models()

        self.assertEqual(calls, ["x"], "re-entrant invalidation must not renotify")


if __name__ == "__main__":
    unittest.main()
