"""Public evidence actions use reservations and completion subscriptions."""

from __future__ import annotations

import dataclasses
import unittest
from typing import Any, Callable
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE
from core.catalog_sources import EntryMeta
from core.catalogue_evidence import CatalogueEvidenceService, CatalogueEvidenceSummary
from core.catalogue_stem_cache import StemCacheError, StemCacheHit
from core.catalogue_types import CatalogueEvidenceState


class CatalogueEvidenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.urls = ("https://example.test/a.yaml", "https://example.test/b.yaml")
        self.metadata = {
            label: EntryMeta(
                label=label, display=label, arch=MDX_ARCH_TYPE, files={"model.yaml": url}, stems=[]
            )
            for label, url in (("A", self.urls[0]), ("Alias", self.urls[0]), ("B", self.urls[1]))
        }
        self.flat = dict(self.metadata)
        self.notifications: list[Any] = []
        self.service = CatalogueEvidenceService(
            flat_metadata=lambda: self.flat,
            family_metadata=lambda: {"mdx": self.metadata},
            catalogues=lambda: {"mdx": {name: meta.files for name, meta in self.metadata.items()}},
            notify_metadata=self.notifications.append,
        )
        self.hits: dict[str, StemCacheHit] = {}
        self.active: set[str] = set()
        self.accepted: tuple[str, ...] = self.urls
        self.listener: Callable[[], None] | None = None
        self.worker_summaries: list[CatalogueEvidenceSummary] = []
        self.enqueues: list[Any] = []
        self.order: list[str] = []

        def reserve(urls: tuple[str, ...], *, on_reserved: Callable[..., None], **kwargs: Any):
            self.enqueues.append((urls, kwargs))
            accepted = tuple(url for url in urls if url in self.accepted)
            if accepted:
                self.active.update(accepted)
                self.order.append("reserved")
                on_reserved(accepted)
            return accepted

        def subscribe(callback: Callable[[], None]) -> None:
            self.listener = callback
            self.order.append("subscribed")

        def start() -> None:
            self.order.append("worker")
            self.worker_summaries.append(self.service.catalogue_evidence_summary())

        for name, side_effect in {
            "enqueue_missing": reserve,
            "lookup_stems": self.hits.get,
            "subscribe": subscribe,
            "pending_urls": lambda: set(self.active),
            "ensure_worker_started": start,
        }.items():
            patcher = mock.patch(f"core.catalogue_stem_cache.{name}", side_effect=side_effect)
            patcher.start()
            self.addCleanup(patcher.stop)

    def complete(self, url: str) -> None:
        self.hits[url] = StemCacheHit(
            ("Vocals", "Instrumental"), "Vocals", True, content_sha256="a" * 64
        )
        self.active.remove(url)
        assert self.listener is not None
        self.listener()

    def test_duplicate_entries_reserve_once_and_publish_all_aliases_before_worker(self) -> None:
        result = self.service.queue_catalogue_evidence(
            (("mdx", "A"), ("mdx", "A"), ("mdx", "Alias")), priority=True
        )
        self.assertEqual(result, (self.urls[0],))
        self.assertEqual(self.enqueues, [((self.urls[0],), {"priority": True, "force": False})])
        self.assertEqual(self.worker_summaries[0].pending, 2)
        self.assertEqual(self.order, ["reserved", "subscribed", "worker"])
        self.assertEqual(self.notifications, [{"mdx": ("A", "Alias")}])
        self.complete(self.urls[0])
        self.assertEqual(self.service.catalogue_evidence_summary().pending, 0)
        for name in ("A", "Alias"):
            self.assertEqual(
                self.metadata[name].catalogue_evidence_status, CatalogueEvidenceState.READY
            )
            self.assertIs(self.flat[name], self.metadata[name])
        self.assertEqual(self.notifications[-1], {"mdx": ("A", "Alias")})

    def test_partial_reservation_only_publishes_accepted_url(self) -> None:
        self.accepted = (self.urls[1],)
        self.assertEqual(self.service.queue_catalogue_evidence(), self.accepted)
        self.assertEqual(self.service.catalogue_evidence_summary().pending, 1)
        self.assertEqual(self.notifications, [{"mdx": ("B",)}])
        self.assertEqual(
            self.metadata["A"].catalogue_evidence_status, CatalogueEvidenceState.UNAVAILABLE
        )

    def test_no_reservation_changes_nothing_and_starts_no_worker(self) -> None:
        before = dict(self.metadata)
        self.accepted = ()
        self.assertEqual(self.service.queue_catalogue_evidence(), ())
        self.assertEqual(self.metadata, before)
        self.assertEqual(self.notifications, [])
        self.assertEqual(self.worker_summaries, [])
        self.assertIsNone(self.listener)

    def test_valid_fresh_cache_skips_but_due_failed_and_hashless_follow_existing_eligibility(
        self,
    ) -> None:
        fresh = StemCacheHit(("Vocals",), "Vocals", True, content_sha256="a" * 64)
        cases = (
            (fresh, False),
            (dataclasses.replace(fresh, revalidation_due=True), True),
            (dataclasses.replace(fresh, content_sha256=""), True),
            (
                StemCacheHit((), None, False, last_error=StemCacheError("timeout", "fixture", 1)),
                False,
            ),
            (StemCacheHit((), None, False, revalidation_due=True), True),
        )
        for hit, eligible in cases:
            with self.subTest(hit=hit):
                self.hits[self.urls[0]] = hit
                result = self.service.queue_catalogue_evidence((("mdx", "A"),))
                self.assertEqual(result, (self.urls[0],) if eligible else ())

    def test_force_completes_once_after_both_urls_with_public_final_summary(self) -> None:
        fresh = StemCacheHit(("Vocals",), "Vocals", True, content_sha256="a" * 64)
        self.hits.update(dict.fromkeys(self.urls, fresh))
        completed: list[CatalogueEvidenceSummary] = []
        self.assertEqual(
            self.service.force_revalidate_catalogue_evidence(completed.append), self.urls
        )
        self.assertEqual(self.enqueues[0][1], {"priority": False, "force": True})
        self.complete(self.urls[0])
        self.assertEqual(completed, [])
        self.complete(self.urls[1])
        self.assertEqual(completed, [self.service.catalogue_evidence_summary()])
        self.assertEqual(completed[0].pending, 0)
        assert self.listener is not None
        self.listener()
        self.assertEqual(len(completed), 1)
