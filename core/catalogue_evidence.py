"""Exact catalogue evidence reconciliation and scheduling.

The service owns pending batches and its cache subscription. Metadata accessors
refer to the manager's current compatibility projections, so replacing a source
snapshot never leaves this service editing stale dictionaries.
"""

from __future__ import annotations

import dataclasses
import threading
import typing
from typing import Any, Callable, Dict, Mapping

from .debug_log import log_event
from .model_identity import FAMILY_BY_ARCH


@dataclasses.dataclass(frozen=True)
class CatalogueEvidenceSummary:
    """Aggregate semantic-review and exact-evidence availability counts."""

    reviewed: int = 0
    raw: int = 0
    waived: int = 0
    pending: int = 0
    unavailable: int = 0
    stale: int = 0


class CatalogueEvidenceService:
    def __init__(
        self,
        *,
        flat_metadata: Callable[[], Dict[str, Any]],
        family_metadata: Callable[[], Mapping[str, Dict[str, Any]]],
        catalogues: Callable[[], Mapping[str, Mapping[str, Any]]],
        notify_metadata: Callable[[Mapping[str, tuple[str, ...]]], None],
    ) -> None:
        self._flat_metadata = flat_metadata
        self._family_metadata = family_metadata
        self._catalogues = catalogues
        self._notify_metadata = notify_metadata
        self._lock = threading.Lock()
        self.pending: set[str] = set()
        self.force_pending: set[str] = set()
        self.callbacks: list[Callable[[CatalogueEvidenceSummary], None]] = []
        self.url_entries: Dict[str, list[tuple[str, str]]] = {}
        self._subscribed = False

    def apply_catalogue_stem_cache(
        self,
        urls: typing.Iterable[str] | None = None,
    ) -> set[str]:
        """Patch family-scoped metadata from completed exact config evidence."""
        from .catalog_sources import (
            _needs_catalogue_config_evidence,
            _yaml_config_url,
            reconcile_catalogue_evidence,
        )
        from .catalogue_stem_cache import lookup_stems

        allowed_urls = set(urls or ())
        scoped = self._family_catalogue_meta()
        targets = [
            (family, label, meta)
            for family, metadata in scoped.items()
            for label, meta in list(metadata.items())
        ]
        if not targets:
            targets = [
                (FAMILY_BY_ARCH.get(meta.arch, ""), label, meta)
                for label, meta in list(self._flat_metadata().items())
            ]
        updated: set[str] = set()
        updated_by_family: Dict[str, list[str]] = {}
        for family, label, meta in targets:
            url = _yaml_config_url(meta.files)
            if not url:
                continue
            if url not in allowed_urls and not _needs_catalogue_config_evidence(meta):
                continue
            hit = lookup_stems(url)
            if hit is None:
                continue
            # Legacy successes without a digest are not exact byte evidence.
            if hit.usable and not hit.content_sha256:
                continue
            reconciled = reconcile_catalogue_evidence(
                meta,
                live_stems=list(hit.stems),
                live_target_instrument=hit.target_instrument,
                live_config_sha256=hit.content_sha256,
                live_usable=hit.usable,
                live_stale=hit.stale,
                live_failed=hit.last_error is not None and not hit.usable,
                live_warning=hit.warning,
            )
            if reconciled != meta:
                flat = self._flat_metadata()
                if flat.get(label) is meta or label not in flat:
                    flat[label] = reconciled
                family_meta = scoped.get(family)
                if family_meta is not None and label in family_meta:
                    family_meta[label] = reconciled
                updated.add(label)
                updated_by_family.setdefault(family, []).append(label)
        if updated:
            self._notify_metadata(
                {family: tuple(sorted(labels)) for family, labels in updated_by_family.items()}
            )
        return updated

    def _ensure_catalogue_evidence_listener(self) -> None:
        """Subscribe once to incremental config-validation cache changes."""
        if self._subscribed:
            return
        from .catalogue_stem_cache import subscribe

        subscribe(self._on_catalogue_evidence_cache_update)
        self._subscribed = True

    def _on_catalogue_evidence_cache_update(self) -> None:
        """Apply completed config evidence while leaving queued work pending."""
        from .catalogue_stem_cache import pending_urls

        lock = self._lock
        with lock:
            tracked = set(self.pending)
        self.apply_catalogue_stem_cache(tracked)
        active = pending_urls()
        callbacks: list[Callable[[CatalogueEvidenceSummary], None]] = []
        completed_force: set[str] = set()
        with lock:
            self.pending.intersection_update(active)
            before_force = set(self.force_pending)
            self.force_pending.intersection_update(active)
            if before_force and not self.force_pending:
                completed_force = before_force
                callbacks = list(self.callbacks)
                self.callbacks.clear()
        if not completed_force:
            return
        summary = self.catalogue_evidence_summary()
        self._log_catalogue_evidence_failures(completed_force)
        log_event(
            "download",
            "catalogue_evidence_batch_completed",
            level="debug",
            **dataclasses.asdict(summary),
        )
        for callback in callbacks:
            try:
                callback(summary)
            except Exception as exc:
                log_event(
                    "download",
                    "catalogue_evidence_subscriber_failed",
                    level="warning",
                    subscriber_type=type(callback).__name__,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )

    def _family_catalogue_meta(self) -> Dict[str, Dict[str, Any]]:
        """Return the authoritative family-scoped catalogue metadata."""
        scoped = self._family_metadata()
        return scoped if isinstance(scoped, dict) else {}

    def _public_family_catalogue_meta(self) -> Dict[str, Dict[str, Any]]:
        """Resolve post-deduplication public rows through exact family metadata."""
        scoped = self._family_catalogue_meta()
        catalogues = {
            "vr": self._catalogues().get("vr", {}),
            "mdx": self._catalogues().get("mdx", {}),
            "demucs": self._catalogues().get("demucs", {}),
            "apollo": self._catalogues().get("apollo", {}),
        }
        return {
            family: {
                str(label): metadata[str(label)] for label in catalogue if str(label) in metadata
            }
            for family, catalogue in catalogues.items()
            if isinstance(catalogue, dict)
            for metadata in (scoped.get(family, {}),)
        }

    def catalogue_evidence_summary(self) -> CatalogueEvidenceSummary:
        """Count semantic review and evidence availability without flattening IDs."""
        semantic = {"reviewed": 0, "raw": 0, "waived": 0}
        evidence = {"pending": 0, "unavailable": 0, "stale": 0}
        for metadata in self._public_family_catalogue_meta().values():
            for meta in metadata.values():
                projection = getattr(meta, "stem_semantics", None)
                review = str(getattr(projection, "status", "raw") or "raw")
                if review in semantic:
                    semantic[review] += 1
                state = getattr(meta, "catalogue_evidence_status", "unavailable")
                state_value = str(getattr(state, "value", state) or "")
                if state_value in evidence:
                    evidence[state_value] += 1
        return CatalogueEvidenceSummary(**semantic, **evidence)

    def _log_catalogue_evidence_failures(self, urls: typing.Iterable[str]) -> None:
        """Log batch failures with exact identities and bounded cache diagnostics."""
        from .catalogue_identity import catalogue_model_id
        from .catalogue_stem_cache import lookup_stems

        scoped = self._family_catalogue_meta()
        url_entries = self.url_entries
        for url in urls:
            hit = lookup_stems(url)
            error = getattr(hit, "last_error", None) if hit is not None else None
            if error is None:
                continue
            for family, label in url_entries.get(url, ()):
                meta = scoped.get(family, {}).get(label)
                catalogue = self._catalogues().get(family, {})
                raw = catalogue.get(label) if isinstance(catalogue, dict) else None
                model_id = catalogue_model_id(family, label, raw, meta) or f"{family}:{label}"
                log_event(
                    "download",
                    "catalogue_evidence_validation_failed",
                    level="warning",
                    model_id=model_id,
                    url=url,
                    error_type=getattr(error, "kind", type(error).__name__),
                    message=getattr(error, "message", str(error)),
                )

    def queue_catalogue_evidence(
        self,
        entries: typing.Iterable[tuple[str, str]] | None = None,
        *,
        priority: bool = False,
        force: bool = False,
        on_complete: Callable[[CatalogueEvidenceSummary], None] | None = None,
    ) -> tuple[str, ...]:
        """Queue exact config evidence and expose pending state immediately.

        ``entries`` contains canonical ``(family, catalogue selection)`` pairs.
        Omitting it selects every current family-scoped entry. Force bypasses
        both success and failure TTLs without deleting last-known-good cache
        evidence.
        """
        from .catalog_sources import _needs_catalogue_config_evidence, _yaml_config_url
        from .catalogue_stem_cache import (
            enqueue_missing,
            ensure_worker_started,
            lookup_stems,
        )
        from .catalogue_types import CatalogueEvidenceState

        scoped = self._family_catalogue_meta()
        public_scoped = self._public_family_catalogue_meta()
        requested = (
            tuple(entries)
            if entries is not None
            else tuple(
                (family, label) for family, metadata in public_scoped.items() for label in metadata
            )
        )
        selected: list[tuple[str, str, Any, str]] = []
        seen_entries: set[tuple[str, str, str]] = set()
        for family, label in requested:
            metadata = scoped.get(str(family), {})
            meta = metadata.get(str(label))
            if meta is None or str(family) != "mdx":
                continue
            url = _yaml_config_url(meta.files)
            if not url:
                continue
            entry_key = (str(family), str(label), url)
            if entry_key in seen_entries:
                continue
            if not force:
                hit = lookup_stems(url)
                if hit is not None:
                    if not (hit.ok and not hit.content_sha256) and not hit.revalidation_due:
                        continue
                elif not _needs_catalogue_config_evidence(meta) and not meta.config_sha256:
                    continue
            seen_entries.add(entry_key)
            selected.append((str(family), str(label), meta, url))

        urls = tuple(sorted({item[3] for item in selected}))
        if not urls:
            return ()
        published_urls: tuple[str, ...] = ()

        def publish_reserved(accepted: tuple[str, ...]) -> None:
            nonlocal published_urls
            accepted_set = set(accepted)
            published_urls = tuple(url for url in urls if url in accepted_set)
            accepted_entries = [item for item in selected if item[3] in accepted_set]
            changed: Dict[str, list[str]] = {}
            for family, label, meta, _url in accepted_entries:
                status = getattr(meta, "catalogue_evidence_status", None)
                if status is not CatalogueEvidenceState.UNAVAILABLE:
                    continue
                pending_meta = dataclasses.replace(
                    meta,
                    catalogue_evidence_status=CatalogueEvidenceState.PENDING,
                    catalogue_evidence_warning="",
                )
                scoped[family][label] = pending_meta
                flat = self._flat_metadata()
                if flat.get(label) is meta:
                    flat[label] = pending_meta
                changed.setdefault(family, []).append(label)

            lock = self._lock
            with lock:
                self.pending.update(published_urls)
                if force:
                    self.force_pending.update(published_urls)
                    if on_complete is not None:
                        self.callbacks.append(on_complete)
                for family, label, _meta, url in accepted_entries:
                    associations = self.url_entries.setdefault(url, [])
                    association = (family, label)
                    if association not in associations:
                        associations.append(association)
            if force:
                summary = self.catalogue_evidence_summary()
                log_event(
                    "download",
                    "catalogue_evidence_batch_started",
                    urls=len(published_urls),
                    force=True,
                    **dataclasses.asdict(summary),
                )
            if changed:
                self._notify_metadata({family: tuple(labels) for family, labels in changed.items()})
            self._ensure_catalogue_evidence_listener()

        accepted = enqueue_missing(
            urls,
            priority=priority,
            force=force,
            on_reserved=publish_reserved,
        )
        if not accepted:
            return ()
        ensure_worker_started()
        return published_urls

    def force_revalidate_catalogue_evidence(
        self,
        on_complete: Callable[[CatalogueEvidenceSummary], None] | None = None,
    ) -> tuple[str, ...]:
        """Conditionally revalidate every current config without clearing LKG."""
        return self.queue_catalogue_evidence(force=True, on_complete=on_complete)
