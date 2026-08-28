"""DownloadManager stem-cache patch and Download Center debounced subtitle flush."""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import threading
import time
import typing
import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

from bundled.constants import APOLLO_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.access_policy import access_policy
from core.catalog_sources import EntryMeta
from core.catalogue_stem_cache import StemCacheError, StemCacheHit
from core.catalogue_types import CatalogueEvidenceState, StemSemanticProjection
from core.downloads import DownloadManager
from core.model_stem_manifest import resolve_model_stem_semantics
from core.model_stem_semantics import stem_semantics_projection
from tests.private_gtk import require_private_gtk

_YAML_URL = "https://example.test/model.yaml"


def _accept_reserved_urls(
    urls: typing.Iterable[str],
    *,
    priority: bool = False,
    force: bool = False,
    on_reserved: typing.Callable[[tuple[str, ...]], None] | None = None,
) -> tuple[str, ...]:
    del priority, force
    accepted = tuple(urls)
    if on_reserved is not None:
        on_reserved(accepted)
    return accepted


def _write_legacy_success_cache(path: str, url: str) -> None:
    """Write the pre-digest cache shape shipped by older UVR builds."""
    fetched_at = time.time()
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "fetched_at": fetched_at,
                "entries": {
                    url: {
                        "stems": ["Vocals", "other"],
                        "target_instrument": "Vocals",
                        "fetched_at": fetched_at,
                        "ok": True,
                    }
                },
            },
            handle,
        )


def setUpModule() -> None:
    require_private_gtk()


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
        self.manager.catalogue_meta_by_family = {"mdx": {"M": meta}}
        hit = StemCacheHit(
            stems=("Vocals", "other"),
            target_instrument="Vocals",
            ok=True,
            content_sha256="a" * 64,
        )
        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            updated = self.manager.apply_catalogue_stem_cache()

        self.assertEqual(updated, {"M"})
        patched = self.manager.catalogue_meta["M"]
        self.assertEqual(patched.stems, ["Vocals", "other"])
        self.assertEqual(patched.target_instrument, "Vocals")
        self.assertEqual(patched.config_sha256, "a" * 64)
        self.assertEqual(patched.catalogue_evidence_status, CatalogueEvidenceState.READY)
        self.assertIs(self.manager.catalogue_meta_by_family["mdx"]["M"], patched)

    def test_patches_exact_config_evidence_through_shared_reconciliation(self) -> None:
        meta = EntryMeta(
            label="Reviewed",
            display="Reviewed",
            arch=MDX_ARCH_TYPE,
            files={
                "melband_roformer_inst_v1.ckpt": "https://example.test/model.ckpt",
                "config_melbandroformer_inst.yaml": _YAML_URL,
            },
            checkpoint="melband_roformer_inst_v1.ckpt",
            stems=[],
        )
        self.manager.catalogue_meta = {"Reviewed": meta}
        hit = StemCacheHit(
            stems=("Instrumental", "Vocals"),
            target_instrument="Instrumental",
            ok=True,
            content_sha256=("723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d"),
        )

        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            updated = self.manager.apply_catalogue_stem_cache()

        self.assertEqual(updated, {"Reviewed"})
        patched = self.manager.catalogue_meta["Reviewed"]
        self.assertEqual(patched.stem_semantics.status, "reviewed")
        self.assertEqual(patched.config_sha256, hit.content_sha256)

    def test_patches_raw_exact_config_evidence_when_stems_already_set(self) -> None:
        meta = EntryMeta(
            label="Reviewed after cache",
            display="Reviewed after cache",
            arch=MDX_ARCH_TYPE,
            files={
                "melband_roformer_inst_v1.ckpt": "https://example.test/model.ckpt",
                "config_melbandroformer_inst.yaml": _YAML_URL,
            },
            checkpoint="melband_roformer_inst_v1.ckpt",
            stems=["Instrumental", "Vocals"],
            target_instrument="Instrumental",
        )
        self.manager.catalogue_meta = {meta.label: meta}
        hit = StemCacheHit(
            stems=("Instrumental", "Vocals"),
            target_instrument="Instrumental",
            ok=True,
            content_sha256="723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
        )
        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            updated = self.manager.apply_catalogue_stem_cache()

        self.assertEqual(updated, {meta.label})
        patched = self.manager.catalogue_meta[meta.label]
        self.assertEqual(patched.stem_semantics.status, "reviewed")
        self.assertEqual(patched.config_sha256, hit.content_sha256)

    def test_legacy_success_without_digest_is_not_applied_as_exact_evidence(self) -> None:
        import core.catalogue_stem_cache as csc

        meta = EntryMeta(
            label="Legacy",
            display="Legacy",
            arch=MDX_ARCH_TYPE,
            files={"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL},
            stems=[],
        )
        self.manager.catalogue_meta = {meta.label: meta}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "catalogue_stem_cache.json")
            with (
                mock.patch.object(csc, "_cache_path", return_value=cache_path),
                mock.patch("core.model_display.clear_display_cache"),
            ):
                csc.clear_catalogue_stem_cache()
                try:
                    _write_legacy_success_cache(cache_path, _YAML_URL)
                    hit = csc.lookup_stems(_YAML_URL)
                    self.assertIsNotNone(hit)
                    assert hit is not None
                    self.assertTrue(hit.ok)
                    self.assertEqual(hit.content_sha256, "")
                    updated = self.manager.apply_catalogue_stem_cache()
                finally:
                    csc.clear_catalogue_stem_cache()

        self.assertEqual(updated, set())
        self.assertIs(self.manager.catalogue_meta[meta.label], meta)

    def test_skips_entry_with_already_reviewed_semantics(self) -> None:
        semantics = resolve_model_stem_semantics(
            "mdx:UVR_MDXNET_KARA_2",
            native_stems=("Instrumental", "Vocals"),
            backend_primary="Instrumental",
        )
        meta = EntryMeta(
            label="Reviewed",
            display="Reviewed",
            arch=MDX_ARCH_TYPE,
            files={"m.yaml": _YAML_URL},
            stems=["Instrumental", "Vocals"],
            stem_semantics=stem_semantics_projection(semantics),
            catalogue_evidence_status=CatalogueEvidenceState.READY,
        )
        self.manager.catalogue_meta = {meta.label: meta}
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

    def test_live_exact_target_overrides_existing_lower_authority_target(self) -> None:
        meta = EntryMeta(
            label="M",
            display="M",
            arch=MDX_ARCH_TYPE,
            files={"m.yaml": _YAML_URL},
            stems=[],
            target_instrument="Bass",
        )
        self.manager.catalogue_meta = {"M": meta}
        hit = StemCacheHit(
            stems=("Vocals", "other"),
            target_instrument="Vocals",
            ok=True,
            content_sha256="b" * 64,
        )
        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            updated = self.manager.apply_catalogue_stem_cache()
        self.assertEqual(updated, {"M"})
        self.assertEqual(self.manager.catalogue_meta["M"].target_instrument, "Vocals")

    def test_failed_online_evidence_updates_availability_without_semantic_mismatch(self) -> None:
        meta = EntryMeta(
            label="M",
            display="M",
            arch=MDX_ARCH_TYPE,
            files={"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL},
            stems=["summary", "only"],
        )
        self.manager.catalogue_meta = {"M": meta}
        hit = StemCacheHit(
            stems=(),
            target_instrument=None,
            ok=False,
            last_error=StemCacheError("network", "request failed", 1.0),
            warning="request failed",
        )
        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            updated = self.manager.apply_catalogue_stem_cache()

        self.assertEqual(updated, {"M"})
        patched = self.manager.catalogue_meta["M"]
        self.assertEqual(patched.catalogue_evidence_status, CatalogueEvidenceState.UNAVAILABLE)
        self.assertEqual(patched.catalogue_evidence_warning, "request failed")
        self.assertNotIn("mismatch", patched.stem_semantics.warning)

    def test_strict_runtime_contract_digest_mismatch_remains_raw(self) -> None:
        meta = EntryMeta(
            label="Reviewed",
            display="Reviewed",
            arch=MDX_ARCH_TYPE,
            files={
                "melband_roformer_inst_v1.ckpt": "https://example.test/model.ckpt",
                "config_melbandroformer_inst.yaml": _YAML_URL,
            },
            checkpoint="melband_roformer_inst_v1.ckpt",
        )
        self.manager.catalogue_meta = {meta.label: meta}
        hit = StemCacheHit(
            stems=("Instrumental", "Vocals"),
            target_instrument="Instrumental",
            ok=True,
            content_sha256="f" * 64,
        )
        with mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=hit):
            updated = self.manager.apply_catalogue_stem_cache()

        self.assertEqual(updated, {meta.label})
        patched = self.manager.catalogue_meta[meta.label]
        self.assertEqual(patched.catalogue_evidence_status, CatalogueEvidenceState.READY)
        self.assertEqual(patched.stem_semantics.status, "raw")
        self.assertIn("runtime-contract-mismatch", patched.catalogue_evidence_warning)


