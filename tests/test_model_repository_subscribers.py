"""`invalidate_models` has to be observable.

Two of its call sites are in `core/` with no path to the UI at all
(`update_model_settings`, and downloads' MDX-C registration), so without a
notification their effect only reaches the screen if some unrelated UI action
happens to refresh afterwards.
"""

from __future__ import annotations

import os
import tempfile
import typing
import unittest

from core.model_repository import ModelRepository


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


class ModelPresentationChangedSubscriberTests(unittest.TestCase):
    """`model_presentation_changed` mirrors the `models_changed` contract.

    A label/catalogue refinement must repaint the pickers without staling
    resolved plans, so it needs its own event rather than reusing the full
    inventory one.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = self._tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
        self.repo = ModelRepository()

    def test_every_subscriber_fires_once(self) -> None:
        calls: list[str] = []
        self.repo.subscribe_model_presentation_changed(lambda: calls.append("a"))
        self.repo.subscribe_model_presentation_changed(lambda: calls.append("b"))

        self.repo.invalidate_model_presentation()

        self.assertEqual(sorted(calls), ["a", "b"])

    def test_double_subscribe_is_idempotent(self) -> None:
        calls: list[str] = []

        def listener() -> None:
            calls.append("x")

        self.repo.subscribe_model_presentation_changed(listener)
        self.repo.subscribe_model_presentation_changed(listener)
        self.repo.invalidate_model_presentation()

        self.assertEqual(calls, ["x"])

    def test_unsubscribe_removes(self) -> None:
        calls: list[str] = []

        def listener() -> None:
            calls.append("x")

        self.repo.subscribe_model_presentation_changed(listener)
        self.repo.unsubscribe_model_presentation_changed(listener)
        self.repo.invalidate_model_presentation()

        self.assertEqual(calls, [])

    def test_unsubscribing_an_unknown_listener_is_a_noop(self) -> None:
        self.repo.unsubscribe_model_presentation_changed(lambda: None)

    def test_a_raising_subscriber_neither_blocks_the_next_nor_propagates(self) -> None:
        calls: list[str] = []

        def boom() -> None:
            calls.append("boom")
            raise RuntimeError("listener blew up")

        self.repo.subscribe_model_presentation_changed(boom)
        self.repo.subscribe_model_presentation_changed(lambda: calls.append("after"))

        self.repo.invalidate_model_presentation()

        self.assertEqual(calls, ["boom", "after"])

    def test_a_subscriber_that_invalidates_does_not_recurse(self) -> None:
        calls: list[str] = []

        def reentrant() -> None:
            calls.append("x")
            if len(calls) < 5:
                self.repo.invalidate_model_presentation()

        self.repo.subscribe_model_presentation_changed(reentrant)
        self.repo.invalidate_model_presentation()

        self.assertEqual(calls, ["x"])

    def test_full_invalidation_does_not_emit_the_presentation_event(self) -> None:
        events: list[str] = []
        self.repo.subscribe_models_changed(lambda: events.append("models"))
        self.repo.subscribe_model_presentation_changed(
            lambda: events.append("presentation")
        )

        self.repo.invalidate_models()

        self.assertEqual(events, ["models"])

    def test_presentation_invalidation_does_not_emit_the_inventory_event(self) -> None:
        events: list[str] = []
        self.repo.subscribe_models_changed(lambda: events.append("models"))
        self.repo.subscribe_model_presentation_changed(
            lambda: events.append("presentation")
        )

        self.repo.invalidate_model_presentation()

        self.assertEqual(events, ["presentation"])


class ModelPresentationInvalidationBoundaryTests(unittest.TestCase):
    """Presentation invalidation clears labels, never execution state."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = self._tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
        self.repo = ModelRepository()

    def _seed(self) -> None:
        self.repo._identity_cache_key = (0, "x", 0)
        self.repo._identity_cache = object()  # type: ignore[assignment]
        self.repo.model_hash_table["sentinel"] = "hash"
        self.repo._stem_check_cache = ("key", ["cfg"])  # type: ignore[assignment]
        self.repo._karaoke_cache = (("a",), ["b"])

    def test_clears_identity_projection_only(self) -> None:
        self._seed()
        hash_table = self.repo.model_hash_table
        stem_cache = self.repo._stem_check_cache
        karaoke_cache = self.repo._karaoke_cache
        generation = self.repo.inventory_generation
        naming = self.repo.naming_revision

        self.repo.invalidate_model_presentation(reload_mappers=False)

        self.assertIsNone(self.repo._identity_cache_key)
        self.assertIsNone(self.repo._identity_cache)
        self.assertEqual(self.repo.inventory_generation, generation)
        self.assertEqual(self.repo.naming_revision, naming)
        self.assertIs(self.repo.model_hash_table, hash_table)
        self.assertEqual(self.repo.model_hash_table.get("sentinel"), "hash")
        self.assertIs(self.repo._stem_check_cache, stem_cache)
        self.assertIs(self.repo._karaoke_cache, karaoke_cache)

    def test_does_not_touch_the_hash_table_provider(self) -> None:
        calls: list[str] = []

        def provider():
            calls.append("provider")
            return {}

        self.repo.bind_model_hash_table(provider)
        calls.clear()

        self.repo.invalidate_model_presentation(reload_mappers=False)

        self.assertEqual(calls, [])

    def test_fires_the_presentation_event_exactly_once(self) -> None:
        calls: list[str] = []
        self.repo.subscribe_model_presentation_changed(lambda: calls.append("x"))

        self.repo.invalidate_model_presentation(reload_mappers=False)

        self.assertEqual(calls, ["x"])

    def test_mapper_variant_bumps_naming_revision_only(self) -> None:
        self._seed()
        hash_table = self.repo.model_hash_table
        stem_cache = self.repo._stem_check_cache
        karaoke_cache = self.repo._karaoke_cache
        generation = self.repo.inventory_generation
        naming = self.repo.naming_revision
        vr_hashes = self.repo.vr_hash_MAPPER
        mdx_hashes = self.repo.mdx_hash_MAPPER

        self.repo.invalidate_model_presentation(reload_mappers=True)

        self.assertEqual(self.repo.naming_revision, naming + 1)
        self.assertEqual(self.repo.inventory_generation, generation)
        self.assertIs(self.repo.model_hash_table, hash_table)
        self.assertIs(self.repo._stem_check_cache, stem_cache)
        self.assertIs(self.repo._karaoke_cache, karaoke_cache)
        # Hash maps are execution data, not presentation data.
        self.assertIs(self.repo.vr_hash_MAPPER, vr_hashes)
        self.assertIs(self.repo.mdx_hash_MAPPER, mdx_hashes)

    def test_name_mapper_reload_is_the_only_reload(self) -> None:
        calls: list[str] = []
        self.repo._reload_hash_mappers = lambda: calls.append("hash")  # type: ignore[method-assign]
        self.repo._reload_name_mappers = lambda: calls.append("name")  # type: ignore[method-assign]

        self.repo.invalidate_model_presentation(reload_mappers=True)

        self.assertEqual(calls, ["name"])


