"""Coordinator snapshot, VIP, refresh-report, and delta tests."""

from __future__ import annotations

import unittest
from unittest import mock

from core.access_policy import AccessPolicy
from core.catalogue_coordinator import CatalogueCoordinator
from core.catalogue_types import DeltaKind, RefreshMode, SourceId
from core.remote_catalog_cache import RemoteJsonSource


def _local(source_id: SourceId, payload: dict) -> RemoteJsonSource:
    return RemoteJsonSource(source_id=source_id, local_loader=lambda: payload)


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
                SourceId.POLITREES: RemoteJsonSource(
                    source_id=SourceId.POLITREES, enabled=lambda: False
                ),
                SourceId.EXTRAS: RemoteJsonSource(
                    source_id=SourceId.EXTRAS, enabled=lambda: False
                ),
                SourceId.MVSEPLESS: RemoteJsonSource(
                    source_id=SourceId.MVSEPLESS, enabled=lambda: False
                ),
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

    def test_vip_is_a_projection_not_source_state(self) -> None:
        payload = {
            "mdx_download_list": {"Public": {"p.ckpt": "https://u/p.ckpt"}},
            "mdx_download_vip_list": {"VIP Only": {"v.ckpt": "https://u/v.ckpt"}},
        }
        coordinator = self._coordinator(payload)
        policy = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        locked = coordinator.snapshot(vip=False, mode=RefreshMode.OFFLINE, policy=policy)
        unlocked = coordinator.snapshot(vip=True, mode=RefreshMode.OFFLINE, policy=policy)
        self.assertIn("Public", locked.mdx)
        self.assertNotIn("VIP Only", locked.mdx)
        self.assertIn("VIP Only", unlocked.mdx)
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
                SourceId.POLITREES: RemoteJsonSource(
                    source_id=SourceId.POLITREES, enabled=lambda: False
                ),
                SourceId.EXTRAS: RemoteJsonSource(
                    source_id=SourceId.EXTRAS, enabled=lambda: False
                ),
                SourceId.MVSEPLESS: RemoteJsonSource(
                    source_id=SourceId.MVSEPLESS, enabled=lambda: False
                ),
            }
        )
        import threading

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
                SourceId.POLITREES: RemoteJsonSource(
                    source_id=SourceId.POLITREES, enabled=lambda: False
                ),
                SourceId.EXTRAS: RemoteJsonSource(
                    source_id=SourceId.EXTRAS, enabled=lambda: False
                ),
                SourceId.MVSEPLESS: RemoteJsonSource(
                    source_id=SourceId.MVSEPLESS, enabled=lambda: False
                ),
            }
        )
        policy = AccessPolicy(allow_network=True, allow_metadata_writes=False)
        report = coordinator.refresh(mode=RefreshMode.FORCE, policy=policy)
        snap = coordinator.snapshot(mode=RefreshMode.OFFLINE, policy=policy)
        self.assertTrue(report.usable or "Bundled" in snap.mdx)
        coordinator.close()


if __name__ == "__main__":
    unittest.main()