class CatalogueEvidenceSchedulingTests(unittest.TestCase):
    def setUp(self) -> None:
        import core.catalogue_stem_cache as csc

        csc._reset_worker_state_for_tests()
        self.addCleanup(csc._reset_worker_state_for_tests)

    @staticmethod
    def _meta(label: str, arch: str, url: str) -> EntryMeta:
        return EntryMeta(
            label=label,
            display=label,
            arch=arch,
            files={"m.ckpt": f"https://example.test/{label}.ckpt", "m.yaml": url},
            catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
        )

    def test_visible_priority_uses_family_scoped_entry_and_exact_url(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        shared = "Shared label"
        mdx = self._meta(shared, MDX_ARCH_TYPE, "https://mdx.example.test/exact.yaml?raw=1")
        vr = self._meta(shared, VR_ARCH_TYPE, "https://vr.example.test/wrong.yaml")
        manager.catalogue_meta = {shared: vr}
        manager.catalogue_meta_by_family = {"mdx": {shared: mdx}, "vr": {shared: vr}}

        with (
            mock.patch.object(
                csc,
                "enqueue_missing",
                side_effect=_accept_reserved_urls,
            ) as enqueue,
            mock.patch.object(csc, "ensure_worker_started") as ensure,
            access_policy(
                allow_network=True,
                allow_metadata_writes=False,
                allow_cache_writes=False,
            ),
        ):
            queued = manager.queue_catalogue_evidence(
                (("mdx", shared),),
                priority=True,
            )

        self.assertEqual(queued, ("https://mdx.example.test/exact.yaml",))
        enqueue.assert_called_once_with(
            ("https://mdx.example.test/exact.yaml",),
            priority=True,
            force=False,
            on_reserved=mock.ANY,
        )
        ensure.assert_called_once_with()
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][shared].catalogue_evidence_status,
            CatalogueEvidenceState.PENDING,
        )
        self.assertEqual(
            manager.catalogue_meta_by_family["vr"][shared].catalogue_evidence_status,
            CatalogueEvidenceState.UNAVAILABLE,
        )

    def test_queued_state_is_observable_before_worker_response(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        queued_url = "https://example.test/queued-observable.yaml"
        meta = self._meta("Queued", MDX_ARCH_TYPE, queued_url)
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        fetch_started = threading.Event()
        release_fetch = threading.Event()

        def blocked_fetch(
            url: str,
            *,
            force: bool,
            policy: object,
        ) -> bool:
            del force, policy
            fetch_started.set()
            self.assertTrue(release_fetch.wait(timeout=1.0), "test did not release fetch")
            csc.remember_stems(url, [], None, ok=False)
            return False

        with (
            mock.patch.object(csc, "_fetch_and_remember", side_effect=blocked_fetch),
            access_policy(
                allow_network=True,
                allow_metadata_writes=False,
                allow_cache_writes=False,
            ),
        ):
            manager.queue_catalogue_evidence((("mdx", meta.label),))
            self.assertTrue(fetch_started.wait(timeout=1.0), "worker did not start fetch")
            self.assertTrue(csc.is_pending(queued_url))
            self.assertEqual(
                manager.catalogue_meta_by_family["mdx"][meta.label].catalogue_evidence_status,
                CatalogueEvidenceState.PENDING,
            )
            release_fetch.set()
            self.assertTrue(csc._worker_idle.wait(timeout=1.0), "worker did not drain")

    def test_shared_config_url_marks_every_family_scoped_row_pending(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        shared_url = "https://example.test/shared-config.yaml"
        first = self._meta("First", MDX_ARCH_TYPE, shared_url)
        second = self._meta("Second", MDX_ARCH_TYPE, shared_url)
        manager.catalogue_meta = {first.label: first, second.label: second}
        manager.catalogue_meta_by_family = {"mdx": {first.label: first, second.label: second}}

        with (
            mock.patch.object(csc, "enqueue_missing", side_effect=_accept_reserved_urls) as enqueue,
            mock.patch.object(csc, "ensure_worker_started"),
            access_policy(
                allow_network=True,
                allow_metadata_writes=False,
                allow_cache_writes=False,
            ),
        ):
            queued = manager.queue_catalogue_evidence((("mdx", first.label), ("mdx", second.label)))

        self.assertEqual(queued, (shared_url,))
        enqueue.assert_called_once_with(
            (shared_url,),
            priority=False,
            force=False,
            on_reserved=mock.ANY,
        )
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][first.label].catalogue_evidence_status,
            CatalogueEvidenceState.PENDING,
        )
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][second.label].catalogue_evidence_status,
            CatalogueEvidenceState.PENDING,
        )

    def test_ordinary_scheduling_queues_due_lkg_once_but_not_before_retry_ttl(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        shared_url = "https://example.test/due-shared.yaml"
        first = dataclasses.replace(
            self._meta("First due", MDX_ARCH_TYPE, shared_url),
            catalogue_evidence_status=CatalogueEvidenceState.READY,
        )
        second = dataclasses.replace(
            self._meta("Second due", MDX_ARCH_TYPE, shared_url),
            catalogue_evidence_status=CatalogueEvidenceState.READY,
        )
        manager.catalogue_meta_by_family = {"mdx": {first.label: first, second.label: second}}
        manager.mdx_download_list = {first.label: {}, second.label: {}}
        fresh_retry = StemCacheHit(
            stems=("Vocals", "Instrumental"),
            target_instrument="Vocals",
            ok=True,
            content_sha256="a" * 64,
            last_error=StemCacheError("network", "down", 1.0),
            stale=True,
            revalidation_due=False,
        )
        due_retry = dataclasses.replace(fresh_retry, revalidation_due=True)

        with (
            mock.patch.object(csc, "lookup_stems", return_value=fresh_retry),
            mock.patch.object(csc, "enqueue_missing") as enqueue,
        ):
            self.assertEqual(manager.queue_catalogue_evidence(), ())
            enqueue.assert_not_called()

        with (
            mock.patch.object(csc, "lookup_stems", return_value=due_retry),
            mock.patch.object(
                csc,
                "enqueue_missing",
                side_effect=_accept_reserved_urls,
            ) as enqueue,
            mock.patch.object(csc, "ensure_worker_started"),
        ):
            self.assertEqual(manager.queue_catalogue_evidence(), (shared_url,))

        enqueue.assert_called_once_with(
            (shared_url,),
            priority=False,
            force=False,
            on_reserved=mock.ANY,
        )

    def test_default_summary_and_queue_exclude_hidden_alias_metadata(self) -> None:
        import core.catalogue_stem_cache as csc
        from core.model_manifest import load_model_manifest

        manager = DownloadManager()
        manifest = load_model_manifest()
        public: dict[str, dict[str, object]] = {
            "vr": {},
            "mdx": {},
            "demucs": {},
            "apollo": {},
        }
        scoped: dict[str, dict[str, EntryMeta]] = {
            "vr": {},
            "mdx": {},
            "demucs": {},
            "apollo": {},
        }
        arch_by_family = {
            "vr": VR_ARCH_TYPE,
            "mdx": MDX_ARCH_TYPE,
            "demucs": "Demucs",
            "apollo": "Apollo",
        }

        def projection(status: str) -> StemSemanticProjection:
            return StemSemanticProjection(
                backend_primary_stem=None,
                backend_target_stem=None,
                logical_primary_role=None,
                logical_secondary_role=None,
                status=status,
                context="full_mix",
                routes=(),
            )

        for model_id, record in manifest.models.items():
            if record.lifecycle != "current":
                continue
            family, _separator, basename = model_id.partition(":")
            label = model_id
            status = "reviewed" if model_id in manifest.stems.models else "waived"
            files = {record.catalogue_evidence.primary_artifact: ""}
            if record.catalogue_evidence.config_yaml:
                files[record.catalogue_evidence.config_yaml] = (
                    f"https://example.test/{basename}.yaml"
                )
            public[family][label] = files
            scoped[family][label] = EntryMeta(
                label=label,
                display=label,
                arch=arch_by_family[family],
                files=files,
                stem_semantics=projection(status),
                catalogue_evidence_status=CatalogueEvidenceState.READY,
            )

        hidden_label = "Hidden pre-dedupe alias"
        hidden_url = "https://example.test/hidden-alias.yaml"
        scoped["mdx"][hidden_label] = EntryMeta(
            label=hidden_label,
            display=hidden_label,
            arch=MDX_ARCH_TYPE,
            files={"hidden.ckpt": "", "hidden.yaml": hidden_url},
            stem_semantics=projection("raw"),
            catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
        )
        manager.vr_download_list = public["vr"]
        manager.mdx_download_list = public["mdx"]
        manager.demucs_download_list = public["demucs"]
        manager.apollo_download_list = public["apollo"]
        manager.catalogue_meta_by_family = scoped

        self.assertEqual(
            dataclasses.asdict(manager.catalogue_evidence_summary()),
            {
                "reviewed": 483,
                "raw": 0,
                "waived": 2,
                "pending": 0,
                "unavailable": 0,
                "stale": 0,
            },
        )
        self.assertEqual(sum(len(entries) for entries in public.values()), 485)

        public_due_label = next(
            label
            for label, meta in scoped["mdx"].items()
            if label != hidden_label
            and any(name.casefold().endswith((".yaml", ".yml")) for name in meta.files)
        )
        scoped["mdx"][public_due_label] = dataclasses.replace(
            scoped["mdx"][public_due_label],
            catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
        )

        with (
            mock.patch.object(csc, "lookup_stems", return_value=None),
            mock.patch.object(
                csc,
                "enqueue_missing",
                side_effect=_accept_reserved_urls,
            ) as enqueue,
            mock.patch.object(csc, "ensure_worker_started"),
        ):
            queued = manager.queue_catalogue_evidence()

        self.assertTrue(queued)
        self.assertNotIn(hidden_url, queued)
        self.assertNotIn(hidden_url, enqueue.call_args.args[0])

        with (
            mock.patch.object(csc, "lookup_stems", return_value=None),
            mock.patch.object(
                csc,
                "enqueue_missing",
                side_effect=_accept_reserved_urls,
            ),
            mock.patch.object(csc, "ensure_worker_started"),
        ):
            self.assertEqual(
                manager.queue_catalogue_evidence((("mdx", hidden_label),)),
                (hidden_url,),
            )

    def test_pending_metadata_is_published_before_network_work_starts(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        meta = self._meta("Queued", MDX_ARCH_TYPE, _YAML_URL)
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        manager._coordinator = mock.MagicMock()
        order: list[str] = []
        manager._coordinator.notify_metadata.side_effect = lambda _labels: order.append("pending")

        def accept(
            urls: typing.Iterable[str],
            *,
            on_reserved: typing.Callable[[tuple[str, ...]], None],
            **_kwargs: object,
        ) -> tuple[str, ...]:
            order.append("enqueue")
            accepted = tuple(urls)
            on_reserved(accepted)
            return accepted

        with (
            mock.patch.object(csc, "enqueue_missing", side_effect=accept),
            mock.patch.object(
                csc, "ensure_worker_started", side_effect=lambda: order.append("worker")
            ),
            access_policy(
                allow_network=True,
                allow_metadata_writes=False,
                allow_cache_writes=False,
            ),
        ):
            manager.queue_catalogue_evidence((("mdx", meta.label),))

        self.assertEqual(order, ["enqueue", "pending", "worker"])

    def test_force_revalidation_retries_failures_without_clearing_lkg(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        ready = self._meta("Ready", MDX_ARCH_TYPE, "https://example.test/ready.yaml")
        ready = dataclasses.replace(
            ready,
            stems=["Vocals", "Instrumental"],
            catalogue_evidence_status=CatalogueEvidenceState.READY,
        )
        failed = self._meta("Failed", MDX_ARCH_TYPE, "https://example.test/failed.yaml")
        manager.catalogue_meta = {ready.label: ready, failed.label: failed}
        manager.catalogue_meta_by_family = {"mdx": {ready.label: ready, failed.label: failed}}
        manager.mdx_download_list = {ready.label: ready.files, failed.label: failed.files}
        expected = (
            "https://example.test/failed.yaml",
            "https://example.test/ready.yaml",
        )

        with (
            mock.patch.object(csc, "enqueue_missing", side_effect=_accept_reserved_urls) as enqueue,
            mock.patch.object(csc, "ensure_worker_started"),
            mock.patch.object(csc, "clear_catalogue_stem_cache") as clear,
            access_policy(
                allow_network=True,
                allow_metadata_writes=False,
                allow_cache_writes=False,
            ),
        ):
            queued = manager.force_revalidate_catalogue_evidence()

        self.assertEqual(
            queued,
            expected,
        )
        enqueue.assert_called_once_with(
            queued,
            priority=False,
            force=True,
            on_reserved=mock.ANY,
        )
        clear.assert_not_called()
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][ready.label].catalogue_evidence_status,
            CatalogueEvidenceState.READY,
        )
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][failed.label].catalogue_evidence_status,
            CatalogueEvidenceState.PENDING,
        )

    def test_force_revalidation_disabled_does_not_publish_pending_or_keep_callback(self) -> None:
        manager = DownloadManager()
        meta = self._meta("Disabled", MDX_ARCH_TYPE, _YAML_URL)
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        completions: list[object] = []

        with mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}):
            queued = manager.force_revalidate_catalogue_evidence(completions.append)

        self.assertEqual(queued, ())
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][meta.label].catalogue_evidence_status,
            CatalogueEvidenceState.UNAVAILABLE,
        )
        self.assertEqual(manager._catalogue_evidence_pending, set())
        self.assertEqual(manager._catalogue_evidence_force_pending, set())
        self.assertEqual(manager._catalogue_evidence_callbacks, [])
        self.assertEqual(completions, [])

    def test_force_revalidation_without_network_does_not_publish_pending_or_keep_callback(
        self,
    ) -> None:
        manager = DownloadManager()
        meta = self._meta("Offline", MDX_ARCH_TYPE, _YAML_URL)
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        completions: list[object] = []

        with access_policy(
            allow_network=False,
            allow_metadata_writes=False,
            allow_cache_writes=False,
        ):
            queued = manager.force_revalidate_catalogue_evidence(completions.append)

        self.assertEqual(queued, ())
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][meta.label].catalogue_evidence_status,
            CatalogueEvidenceState.UNAVAILABLE,
        )
        self.assertEqual(manager._catalogue_evidence_pending, set())
        self.assertEqual(manager._catalogue_evidence_force_pending, set())
        self.assertEqual(manager._catalogue_evidence_callbacks, [])
        self.assertEqual(completions, [])

    def test_force_revalidation_after_shutdown_does_not_publish_pending(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        meta = self._meta("Shutdown", MDX_ARCH_TYPE, _YAML_URL)
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        csc.request_shutdown()
        try:
            queued = manager.force_revalidate_catalogue_evidence()
        finally:
            csc._shutdown.clear()

        self.assertEqual(queued, ())
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][meta.label].catalogue_evidence_status,
            CatalogueEvidenceState.UNAVAILABLE,
        )
        self.assertEqual(manager._catalogue_evidence_pending, set())
        self.assertEqual(manager._catalogue_evidence_force_pending, set())

    def test_prestarted_worker_cannot_finish_before_force_state_is_published(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        meta = self._meta("Immediate", MDX_ARCH_TYPE, _YAML_URL)
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        manager.mdx_download_list = {meta.label: meta.files}
        manager._coordinator = mock.MagicMock()
        cache_notified = threading.Event()
        completion = threading.Event()
        completion_during_publish: list[bool] = []

        def fetch_immediately(
            url: str,
            *,
            force: bool,
            policy: object,
        ) -> bool:
            del force, policy
            csc.remember_stems(
                url,
                ["Vocals", "Instrumental"],
                "Vocals",
                content_sha256="a" * 64,
                ok=True,
            )
            return True

        def publish_pending(_labels: object) -> None:
            completion_during_publish.append(cache_notified.wait(timeout=0.2))

        manager._coordinator.notify_metadata.side_effect = publish_pending
        csc.subscribe(cache_notified.set)
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "catalogue_stem_cache.json")
            with (
                mock.patch.object(csc, "_cache_path", return_value=cache_path),
                mock.patch.object(csc, "_fetch_and_remember", side_effect=fetch_immediately),
                access_policy(
                    allow_network=True,
                    allow_metadata_writes=False,
                    allow_cache_writes=False,
                ),
            ):
                csc.clear_catalogue_stem_cache()
                csc.ensure_worker_started()
                queued = manager.force_revalidate_catalogue_evidence(
                    lambda _summary: completion.set()
                )
                self.assertTrue(completion.wait(timeout=1.0), "force callback stayed pending")

        self.assertEqual(queued, (_YAML_URL,))
        self.assertEqual(completion_during_publish, [False, True])
        self.assertEqual(
            manager.catalogue_meta_by_family["mdx"][meta.label].catalogue_evidence_status,
            CatalogueEvidenceState.READY,
        )
        self.assertEqual(
            manager.catalogue_meta[meta.label].catalogue_evidence_status,
            CatalogueEvidenceState.READY,
        )
        self.assertEqual(manager._catalogue_evidence_pending, set())
        self.assertEqual(manager._catalogue_evidence_force_pending, set())
        self.assertEqual(manager._catalogue_evidence_callbacks, [])
        self.assertFalse(csc.is_pending(_YAML_URL))

    def test_cache_subscriber_exception_is_logged(self) -> None:
        import core.catalogue_stem_cache as csc

        def broken() -> None:
            raise RuntimeError("subscriber failed")

        csc.subscribe(broken)
        with mock.patch.object(csc, "log_event") as event:
            csc._notify_subscribers()

        event.assert_called_once_with(
            "cache",
            "catalogue_stem_subscriber_failed",
            level="warning",
            subscriber_type="function",
            error_type="RuntimeError",
            message="subscriber failed",
        )

    def test_force_batch_logs_aggregate_start_and_completion(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        pending = self._meta("Pending", MDX_ARCH_TYPE, _YAML_URL)
        manager.catalogue_meta = {pending.label: pending}
        manager.catalogue_meta_by_family = {"mdx": {pending.label: pending}}
        manager.mdx_download_list = {pending.label: pending.files}
        completions: list[object] = []

        with (
            mock.patch.object(csc, "enqueue_missing", side_effect=_accept_reserved_urls),
            mock.patch.object(csc, "ensure_worker_started"),
            mock.patch("core.downloads.log_event") as event,
            access_policy(
                allow_network=True,
                allow_metadata_writes=False,
                allow_cache_writes=False,
            ),
        ):
            manager.force_revalidate_catalogue_evidence(completions.append)
            unavailable = dataclasses.replace(
                manager.catalogue_meta_by_family["mdx"][pending.label],
                catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
                catalogue_evidence_warning="request failed",
            )
            manager.catalogue_meta_by_family["mdx"][pending.label] = unavailable
            manager.catalogue_meta[pending.label] = unavailable
            with (
                mock.patch.object(csc, "pending_urls", return_value=frozenset()),
                mock.patch.object(
                    manager, "apply_catalogue_stem_cache", return_value={pending.label}
                ),
            ):
                manager._on_catalogue_evidence_cache_update()

        self.assertEqual(len(completions), 1)
        summary = typing.cast(Any, completions[0])
        self.assertEqual(summary.unavailable, 1)
        names = [call.args[1] for call in event.call_args_list]
        self.assertEqual(
            names,
            ["catalogue_evidence_batch_started", "catalogue_evidence_batch_completed"],
        )
        completed = event.call_args_list[-1]
        self.assertEqual(completed.kwargs["level"], "debug")
        self.assertEqual(completed.kwargs["unavailable"], 1)
        self.assertEqual(completed.kwargs["pending"], 0)
        for aggregate in event.call_args_list:
            for field in (
                "reviewed",
                "raw",
                "waived",
                "pending",
                "unavailable",
                "stale",
            ):
                self.assertIn(field, aggregate.kwargs)

    def test_force_batch_failure_log_uses_exact_identity_and_bounded_error(self) -> None:
        import core.catalogue_stem_cache as csc

        manager = DownloadManager()
        meta = dataclasses.replace(
            self._meta("Failure", MDX_ARCH_TYPE, _YAML_URL),
            checkpoint="m.ckpt",
        )
        manager.catalogue_meta = {meta.label: meta}
        manager.catalogue_meta_by_family = {"mdx": {meta.label: meta}}
        manager.mdx_download_list = {meta.label: meta.files}
        manager._catalogue_evidence_url_entries = {_YAML_URL: [("mdx", meta.label)]}
        failure = StemCacheHit(
            stems=(),
            target_instrument=None,
            ok=False,
            last_error=StemCacheError("http", "HTTP 503", 1.0),
        )

        with (
            mock.patch.object(csc, "lookup_stems", return_value=failure),
            mock.patch(
                "core.catalogue_identity.catalogue_model_id",
                return_value="mdx:m",
            ),
            mock.patch("core.downloads.log_event") as event,
        ):
            manager._log_catalogue_evidence_failures((_YAML_URL,))

        event.assert_called_once_with(
            "download",
            "catalogue_evidence_validation_failed",
            level="warning",
            model_id="mdx:m",
            url=_YAML_URL,
            error_type="http",
            message="HTTP 503",
        )


class StemSubtitleDebounceTests(unittest.TestCase):
    def test_row_metadata_lookup_is_family_scoped_for_colliding_labels(self) -> None:
        from ui.download_center import DownloadCenterWindow

        shared = "Shared label"
        mdx = EntryMeta(
            label=shared,
            display=shared,
            arch=MDX_ARCH_TYPE,
            files={},
            catalogue_evidence_status=CatalogueEvidenceState.PENDING,
        )
        vr = dataclasses.replace(
            mdx,
            arch=VR_ARCH_TYPE,
            catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
        )
        win = typing.cast(Any, object.__new__(DownloadCenterWindow))
        win.manager = SimpleNamespace(
            catalogue_meta={shared: vr},
            catalogue_meta_by_family={"mdx": {shared: mdx}, "vr": {shared: vr}},
        )

        self.assertIs(win._catalogue_row_metadata(MDX_ARCH_TYPE, shared), mdx)
        self.assertIs(win._catalogue_row_metadata(VR_ARCH_TYPE, shared), vr)

    def test_reviewed_subtitle_uses_exact_route_labels_and_reviewed_purpose(self) -> None:
        from ui.download_center import catalogue_semantics_subtitle

        semantics = resolve_model_stem_semantics(
            "mdx:UVR_MDXNET_KARA_2",
            native_stems=("Instrumental", "Vocals"),
            backend_primary="Instrumental",
        )
        projection = stem_semantics_projection(
            semantics,
            backend_primary="Instrumental",
            backend_target="other",
        )
        meta = EntryMeta(
            label="K",
            display="K",
            arch=MDX_ARCH_TYPE,
            files={},
            stems=["Instrumental", "Vocals"],
            intent=semantics.intent,
            stem_semantics=projection,
            catalogue_evidence_status=CatalogueEvidenceState.READY,
        )

        self.assertEqual(
            (projection.logical_primary_role, projection.logical_secondary_role),
            ("mix.instrumental_with_backing_vocals", "vocal.lead"),
        )
        self.assertEqual(
            tuple(
                (
                    route.native,
                    route.role,
                    route.logical_primary,
                    route.logical_secondary,
                    route.selected_by_default,
                )
                for route in projection.routes
            ),
            (
                (
                    "Instrumental",
                    "mix.instrumental_with_backing_vocals",
                    True,
                    False,
                    True,
                ),
                ("Vocals", "vocal.lead", False, True, True),
            ),
        )
        self.assertEqual(
            catalogue_semantics_subtitle(meta),
            "Karaoke · Instrumental with Backing Vocals, Lead Vocals",
        )

    def test_reviewed_ready_and_stale_use_mapped_dual_vocal_and_specialty_purposes(
        self,
    ) -> None:
        from core.model_stem_semantics import INTENT_DUAL_VOC_INST, INTENT_SPECIALTY_STEM
        from ui.download_center import catalogue_semantics_subtitle

        semantics = resolve_model_stem_semantics(
            "mdx:UVR_MDXNET_KARA_2",
            native_stems=("Instrumental", "Vocals"),
            backend_primary="Instrumental",
        )
        projection = stem_semantics_projection(semantics)
        for intent, purpose in (
            (INTENT_DUAL_VOC_INST, "Vocals"),
            (INTENT_SPECIALTY_STEM, "Specialty"),
        ):
            for state in (CatalogueEvidenceState.READY, CatalogueEvidenceState.STALE):
                with self.subTest(intent=intent, state=state):
                    meta = EntryMeta(
                        label="Reviewed",
                        display="Reviewed",
                        arch=MDX_ARCH_TYPE,
                        files={},
                        stems=["Instrumental", "Vocals"],
                        intent=intent,
                        stem_semantics=projection,
                        catalogue_evidence_status=state,
                    )

                    self.assertTrue(catalogue_semantics_subtitle(meta).startswith(f"{purpose} · "))

    def test_reviewed_stale_subtitle_keeps_curated_routes_and_warning_detail(self) -> None:
        from ui.download_center import (
            catalogue_evidence_detail,
            catalogue_semantics_subtitle,
        )

        semantics = resolve_model_stem_semantics(
            "mdx:UVR_MDXNET_KARA_2",
            native_stems=("Instrumental", "Vocals"),
            backend_primary="Instrumental",
        )
        meta = EntryMeta(
            label="K",
            display="K",
            arch=MDX_ARCH_TYPE,
            files={},
            stems=["Instrumental", "Vocals"],
            intent=semantics.intent,
            stem_semantics=stem_semantics_projection(semantics),
            catalogue_evidence_status=CatalogueEvidenceState.STALE,
            catalogue_evidence_warning="Last validation failed; reviewed details may be stale",
        )

        self.assertEqual(
            catalogue_semantics_subtitle(meta),
            "Karaoke · Instrumental with Backing Vocals, Lead Vocals",
        )
        self.assertEqual(
            catalogue_evidence_detail(meta),
            "Last validation failed; reviewed details may be stale",
        )

    def test_pending_without_evidence_has_loading_subtitle(self) -> None:
        from ui.download_center import catalogue_semantics_subtitle

        meta = EntryMeta(
            label="Pending",
            display="Pending",
            arch=MDX_ARCH_TYPE,
            files={"m.yaml": _YAML_URL},
            catalogue_evidence_status=CatalogueEvidenceState.PENDING,
        )

        self.assertEqual(catalogue_semantics_subtitle(meta), "Loading output details…")

    def test_failed_without_evidence_has_unavailable_subtitle(self) -> None:
        from ui.download_center import catalogue_semantics_subtitle

        meta = EntryMeta(
            label="Failed",
            display="Failed",
            arch=MDX_ARCH_TYPE,
            files={"m.yaml": _YAML_URL},
            catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
        )

        self.assertEqual(catalogue_semantics_subtitle(meta), "Output details unavailable")

    def test_apollo_waiver_is_restoration_not_raw(self) -> None:
        from ui.download_center import catalogue_semantics_subtitle

        meta = EntryMeta(
            label="Apollo",
            display="Apollo",
            arch=APOLLO_ARCH_TYPE,
            files={},
            catalogue_evidence_status=CatalogueEvidenceState.NOT_APPLICABLE,
        )

        self.assertEqual(
            catalogue_semantics_subtitle(meta),
            "Restoration · output details not applicable",
        )

    def test_observed_mismatch_renders_raw_observed_native_names(self) -> None:
        from ui.download_center import catalogue_semantics_subtitle

        meta = EntryMeta(
            label="Mismatch",
            display="Mismatch",
            arch=MDX_ARCH_TYPE,
            files={"m.yaml": _YAML_URL},
            stems=["mysteryLead", "mysteryBack"],
            catalogue_evidence_status=CatalogueEvidenceState.READY,
            catalogue_evidence_warning="catalogue-evidence-mismatch model_id=mdx:mismatch",
        )

        self.assertEqual(
            catalogue_semantics_subtitle(meta),
            "Raw outputs · mysteryLead, mysteryBack",
        )

    def test_genuine_unknown_renders_raw_without_inventing_names(self) -> None:
        from ui.download_center import catalogue_semantics_subtitle

        meta = EntryMeta(
            label="Unknown",
            display="Unknown",
            arch=VR_ARCH_TYPE,
            files={"unknown.onnx": "https://example.test/unknown.onnx"},
            catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
        )

        self.assertEqual(catalogue_semantics_subtitle(meta), "Raw outputs")

    def test_raw_subtitle_is_explicit_and_preserves_native_names(self) -> None:
        from ui.download_center import catalogue_semantics_subtitle

        meta = EntryMeta(
            label="Private",
            display="Private",
            arch=MDX_ARCH_TYPE,
            files={},
            stems=["mysteryLead", "mysteryBack"],
        )

        self.assertEqual(
            catalogue_semantics_subtitle(meta),
            "Raw outputs · mysteryLead, mysteryBack",
        )

    def _bare_window(self) -> Any:
        from ui.download_center import DownloadCenterWindow

        win = typing.cast(Any, object.__new__(DownloadCenterWindow))
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

        with (
            mock.patch("ui.download_center.stash"),
            mock.patch(
                "ui.download_center.fetch", side_effect=lambda _row, key, default=None: default
            ),
            mock.patch("ui.download_center.set_row_subtitle") as set_subtitle,
        ):
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
        self.assertEqual(fetch(action, "_uvr_stems_text"), "Raw outputs · Vocals, other")

    def test_schedule_hops_to_main_via_idle_on_main(self) -> None:
        win = self._bare_window()
        idle_calls: list[Any] = []

        def fake_idle(fn: Any, *args: Any, **kwargs: Any) -> None:
            idle_calls.append(fn)

        with mock.patch("ui.download_center.idle_on_main", side_effect=fake_idle):
            win._schedule_stem_subtitle_refresh()

        self.assertEqual(len(idle_calls), 1)
        self.assertEqual(idle_calls[0], win._arm_stem_subtitle_refresh)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK row transitions need a display",
)
class DownloadCenterGtkEvidenceTransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.download-evidence-row")
        cls._app.register()

    def _window_with_pending_row(self) -> tuple[Any, Any, Any]:
        from gi.repository import Gtk

        from ui.download_center import DownloadCenterWindow

        meta = EntryMeta(
            label="Canonical selection",
            display="Canonical selection",
            arch=MDX_ARCH_TYPE,
            files={"model.ckpt": "https://example.test/model.ckpt", "model.yaml": _YAML_URL},
            catalogue_evidence_status=CatalogueEvidenceState.PENDING,
        )
        manager = SimpleNamespace(
            catalogue_meta={meta.label: meta},
            catalogue_meta_by_family={"mdx": {meta.label: meta}},
            mdx_download_list={meta.label: meta.files},
            apply_catalogue_stem_cache=mock.MagicMock(return_value={meta.label}),
        )
        win = typing.cast(Any, object.__new__(DownloadCenterWindow))
        win.manager = manager
        win._row_checks = {}
        win._row_actions = {}
        win._size_lookup_ids = {}
        win._list_boxes = {MDX_ARCH_TYPE: Gtk.ListBox()}
        win._stem_refresh_armed = True
        win._update_download_button = mock.MagicMock()
        win._lookup_row_size = mock.MagicMock()
        win._rebuild_catalogue = mock.MagicMock()
        with mock.patch.object(
            win,
            "_row_score",
            return_value=(None, None, "Loading output details…"),
        ):
            win._add_model_row(MDX_ARCH_TYPE, meta.label)
        check = win._row_checks[(MDX_ARCH_TYPE, meta.label)]
        check.set_active(True)

        adjustment = Gtk.Adjustment(lower=0, upper=100, step_increment=1, page_size=10)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vadjustment(adjustment)
        scroller.set_child(win._list_boxes[MDX_ARCH_TYPE])
        win._test_scroller = scroller
        adjustment.set_value(42)
        return win, adjustment, meta

    def test_pending_to_ready_mutates_existing_row_and_preserves_browser_state(self) -> None:
        from ui.download_center import DownloadCenterWindow
        from ui.widget_state import fetch

        win, adjustment, pending = self._window_with_pending_row()
        key = (MDX_ARCH_TYPE, pending.label)
        action = win._row_actions[key]
        check = win._row_checks[key]
        semantics = resolve_model_stem_semantics(
            "mdx:UVR_MDXNET_KARA_2",
            native_stems=("Instrumental", "Vocals"),
            backend_primary="Instrumental",
        )
        ready = dataclasses.replace(
            pending,
            stems=["Instrumental", "Vocals"],
            intent=semantics.intent,
            stem_semantics=stem_semantics_projection(semantics),
            catalogue_evidence_status=CatalogueEvidenceState.READY,
        )
        win.manager.catalogue_meta[pending.label] = ready
        win.manager.catalogue_meta_by_family["mdx"][pending.label] = ready

        DownloadCenterWindow._flush_stem_subtitles(win)

        self.assertIs(win._row_actions[key], action)
        self.assertEqual(adjustment.get_value(), 42)
        self.assertTrue(check.get_active())
        self.assertEqual(fetch(action, "_uvr_model_name"), pending.label)
        self.assertEqual(win._selected_entries(), [(pending.label, MDX_ARCH_TYPE)])
        self.assertIn("Instrumental with Backing Vocals", action.get_subtitle())
        win._rebuild_catalogue.assert_not_called()

    def test_pending_to_unavailable_mutates_existing_row_and_preserves_browser_state(self) -> None:
        from ui.download_center import DownloadCenterWindow
        from ui.widget_state import fetch

        win, adjustment, pending = self._window_with_pending_row()
        key = (MDX_ARCH_TYPE, pending.label)
        action = win._row_actions[key]
        check = win._row_checks[key]
        unavailable = dataclasses.replace(
            pending,
            catalogue_evidence_status=CatalogueEvidenceState.UNAVAILABLE,
            catalogue_evidence_warning="request failed",
        )
        win.manager.catalogue_meta[pending.label] = unavailable
        win.manager.catalogue_meta_by_family["mdx"][pending.label] = unavailable

        DownloadCenterWindow._flush_stem_subtitles(win)

        self.assertIs(win._row_actions[key], action)
        self.assertEqual(adjustment.get_value(), 42)
        self.assertTrue(check.get_active())
        self.assertEqual(fetch(action, "_uvr_model_name"), pending.label)
        self.assertEqual(win._selected_entries(), [(pending.label, MDX_ARCH_TYPE)])
        self.assertIn("Output details unavailable", action.get_subtitle())
        self.assertEqual(action.get_tooltip_text(), "request failed")
        win._rebuild_catalogue.assert_not_called()


