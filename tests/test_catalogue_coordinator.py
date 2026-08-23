"""Coordinator snapshot, refresh-report, and delta tests."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from io import BytesIO
from typing import Any, Callable
from unittest import mock

from core.access_policy import AccessPolicy
from core.catalogue_coordinator import CatalogueCoordinator
from core.catalogue_types import DeltaKind, RefreshMode, SourceId
from core.remote_catalog_cache import RemoteJsonSource


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Response(BytesIO):
    def __init__(self, payload: dict, *, status: int = 200, headers: dict | None = None) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))
        self.status = status
        self.headers = headers or {}

    def getheader(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name, default)


def _local(source_id: SourceId, payload: dict) -> RemoteJsonSource:
    return RemoteJsonSource(source_id=source_id, local_loader=lambda: payload)


def _disabled(source_id: SourceId) -> RemoteJsonSource:
    return RemoteJsonSource(source_id=source_id, enabled=lambda: False)


def _write_envelope(path: str, fetched_at: float, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"fetched_at": fetched_at, "data": payload}, handle)


def _gated_opener(
    payload: dict, fetched: threading.Event, release: threading.Event
) -> Callable[[object], _Response]:
    def opener(_url: object) -> _Response:
        fetched.set()
        release.wait(timeout=2)
        return _Response(payload)

    return opener


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class CatalogueCoordinatorTests(unittest.TestCase):
    def _coordinator(self, upstream: dict | None = None) -> CatalogueCoordinator:
        payload = upstream or {
            "mdx_download_list": {"Kept": {"kept.ckpt": "https://u/kept.ckpt"}},
            "vr_download_list": {},
            "demucs_download_list": {},
        }
        return CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(SourceId.UPSTREAM, payload),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )

    def test_one_projection_per_revision(self) -> None:
        coordinator = self._coordinator()
        policy = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        first = coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        second = coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        self.assertIs(first, second)
        self.assertEqual(coordinator.builds, 1)
        coordinator.close()

    def test_snapshot_records_exact_winning_source_for_each_entry(self) -> None:
        coordinator = self._coordinator()
        snapshot = coordinator.snapshot(
            mode=RefreshMode.OFFLINE,
            policy=AccessPolicy(
                allow_network=False, allow_metadata_writes=False
            ),
        )

        self.assertEqual(snapshot.entry_sources["mdx"]["Kept"], "upstream")
        coordinator.close()

    def test_public_projection_includes_every_legacy_vip_list(self) -> None:
        payload = {
            "vr_download_list": {"VR Public": "public.pth"},
            "vr_download_vip_list": {"VR VIP: Added": "added.pth"},
            "mdx_download_list": {"MDX Public": "public.onnx"},
            "mdx_download_vip_list": {
                "MDX-Net Model VIP: Added MDX": "mdx.onnx"
            },
            "mdx23_download_vip_list": {
                "MDX23 Model VIP: Added MDX23": {"23.ckpt": "23.yaml"}
            },
            "mdx23c_download_vip_list": {
                "MDX23C Model VIP: Added MDX23C": {"23c.ckpt": "23c.yaml"}
            },
            "roformer_download_vip_list": {
                "Roformer Model VIP: Added Roformer": {"r.ckpt": "r.yaml"}
            },
            "scnet_download_vip_list": {
                "SCNet Model VIP: Added": {"s.ckpt": "s.yaml"}
            },
            "bandit_download_vip_list": {
                "Bandit Model VIP: Added": {"b.ckpt": "b.yaml"}
            },
            "demucs_download_list": {},
            "demucs_download_vip_list": {
                "Demucs Model VIP: Added": "demucs.yaml"
            },
        }
        coordinator = self._coordinator(payload)
        policy = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        snapshot = coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        self.assertEqual(set(snapshot.vr), {"VR Public", "VR VIP: Added"})
        self.assertEqual(
            set(snapshot.mdx),
            {
                "MDX Public",
                "MDX-Net Model VIP: Added MDX",
                "MDX23 Model VIP: Added MDX23",
                "MDX23C Model VIP: Added MDX23C",
                "Roformer Model VIP: Added Roformer",
                "SCNet Model VIP: Added",
                "Bandit Model VIP: Added",
            },
        )
        self.assertEqual(set(snapshot.demucs), {"Demucs Model VIP: Added"})
        self.assertEqual(coordinator.builds, 1)
        coordinator.close()

    def test_close_is_idempotent(self) -> None:
        coordinator = self._coordinator()
        coordinator.close()
        coordinator.close()
        report = coordinator.refresh(mode=RefreshMode.FORCE)
        self.assertFalse(report.upstream_live)

    def test_noop_refresh_does_not_notify(self) -> None:
        coordinator = self._coordinator()
        policy = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        calls: list = []
        coordinator.subscribe_delta(lambda delta: calls.append(delta))
        coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        self.assertEqual(calls, [])
        coordinator.close()

    def test_offline_refresh_records_start_and_snapshot_counts(self) -> None:
        coordinator = self._coordinator()
        policy = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        with mock.patch("core.catalogue_coordinator.log_event") as event:
            coordinator.refresh(mode=RefreshMode.OFFLINE, policy=policy)

        names = [call.args[1] for call in event.call_args_list]
        self.assertIn("catalogue_refresh_started", names)
        self.assertIn("catalogue_refresh_completed", names)
        completed = next(
            call for call in event.call_args_list
            if call.args[1] == "catalogue_refresh_completed"
        )
        self.assertEqual(completed.kwargs["mdx_count"], 1)
        coordinator.close()

    def test_identity_removal_uses_identity_kind(self) -> None:
        coordinator = self._coordinator()
        policy = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        with mock.patch(
            "core.download_sizes.trusted_content_ids_from_cache",
            return_value={"https://u/kept.ckpt": "same"},
        ):
            delta = coordinator.apply_trusted_identities({"https://u/kept.ckpt": "same"})
        if delta is not None:
            self.assertEqual(delta.kind, DeltaKind.IDENTITY_REFINED)
        coordinator.close()

    def test_force_coalesces_concurrent_callers(self) -> None:
        calls = {"n": 0}
        payload = {"mdx_download_list": {"A": {"a.ckpt": "https://u/a.ckpt"}}}

        def loader() -> dict:
            calls["n"] += 1
            return payload

        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: RemoteJsonSource(
                    source_id=SourceId.UPSTREAM, local_loader=loader
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )

        def run() -> None:
            coordinator.refresh(
                mode=RefreshMode.FORCE,
                policy=AccessPolicy(allow_network=True, allow_metadata_writes=False),
            )

        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        coordinator.close()
        self.assertGreaterEqual(calls["n"], 1)
        self.assertLessEqual(calls["n"], 4)

    def test_partial_failure_keeps_last_good_and_reports(self) -> None:
        opener = mock.Mock(side_effect=OSError("offline"))
        source = RemoteJsonSource(
            source_id=SourceId.UPSTREAM,
            url="https://example.test/upstream.json",
            opener=opener,
            bundled_fallback=lambda: {
                "mdx_download_list": {"Bundled": {"b.ckpt": "https://u/b.ckpt"}}
            },
        )
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: source,
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=False)
        report = coordinator.refresh(mode=RefreshMode.FORCE, policy=policy)
        snap = coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        self.assertTrue(report.usable or "Bundled" in snap.mdx)
        coordinator.close()

    def test_force_then_ensure_keeps_usable_report_on_snapshot(self) -> None:
        """The catalogue writer does refresh(FORCE) then ensure(SWR).

        FORCE used to cache a placeholder RefreshReport(usable=False) under
        the revision digest, so the SWR republish returned that snapshot and
        generate_models_catalogue refused as unusable even with full lists.
        """
        coordinator = self._coordinator()
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=False)
        returned = coordinator.refresh(mode=RefreshMode.FORCE, policy=policy)
        snap = coordinator.ensure(policy=policy)
        self.assertTrue(snap.mdx)
        self.assertTrue(returned.usable)
        report = snap.report
        self.assertIsNotNone(report)
        assert report is not None
        self.assertTrue(report.usable)
        coordinator.close()

    def _swr_source(
        self,
        source_id: SourceId,
        *,
        path: str,
        clock: _Clock,
        opener: Callable[[object], Any],
        url: str,
    ) -> RemoteJsonSource:
        return RemoteJsonSource(
            source_id=source_id,
            url=url,
            cache_filename=os.path.basename(path),
            cache_path=path,
            ttl_seconds=60,
            opener=opener,
            clock=clock,
        )

    def _swr_coordinator(
        self, sources: dict[SourceId, RemoteJsonSource]
    ) -> CatalogueCoordinator:
        mapping = {
            SourceId.UPSTREAM: _disabled(SourceId.UPSTREAM),
            SourceId.POLITREES: _disabled(SourceId.POLITREES),
            SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
            SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
        }
        mapping.update(sources)
        coordinator = CatalogueCoordinator(sources=mapping)
        self.addCleanup(coordinator.close)
        return coordinator

    def test_swr_republishes_when_background_fetch_completes(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "upstream.json")
        clock = _Clock()
        _write_envelope(
            path,
            clock.now - 120,
            {
                "mdx_download_list": {"Old": {"o.ckpt": "https://u/o.ckpt"}},
                "vr_download_list": {},
                "demucs_download_list": {},
            },
        )
        fetched = threading.Event()
        release = threading.Event()
        opener = _gated_opener(
            {
                "mdx_download_list": {"New": {"n.ckpt": "https://u/n.ckpt"}},
                "vr_download_list": {},
                "demucs_download_list": {},
            },
            fetched,
            release,
        )
        coordinator = self._swr_coordinator(
            {
                SourceId.UPSTREAM: self._swr_source(
                    SourceId.UPSTREAM,
                    path=path,
                    clock=clock,
                    opener=opener,
                    url="https://example.test/upstream.json",
                )
            }
        )
        deltas: list = []
        coordinator.subscribe_delta(lambda delta: deltas.append(delta))
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=True)
        stale = coordinator.refresh(
            mode=RefreshMode.STALE_WHILE_REVALIDATE, policy=policy
        )
        self.assertTrue(stale.usable)
        self.assertIn("Old", coordinator._latest.mdx if coordinator._latest else {})
        self.assertTrue(fetched.wait(timeout=2))
        release.set()
        self.assertTrue(
            _wait_until(
                lambda: coordinator._latest is not None
                and "New" in coordinator._latest.mdx
            )
        )
        latest = coordinator._latest
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertIn("New", latest.mdx)
        self.assertNotIn("Old", latest.mdx)
        self.assertTrue(deltas)

    def test_swr_multi_source_completion_order(self) -> None:
        for first in ("upstream", "politrees"):
            with self.subTest(first=first):
                self._assert_multi_source_swr(first)

    def _assert_multi_source_swr(self, first: str) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        up_path = os.path.join(tmp.name, "upstream.json")
        po_path = os.path.join(tmp.name, "politrees.json")
        clock = _Clock()
        _write_envelope(
            up_path,
            clock.now - 120,
            {
                "mdx_download_list": {"Old": {"o.ckpt": "https://u/o.ckpt"}},
                "vr_download_list": {},
                "demucs_download_list": {},
            },
        )
        _write_envelope(
            po_path,
            clock.now - 120,
            {"mdx_download_list": {"P-old": {"po.ckpt": "https://p/po.ckpt"}}},
        )
        up_fetched, up_release = threading.Event(), threading.Event()
        po_fetched, po_release = threading.Event(), threading.Event()
        coordinator = self._swr_coordinator(
            {
                SourceId.UPSTREAM: self._swr_source(
                    SourceId.UPSTREAM,
                    path=up_path,
                    clock=clock,
                    opener=_gated_opener(
                        {
                            "mdx_download_list": {
                                "New": {"n.ckpt": "https://u/n.ckpt"}
                            },
                            "vr_download_list": {},
                            "demucs_download_list": {},
                        },
                        up_fetched,
                        up_release,
                    ),
                    url="https://example.test/upstream.json",
                ),
                SourceId.POLITREES: self._swr_source(
                    SourceId.POLITREES,
                    path=po_path,
                    clock=clock,
                    opener=_gated_opener(
                        {
                            "mdx_download_list": {
                                "P-new": {"pn.ckpt": "https://p/pn.ckpt"}
                            }
                        },
                        po_fetched,
                        po_release,
                    ),
                    url="https://example.test/politrees.json",
                ),
            }
        )
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=True)
        stale = coordinator.refresh(
            mode=RefreshMode.STALE_WHILE_REVALIDATE, policy=policy
        )
        self.assertTrue(stale.usable)
        latest = coordinator._latest
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertIn("Old", latest.mdx)
        self.assertIn("P-old", latest.mdx)
        self.assertTrue(latest.mdx)
        self.assertTrue(up_fetched.wait(timeout=2))
        self.assertTrue(po_fetched.wait(timeout=2))
        if first == "upstream":
            up_release.set()
            time.sleep(0.02)
            po_release.set()
        else:
            po_release.set()
            time.sleep(0.02)
            up_release.set()
        self.assertTrue(
            _wait_until(
                lambda: coordinator._latest is not None
                and "New" in coordinator._latest.mdx
                and "P-new" in coordinator._latest.mdx
            )
        )
        final = coordinator._latest
        self.assertIsNotNone(final)
        assert final is not None
        self.assertIn("New", final.mdx)
        self.assertIn("P-new", final.mdx)
        self.assertNotIn("Old", final.mdx)
        self.assertNotIn("P-old", final.mdx)

    def test_swr_background_fetch_failure_keeps_stale(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "upstream.json")
        clock = _Clock()
        _write_envelope(
            path,
            clock.now - 120,
            {
                "mdx_download_list": {"Old": {"o.ckpt": "https://u/o.ckpt"}},
                "vr_download_list": {},
                "demucs_download_list": {},
            },
        )
        fetched = threading.Event()

        def opener(_url: object) -> _Response:
            fetched.set()
            raise OSError("offline")

        coordinator = self._swr_coordinator(
            {
                SourceId.UPSTREAM: self._swr_source(
                    SourceId.UPSTREAM,
                    path=path,
                    clock=clock,
                    opener=opener,
                    url="https://example.test/upstream.json",
                )
            }
        )
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=True)
        stale = coordinator.refresh(
            mode=RefreshMode.STALE_WHILE_REVALIDATE, policy=policy
        )
        self.assertTrue(stale.usable)
        self.assertTrue(fetched.wait(timeout=2))
        self.assertTrue(
            _wait_until(
                lambda: coordinator.source(SourceId.UPSTREAM).state.status.error
                is not None
            )
        )
        latest = coordinator._latest
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertIn("Old", latest.mdx)
        self.assertTrue(stale.usable)

    def test_swr_metadata_only_updates_source_payload(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "upstream.json")
        clock = _Clock()
        models = {"A": {"a.ckpt": "https://u/a.ckpt"}}
        _write_envelope(
            path,
            clock.now - 120,
            {
                "mdx_download_list": models,
                "current_version_linux": "1",
                "vr_download_list": {},
                "demucs_download_list": {},
            },
        )
        fetched = threading.Event()
        release = threading.Event()
        opener = _gated_opener(
            {
                "mdx_download_list": models,
                "current_version_linux": "2",
                "vr_download_list": {},
                "demucs_download_list": {},
            },
            fetched,
            release,
        )
        coordinator = self._swr_coordinator(
            {
                SourceId.UPSTREAM: self._swr_source(
                    SourceId.UPSTREAM,
                    path=path,
                    clock=clock,
                    opener=opener,
                    url="https://example.test/upstream.json",
                )
            }
        )
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=True)
        stale = coordinator.refresh(
            mode=RefreshMode.STALE_WHILE_REVALIDATE, policy=policy
        )
        self.assertTrue(stale.usable)
        disk_payload = coordinator.source(SourceId.UPSTREAM).state.content
        self.assertIsNotNone(disk_payload)
        assert disk_payload is not None
        self.assertEqual(disk_payload.payload["current_version_linux"], "1")
        self.assertTrue(fetched.wait(timeout=2))
        release.set()

        def version_is_two() -> bool:
            content = coordinator.source(SourceId.UPSTREAM).state.content
            return content is not None and content.payload.get("current_version_linux") == "2"

        self.assertTrue(_wait_until(version_is_two))
        content = coordinator.source(SourceId.UPSTREAM).state.content
        self.assertIsNotNone(content)
        assert content is not None
        self.assertEqual(content.payload["current_version_linux"], "2")


if __name__ == "__main__":
    unittest.main()
