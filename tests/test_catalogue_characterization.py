"""Characterization tests for the revisioned catalogue coordinator."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from core.access_policy import AccessPolicy
from core.catalogue_coordinator import CatalogueCoordinator, flatten_upstream_lists
from core.catalogue_types import (
    PRIOR_EXTRAS_SCNET_BANDIT_WINNERS,
    RefreshMode,
    SourceId,
)
from core.remote_catalog_cache import RemoteJsonSource


class FingerprintCharacterizationTests(unittest.TestCase):
    def test_same_labels_changed_urls_are_not_cached(self) -> None:
        from core import catalog_sources

        catalog_sources.invalidate_catalogue_merge()
        with (
            mock.patch.object(
                catalog_sources, "_supplemental_sources", return_value=({}, {}, {}, {})
            ),
            mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}),
        ):
            first = catalog_sources.merged_catalogues(
                vr={}, mdx={"Shared": {"a.ckpt": "https://one/a.ckpt"}}, demucs={}
            )
            second = catalog_sources.merged_catalogues(
                vr={}, mdx={"Shared": {"a.ckpt": "https://two/a.ckpt"}}, demucs={}
            )
        self.assertEqual(first.mdx["Shared"]["a.ckpt"], "https://one/a.ckpt")
        self.assertEqual(second.mdx["Shared"]["a.ckpt"], "https://two/a.ckpt")
        self.assertIsNot(first, second)


class UpstreamScnetBanditTests(unittest.TestCase):
    def test_flatten_includes_scnet_and_bandit_before_supplements(self) -> None:
        payload = {
            "mdx_download_list": {"MDX Only": {"m.ckpt": "https://u/m.ckpt"}},
            "scnet_download_list": {
                PRIOR_EXTRAS_SCNET_BANDIT_WINNERS[0]: {
                    "upstream.ckpt": "https://upstream/huge.ckpt"
                }
            },
        }
        _vr, mdx, _demucs = flatten_upstream_lists(payload)
        self.assertEqual(
            mdx[PRIOR_EXTRAS_SCNET_BANDIT_WINNERS[0]]["upstream.ckpt"],
            "https://upstream/huge.ckpt",
        )

    def test_rebuild_catalogues_keeps_upstream_scnet_over_extras(self) -> None:
        from core.downloads import DownloadManager

        manager = DownloadManager.__new__(DownloadManager)
        manager.online_data = {
            "vr_download_list": {},
            "mdx_download_list": {},
            "scnet_download_list": {
                PRIOR_EXTRAS_SCNET_BANDIT_WINNERS[0]: {
                    "upstream.ckpt": "https://upstream/huge.ckpt"
                }
            },
            "demucs_download_list": {},
        }
        DownloadManager._rebuild_catalogues(manager)
        self.assertEqual(
            manager.mdx_download_list[PRIOR_EXTRAS_SCNET_BANDIT_WINNERS[0]]["upstream.ckpt"],
            "https://upstream/huge.ckpt",
        )


class CompactConfigEvidenceTests(unittest.TestCase):
    def _snapshot(self, payload: dict):
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: RemoteJsonSource(
                    source_id=SourceId.UPSTREAM, local_loader=lambda: payload
                ),
                SourceId.POLITREES: RemoteJsonSource(
                    source_id=SourceId.POLITREES, enabled=lambda: False
                ),
                SourceId.EXTRAS: RemoteJsonSource(source_id=SourceId.EXTRAS, enabled=lambda: False),
                SourceId.MVSEPLESS: RemoteJsonSource(
                    source_id=SourceId.MVSEPLESS, enabled=lambda: False
                ),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator.snapshot(
            mode=RefreshMode.OFFLINE,
            policy=AccessPolicy(
                allow_network=False,
                allow_metadata_writes=False,
            ),
        )

    def test_compact_scalar_and_exact_other_network_url_are_evidence_only(self) -> None:
        snapshot = self._snapshot(
            {
                "roformer_download_list": {
                    "Roformer Model: Compact": {"compact.ckpt": "compact_config.yml"}
                },
                "other_network_list": {
                    "Roformer Model: Compact": {
                        "compact.ckpt": "https://weights.test/compact.ckpt",
                        "compact_config.yml": "https://configs.test/compact_config.yml",
                    },
                    "Evidence-only row": {
                        "hidden.ckpt": "https://weights.test/hidden.ckpt",
                        "hidden.yaml": "https://configs.test/hidden.yaml",
                    },
                },
            }
        )

        self.assertEqual(
            snapshot.checkpoint_yaml_index["compact.ckpt"],
            "compact_config.yml",
        )
        self.assertEqual(
            snapshot.checkpoint_yaml_url_index[("compact.ckpt", "compact_config.yml")],
            "https://configs.test/compact_config.yml",
        )
        self.assertEqual(set(snapshot.mdx), {"Roformer Model: Compact"})
        self.assertNotIn("Evidence-only row", snapshot.mdx)

    def test_non_basename_scalar_and_mismatched_url_pair_do_not_join(self) -> None:
        snapshot = self._snapshot(
            {
                "roformer_download_list": {
                    "Roformer Model: Nested": {"nested.ckpt": "configs/nested.yaml"},
                    "Roformer Model: Mismatch": {"mismatch.ckpt": "mismatch.yaml"},
                    "Roformer Model: Non-URL evidence": {"not_url.ckpt": "not_url.yaml"},
                },
                "other_network_list": {
                    "Roformer Model: Mismatch": {
                        "different.ckpt": "https://weights.test/different.ckpt",
                        "mismatch.yaml": "https://configs.test/mismatch.yaml",
                    },
                    "Roformer Model: Non-URL evidence": {
                        "not_url.ckpt": "not-a-url",
                        "not_url.yaml": "https://configs.test/not_url.yaml",
                    },
                },
            }
        )

        self.assertNotIn("nested.ckpt", snapshot.checkpoint_yaml_index)
        self.assertEqual(
            snapshot.checkpoint_yaml_index["mismatch.ckpt"],
            "mismatch.yaml",
        )
        self.assertNotIn(
            ("mismatch.ckpt", "mismatch.yaml"),
            snapshot.checkpoint_yaml_url_index,
        )
        self.assertNotIn(
            ("not_url.ckpt", "not_url.yaml"),
            snapshot.checkpoint_yaml_url_index,
        )

    def test_explicit_yaml_mapping_keeps_legacy_last_key_behavior(self) -> None:
        snapshot = self._snapshot(
            {
                "mdx23c_download_list": {
                    "Legacy multi-file row": {
                        "first.ckpt": "https://weights.test/first.ckpt",
                        "first.yaml": "https://configs.test/first.yaml",
                        "last.ckpt": "https://weights.test/last.ckpt",
                        "last.yaml": "https://configs.test/last.yaml",
                    }
                }
            }
        )

        self.assertNotIn("first.ckpt", snapshot.checkpoint_yaml_index)
        self.assertEqual(snapshot.checkpoint_yaml_index["last.ckpt"], "last.yaml")


class PolitreesFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        import core.politrees_catalog as pc

        self.pc = pc
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = os.path.join(self._tmp.name, "politrees_model_links.json")
        self._patch = mock.patch.object(pc, "_politrees_cache_path", return_value=self.cache_path)
        self._patch.start()
        self._env = mock.patch.dict(
            os.environ, {"UVR_DISABLE_POLITREES": "0", "UVR_DISABLE_MVSEPLESS": "1"}
        )
        self._env.start()
        pc.clear_politrees_cache()

    def tearDown(self) -> None:
        self._env.stop()
        self._patch.stop()
        self.pc.clear_politrees_cache()
        self._tmp.cleanup()

    def test_offline_expired_disk_does_not_suppress_later_swr(self) -> None:
        fetched_at = time.time() - (self.pc._POLITREES_CACHE_TTL_SECONDS + 60)
        with open(self.cache_path, "w", encoding="utf-8") as handle:
            json.dump(
                {"fetched_at": fetched_at, "data": {"mdx_download_list": {"M": "m.onnx"}}},
                handle,
            )
        self.pc.load_politrees_links(allow_network=False)
        with mock.patch.object(self.pc, "_start_background_refresh") as refresh:
            self.pc.load_politrees_links(allow_network=True)
        refresh.assert_called_once()


class UnsupportedPolicyTests(unittest.TestCase):
    def test_unsupported_mvsepless_honors_allow_network(self) -> None:
        from core.mvsepless_catalog import unsupported_mvsepless_downloads

        with mock.patch(
            "core.mvsepless_catalog.load_converted_mvsepless", return_value=None
        ) as load:
            unsupported_mvsepless_downloads(allow_network=False)
        self.assertEqual(load.call_args.kwargs.get("allow_network"), False)

    def test_unsupported_reason_for_label_honors_allow_network(self) -> None:
        from core.mvsepless_catalog import unsupported_reason_for_label

        with mock.patch(
            "core.mvsepless_catalog.load_converted_mvsepless", return_value=None
        ) as load:
            unsupported_reason_for_label("nope", allow_network=False)
        self.assertEqual(load.call_args.kwargs.get("allow_network"), False)


class InventoryVsAliasTests(unittest.TestCase):
    def test_custom_file_stays_in_default_list_contract(self) -> None:
        from core.model_identity import iter_model_records

        class _Repo:
            def list_vr_models(self) -> list[str]:
                return ["custom_unrecognized"]

            def list_mdx_models(self) -> list[str]:
                return []

            def list_demucs_models(self) -> list[str]:
                return []

            def vr_catalogue_display_index(self, *, allow_network: bool = False) -> dict:
                return {}

            def mdx_catalogue_display_index(self, *, allow_network: bool = False) -> dict:
                return {}

            def demucs_catalogue_display_index(self, *, allow_network: bool = False) -> dict:
                return {}

        with mock.patch("core.apollo.list_apollo_models", return_value=[]):
            records = list(iter_model_records(_Repo()))
        installed = [row for row in records if row.installed]
        self.assertTrue(any(row.basename == "custom_unrecognized" for row in installed))


class CoordinatorConcurrencyTests(unittest.TestCase):
    def test_concurrent_ensure_and_refresh_publish_complete_snapshots(self) -> None:
        payload = {"mdx_download_list": {"A": {"a.ckpt": "https://x/a.ckpt"}}}
        source = RemoteJsonSource(
            source_id=SourceId.UPSTREAM,
            local_loader=lambda: payload,
        )
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: source,
                SourceId.POLITREES: RemoteJsonSource(
                    source_id=SourceId.POLITREES, enabled=lambda: False
                ),
                SourceId.EXTRAS: RemoteJsonSource(source_id=SourceId.EXTRAS, enabled=lambda: False),
                SourceId.MVSEPLESS: RemoteJsonSource(
                    source_id=SourceId.MVSEPLESS, enabled=lambda: False
                ),
            }
        )
        seen: list[int] = []
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                for _ in range(8):
                    snap = coordinator.ensure(
                        allow_network=False,
                        policy=AccessPolicy(allow_network=False, allow_metadata_writes=False),
                    )
                    seen.append(len(snap.mdx))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        coordinator.close()
        self.assertFalse(errors)
        self.assertTrue(seen)
        self.assertTrue(all(count in {0, 1} for count in seen))
        self.assertIn(1, seen)


class OfflinePolicyTests(unittest.TestCase):
    def test_fully_offline_source_does_not_touch_network_or_disk(self) -> None:
        opener = mock.Mock(side_effect=AssertionError("opener"))
        source = RemoteJsonSource(
            source_id=SourceId.POLITREES,
            url="https://example.test/catalog.json",
            cache_filename="politrees_model_links.json",
            cache_path="/tmp/does-not-exist-uvr-catalogue.json",
            opener=opener,
        )
        policy = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        with (
            mock.patch("os.makedirs", side_effect=AssertionError("mkdir")),
            mock.patch("os.replace", side_effect=AssertionError("replace")),
            mock.patch("shutil.move", side_effect=AssertionError("move")),
            mock.patch("shutil.copy2", side_effect=AssertionError("copy")),
            mock.patch("threading.Thread.start", side_effect=AssertionError("thread")),
        ):
            state = source.load(mode=RefreshMode.STALE_WHILE_REVALIDATE, policy=policy)
        opener.assert_not_called()
        self.assertIsNone(state.content)

    def test_write_denied_refresh_does_not_mkdir(self) -> None:
        from tests.test_remote_catalog_cache import _Response

        source = RemoteJsonSource(
            source_id=SourceId.UPSTREAM,
            url="https://example.test/catalog.json",
            cache_filename="upstream.json",
            cache_path="/tmp/uvr-catalogue-write-denied.json",
            opener=lambda _url: _Response({"mdx_download_list": {"A": {"a.ckpt": "u"}}}),
        )
        with (
            mock.patch("os.makedirs", side_effect=AssertionError("mkdir")),
            mock.patch("os.replace", side_effect=AssertionError("replace")),
        ):
            state = source.load(
                mode=RefreshMode.FORCE,
                policy=AccessPolicy(allow_network=True, allow_metadata_writes=False),
            )
        self.assertIsNotNone(state.content)
        self.assertFalse(os.path.exists("/tmp/uvr-catalogue-write-denied.json"))


class CoordinatorIsolationTests(unittest.TestCase):
    def test_close_does_not_leak_subscribers_into_next_instance(self) -> None:
        first = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: RemoteJsonSource(
                    source_id=SourceId.UPSTREAM,
                    local_loader=lambda: {"mdx_download_list": {}},
                ),
                SourceId.POLITREES: RemoteJsonSource(
                    source_id=SourceId.POLITREES, enabled=lambda: False
                ),
                SourceId.EXTRAS: RemoteJsonSource(source_id=SourceId.EXTRAS, enabled=lambda: False),
                SourceId.MVSEPLESS: RemoteJsonSource(
                    source_id=SourceId.MVSEPLESS, enabled=lambda: False
                ),
            }
        )
        seen: list = []
        first.subscribe_delta(lambda delta: seen.append(delta))
        first.close()
        second = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: RemoteJsonSource(
                    source_id=SourceId.UPSTREAM,
                    local_loader=lambda: {
                        "mdx_download_list": {"N": {"n.ckpt": "https://u/n.ckpt"}}
                    },
                ),
                SourceId.POLITREES: RemoteJsonSource(
                    source_id=SourceId.POLITREES, enabled=lambda: False
                ),
                SourceId.EXTRAS: RemoteJsonSource(source_id=SourceId.EXTRAS, enabled=lambda: False),
                SourceId.MVSEPLESS: RemoteJsonSource(
                    source_id=SourceId.MVSEPLESS, enabled=lambda: False
                ),
            }
        )
        second.snapshot(
            mode=RefreshMode.OFFLINE,
            policy=AccessPolicy(allow_network=False, allow_metadata_writes=False),
        )
        second.close()
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