class DownloadCenterStemSubscriptionTests(unittest.TestCase):
    def test_ensure_background_listeners_subscribes_and_starts_worker(self) -> None:
        from ui.download_center import DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._stem_refresh_armed = False
        win.manager = mock.MagicMock()

        with (
            mock.patch("core.catalogue_stem_cache.subscribe") as subscribe,
            mock.patch("core.catalogue_stem_cache.ensure_worker_started") as ensure,
        ):
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
        win.manager = mock.MagicMock()
        win._pinned_snapshot = None
        win._pending_source_delta = False

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
        win.manager = mock.MagicMock()

        with mock.patch("gi.repository.GLib.timeout_add") as timeout_add:
            for _ in range(5):
                DownloadCenterWindow._schedule_stem_yaml_fetches(win)

        self.assertEqual(timeout_add.call_count, 1)
        callback = timeout_add.call_args[0][1]

        # Once the timeout fires the next burst must arm again.
        with (
            mock.patch.object(win, "_visible_catalogue_entries", return_value=[]),
            mock.patch.object(win, "_all_catalogue_entries", return_value=[]),
        ):
            self.assertFalse(callback())
        with mock.patch("gi.repository.GLib.timeout_add") as timeout_add2:
            DownloadCenterWindow._schedule_stem_yaml_fetches(win)
        self.assertEqual(timeout_add2.call_count, 1)

    def test_visible_labels_scoped_to_active_tab(self) -> None:
        """ "Visible" must mean the tab on screen, not every tab's filter result."""
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

    def test_visible_entries_keep_family_with_canonical_selection(self) -> None:
        from ui.download_center import PURPOSE_ALL, DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._available = {
            MDX_ARCH_TYPE: ["Shared Model"],
            VR_ARCH_TYPE: ["Shared Model"],
        }
        win._search_entries = {}
        win._purpose = PURPOSE_ALL
        win.stack = mock.MagicMock()
        win.stack.get_visible_child_name.return_value = MDX_ARCH_TYPE

        self.assertEqual(win._visible_catalogue_entries(), [("mdx", "Shared Model")])

    def test_priority_flush_filters_colliding_label_with_active_family_intent(self) -> None:
        from core.model_scores import PURPOSE_VOCALS
        from core.model_stem_semantics import INTENT_DUAL_VOC_INST, INTENT_SPECIALTY_STEM
        from ui.download_center import DownloadCenterWindow

        shared = "Shared Model"
        mdx = EntryMeta(
            label=shared,
            display=shared,
            arch=MDX_ARCH_TYPE,
            files={"m.ckpt": "https://example.test/mdx.ckpt", "m.yaml": _YAML_URL},
            intent=INTENT_DUAL_VOC_INST,
        )
        vr = dataclasses.replace(
            mdx,
            arch=VR_ARCH_TYPE,
            files={"m.pth": "https://example.test/vr.pth"},
            intent=INTENT_SPECIALTY_STEM,
        )
        win = typing.cast(Any, object.__new__(DownloadCenterWindow))
        win.manager = mock.MagicMock()
        win.manager.catalogue_meta = {shared: vr}
        win.manager.catalogue_meta_by_family = {
            "mdx": {shared: mdx},
            "vr": {shared: vr},
        }
        win._available = {
            MDX_ARCH_TYPE: [shared],
            VR_ARCH_TYPE: [shared],
        }
        win._search_entries = {}
        win._purpose = PURPOSE_VOCALS
        win._stem_fetch_armed = True
        win.stack = mock.MagicMock()
        win.stack.get_visible_child_name.return_value = MDX_ARCH_TYPE

        DownloadCenterWindow._flush_stem_yaml_fetches(win)

        self.assertEqual(
            win.manager.queue_catalogue_evidence.call_args_list,
            [
                mock.call((("mdx", shared),), priority=True),
                mock.call((("vr", shared),), priority=False),
            ],
        )

    def test_row_filter_uses_family_intent_for_colliding_label(self) -> None:
        from core.model_scores import PURPOSE_VOCALS
        from core.model_stem_semantics import INTENT_DUAL_VOC_INST, INTENT_SPECIALTY_STEM
        from ui.download_center import DownloadCenterWindow

        shared = "Shared Model"
        mdx = EntryMeta(
            label=shared,
            display=shared,
            arch=MDX_ARCH_TYPE,
            intent=INTENT_DUAL_VOC_INST,
        )
        vr = dataclasses.replace(
            mdx,
            arch=VR_ARCH_TYPE,
            intent=INTENT_SPECIALTY_STEM,
        )
        win = typing.cast(Any, object.__new__(DownloadCenterWindow))
        win.manager = SimpleNamespace(
            catalogue_meta={shared: vr},
            catalogue_meta_by_family={"mdx": {shared: mdx}, "vr": {shared: vr}},
        )
        win._purpose = PURPOSE_VOCALS
        win._hide_unsupported = False
        win._search_entries = {}
        action = object()

        def row_value(_action: object, key: str, default: object) -> object:
            values = {
                "_uvr_model_name": shared,
                "_uvr_unsupported": False,
            }
            return values.get(key, default)

        with (
            mock.patch.object(win, "_catalogue_row_action", return_value=action),
            mock.patch("ui.download_center.fetch", side_effect=row_value),
        ):
            self.assertTrue(win._row_matches_filter(mock.MagicMock(), MDX_ARCH_TYPE))
            self.assertFalse(win._row_matches_filter(mock.MagicMock(), VR_ARCH_TYPE))

    def test_visible_labels_fall_back_when_no_active_tab(self) -> None:
        from ui.download_center import PURPOSE_ALL, DownloadCenterWindow

        win = object.__new__(DownloadCenterWindow)
        win._available = {MDX_ARCH_TYPE: ["MDX Model"], "VR Arc": ["VR Model"]}
        win._search_entries = {}
        win._purpose = PURPOSE_ALL
        win.stack = mock.MagicMock()
        win.stack.get_visible_child_name.return_value = None

        self.assertEqual(sorted(win._visible_catalogue_labels()), ["MDX Model", "VR Model"])

    def test_pending_urls_refetch_fresh_legacy_success_without_digest(self) -> None:
        import core.catalogue_stem_cache as csc
        from ui.download_center import DownloadCenterWindow

        meta = EntryMeta(
            label="Legacy",
            display="Legacy",
            arch=MDX_ARCH_TYPE,
            files={"m.ckpt": "https://example.test/m.ckpt", "m.yaml": _YAML_URL},
            stems=["Vocals", "other"],
        )
        win = object.__new__(DownloadCenterWindow)
        typing.cast(Any, win).manager = SimpleNamespace(catalogue_meta={meta.label: meta})

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "catalogue_stem_cache.json")
            with (
                mock.patch.object(csc, "_cache_path", return_value=cache_path),
                mock.patch("core.model_display.clear_display_cache"),
            ):
                csc.clear_catalogue_stem_cache()
                try:
                    _write_legacy_success_cache(cache_path, _YAML_URL)
                    pending = DownloadCenterWindow._pending_stem_yaml_urls(win)
                finally:
                    csc.clear_catalogue_stem_cache()

        self.assertEqual(pending, [_YAML_URL])

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

        def meta_for(
            label: str,
            yaml_url: str | None,
            stems: list[str],
            *,
            reviewed: bool = False,
        ) -> EntryMeta:
            files = {"m.ckpt": f"https://example.test/{label}.ckpt"}
            if yaml_url:
                files["m.yaml"] = yaml_url
            projection = EntryMeta(label="", display="", arch="").stem_semantics
            if reviewed:
                semantics = resolve_model_stem_semantics(
                    "mdx:UVR_MDXNET_KARA_2",
                    native_stems=("Instrumental", "Vocals"),
                    backend_primary="Instrumental",
                )
                projection = stem_semantics_projection(semantics)
            return EntryMeta(
                label=label,
                display=label,
                arch=MDX_ARCH_TYPE,
                files=files,
                stems=stems,
                stem_semantics=projection,
                catalogue_evidence_status=(
                    CatalogueEvidenceState.READY if reviewed else CatalogueEvidenceState.UNAVAILABLE
                ),
            )

        cached_url = "https://example.test/cached.yaml"
        failed_url = "https://example.test/failed.yaml"
        catalogue_meta = {
            # Matches the "kim" query; needs a fetch.
            "Kim Vocal 1": meta_for("Kim Vocal 1", "https://example.test/kim.yaml", []),
            # Matches and has source stems, but still lacks exact config evidence.
            "Kim Inst 2": meta_for("Kim Inst 2", "https://example.test/inst.yaml", ["Vocals"]),
            # Matches, but the stem cache already answers for it — must be skipped.
            "Kim Cached 3": meta_for("Kim Cached 3", cached_url, []),
            # Reviewed rows do not need another config fetch.
            "Kim Reviewed 4": meta_for(
                "Kim Reviewed 4",
                "https://example.test/reviewed.yaml",
                ["Instrumental", "Vocals"],
                reviewed=True,
            ),
            # A fresh failure retains its shorter failure TTL and is not retried yet.
            "Kim Failed 5": meta_for("Kim Failed 5", failed_url, []),
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
        win._search_entries = typing.cast("dict[str, Any]", {MDX_ARCH_TYPE: _Entry("kim")})
        win._purpose = PURPOSE_ALL
        win.stack = mock.MagicMock()
        win.stack.get_visible_child_name.return_value = MDX_ARCH_TYPE

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "catalogue_stem_cache.json")
            with mock.patch.object(csc, "_cache_path", return_value=cache_path):
                with mock.patch("core.model_display.clear_display_cache"):
                    csc.clear_catalogue_stem_cache()
                    csc.remember_stems(
                        cached_url,
                        ["Vocals", "other"],
                        "Vocals",
                        content_sha256="c" * 64,
                        ok=True,
                    )
                    csc.remember_stems(failed_url, [], None, ok=False)
                    win.manager.queue_catalogue_evidence.side_effect = [
                        ("https://example.test/kim.yaml", "https://example.test/inst.yaml"),
                        ("https://example.test/other.yaml",),
                    ]
                    DownloadCenterWindow._flush_stem_yaml_fetches(win)
                    csc.clear_catalogue_stem_cache()

        self.assertEqual(
            win.manager.queue_catalogue_evidence.call_args_list,
            [
                mock.call(
                    (
                        ("mdx", "Kim Vocal 1"),
                        ("mdx", "Kim Inst 2"),
                        ("mdx", "Kim Cached 3"),
                        ("mdx", "Kim Reviewed 4"),
                        ("mdx", "Kim Failed 5"),
                    ),
                    priority=True,
                ),
                mock.call(
                    (
                        ("mdx", "Other Model"),
                        ("mdx", "No Yaml"),
                    ),
                    priority=False,
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