class _FakeCoordinator:
    """Minimal stand-in exposing only the delta contract the repository uses."""

    def __init__(self) -> None:
        self.delta_subscribers: list = []
        self.snapshot_calls = 0
        self.revision = "rev-1"

    def subscribe_delta(self, callback: typing.Any) -> None:
        if callback not in self.delta_subscribers:
            self.delta_subscribers.append(callback)

    def unsubscribe_delta(self, callback: typing.Any) -> None:
        try:
            self.delta_subscribers.remove(callback)
        except ValueError:
            pass

    def snapshot(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        self.snapshot_calls += 1
        return None

    def emit(self, kind: typing.Any) -> None:
        from core.catalogue_types import CatalogueDelta

        delta = CatalogueDelta(kind=kind)
        for callback in list(self.delta_subscribers):
            callback(delta)


class CatalogueDeltaBridgeTests(unittest.TestCase):
    """Catalogue refinements reach the pickers as presentation events.

    A catalogue that learns a friendlier label, or that gains/loses the exact
    association an installed record projects from, changes only what the user
    reads. It must repaint without staling a resolved plan.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        os.environ["UVR_DATA_DIR"] = self._tmp.name
        self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
        self.coordinator = _FakeCoordinator()
        self.repo = ModelRepository(catalogue=self.coordinator)
        self.events: list[str] = []
        self.repo.subscribe_models_changed(lambda: self.events.append("models"))
        self.repo.subscribe_model_presentation_changed(
            lambda: self.events.append("presentation")
        )

    def test_construction_subscribes_exactly_once(self) -> None:
        self.assertEqual(len(self.coordinator.delta_subscribers), 1)

    def test_sources_changed_emits_one_presentation_event(self) -> None:
        from core.catalogue_types import DeltaKind

        self.coordinator.emit(DeltaKind.SOURCES_CHANGED)

        self.assertEqual(self.events, ["presentation"])

    def test_identity_refined_emits_one_presentation_event(self) -> None:
        from core.catalogue_types import DeltaKind

        self.coordinator.emit(DeltaKind.IDENTITY_REFINED)

        self.assertEqual(self.events, ["presentation"])

    def test_metadata_changed_emits_nothing(self) -> None:
        """Stem subtitles are not model labels."""
        from core.catalogue_types import DeltaKind

        self.coordinator.emit(DeltaKind.METADATA_CHANGED)

        self.assertEqual(self.events, [])

    def test_bridge_does_not_reload_name_mappers(self) -> None:
        from core.catalogue_types import DeltaKind

        naming = self.repo.naming_revision
        self.coordinator.emit(DeltaKind.SOURCES_CHANGED)

        self.assertEqual(self.repo.naming_revision, naming)

    def test_bridge_does_not_increment_inventory_generation(self) -> None:
        from core.catalogue_types import DeltaKind

        generation = self.repo.inventory_generation
        self.coordinator.emit(DeltaKind.SOURCES_CHANGED)
        self.coordinator.emit(DeltaKind.IDENTITY_REFINED)

        self.assertEqual(self.repo.inventory_generation, generation)

    def test_bridge_does_not_pull_a_snapshot(self) -> None:
        """The coordinator already published; re-meshing here would be a fetch."""
        from core.catalogue_types import DeltaKind

        self.coordinator.emit(DeltaKind.SOURCES_CHANGED)

        self.assertEqual(self.coordinator.snapshot_calls, 0)

    def test_full_invalidation_remains_a_separate_event(self) -> None:
        self.repo.invalidate_models()

        self.assertEqual(self.events, ["models"])

    def test_coordinator_shutdown_owns_callback_release(self) -> None:
        """No repository `close()` exists; the coordinator drops the callback.

        `CatalogueCoordinator.close()` clears its own subscriber list, so the
        bridge is released without adding a second lifecycle owner.
        """
        self.assertEqual(len(self.coordinator.delta_subscribers), 1)

        self.coordinator.delta_subscribers.clear()  # what close() does
        from core.catalogue_types import DeltaKind

        self.coordinator.emit(DeltaKind.SOURCES_CHANGED)

        self.assertEqual(self.events, [])

    def test_real_coordinator_close_clears_the_bridge(self) -> None:
        from core.catalogue_coordinator import CatalogueCoordinator

        coordinator = CatalogueCoordinator()
        repo = ModelRepository(catalogue=coordinator)
        self.assertIn(repo._on_catalogue_delta, coordinator._delta_subscribers)

        coordinator.close()

        self.assertEqual(coordinator._delta_subscribers, [])

    def test_repository_without_a_coordinator_still_constructs(self) -> None:
        repo = ModelRepository()
        repo.invalidate_model_presentation()

    def test_coordinator_without_subscribe_delta_is_tolerated(self) -> None:
        class _Bare:
            pass

        ModelRepository(catalogue=_Bare())
