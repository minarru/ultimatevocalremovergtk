import json
import os
import sys
import unittest
import urllib.error
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from core.catalogue_types import SourceId  # noqa: E402
import generate_models_catalogue as cli  # noqa: E402
from catalogue import collect as catalogue  # noqa: E402
from catalogue import render  # noqa: E402


class UiNoteTests(unittest.TestCase):
    def test_vocals_other_note_only_for_two_stem_models(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="MelBand Roformer Kim | Inst v1 by Unwa",
            weight_file="model.ckpt",
            instruments=["other", "vocals"],
            stem_count=2,
        )
        self.assertIn("Vocals / Instrumental", catalogue._ui_note(entry))

    def test_four_stem_vocals_other_uses_subset_row_note(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="4-stems SCNet Large",
            weight_file="model.ckpt",
            instruments=["Drums", "Bass", "Other", "Vocals"],
            stem_count=4,
            name_intent="multi_stem",
        )
        self.assertEqual(catalogue._ui_note(entry), "UI: per-stem subset or focus row")

    def test_special_fx_best_result_and_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="VR Architecture",
            catalogue_label="UVR-DeNoise by FoxJoy",
            weight_file="UVR-DeNoise.pth",
            primary_stem="noise",
            name_intent="special_fx",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertIn("Noise", entry.best_result)
        self.assertTrue(entry.backend_focus.startswith("special_fx_primary:"))
        self.assertIn("complement", entry.ui_export_note)

    def test_karaoke_2_gets_karaoke_backend_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="MDX-Net ONNX",
            catalogue_label="MDX-Net Model: UVR-MDX-NET Karaoke 2",
            weight_file="UVR_MDXNET_KARA_2.onnx",
            primary_stem="Instrumental",
            name_intent="karaoke",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertTrue(entry.is_karaoke)
        self.assertEqual(entry.backend_focus, "karaoke_instrumental_primary")

    def test_specialty_stem_flags_old_vocals_mismatch(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="BandSplit Roformer | Male-Female by aufr33",
            weight_file="model.ckpt",
            instruments=["male", "female"],
            primary_stem="male",
            name_intent="vocals",
            backend_focus="two_stem",
            metadata_source="remote_yaml:test.yaml",
        )
        flags = catalogue._flag_mismatches(entry)
        self.assertTrue(any("specialty 2-stem" in flag for flag in flags))


class SourceForTests(unittest.TestCase):
    def test_mdx23c_download_list_counts_as_trvlvr(self) -> None:
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", None, trvlvr), "TRvlvr")

    def test_mdx23c_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_mdx23c_in_both_is_combined(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(
            catalogue._source_for("Some Model", politrees, trvlvr), "TRvlvr+Politrees"
        )

    def test_unattributed_label_is_unknown_not_trvlvr(self) -> None:
        """No membership anywhere is 'not proven', not positive provenance."""
        self.assertEqual(catalogue._source_for("Unknown Model", None, {}), "unknown")

    def test_failed_upstream_payload_does_not_attribute_everything_to_trvlvr(self) -> None:
        """A source that failed to load yields {}, which must not read as TRvlvr.

        _source_payload returns {} when a source has no content, so under a cold
        cache every label would otherwise be stamped with positive TRvlvr
        provenance on the strength of a failed membership check.
        """
        politrees = {"mdx23c_download_list": {"In Politrees": "a.ckpt"}}
        self.assertEqual(catalogue._source_for("In Politrees", politrees, {}), "Politrees")
        self.assertEqual(catalogue._source_for("In Nothing", politrees, {}), "unknown")

    def test_mdx23_download_list_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_scnet_in_upstream_counts_as_trvlvr(self) -> None:
        trvlvr = {"scnet_download_list": {"SCnet: Huge": {"huge.ckpt": "https://u/huge.ckpt"}}}
        politrees = {"scnet_download_list": {"SCnet: Huge": {"huge.ckpt": "https://p/huge.ckpt"}}}
        self.assertEqual(
            catalogue._source_for("SCnet: Huge", politrees, trvlvr), "TRvlvr+Politrees"
        )

    def test_extras_only_is_extras(self) -> None:
        extras = {
            "roformer_download_list": {
                "Roformer Model: BandSplit Roformer | HyperACE": {
                    "bs_hyperace.ckpt": "https://u/bs_hyperace.ckpt"
                }
            }
        }
        self.assertEqual(
            catalogue._source_for("Roformer Model: BandSplit Roformer | HyperACE", extras=extras),
            "extras",
        )

    def test_apollo_in_extras_is_extras(self) -> None:
        extras = {
            "apollo_download_list": {
                "Apollo Model: EDM Restoration by essid": {
                    "apollo_edm_by_essid.ckpt": "https://u/apollo.ckpt"
                }
            }
        }
        self.assertEqual(
            catalogue._source_for("Apollo Model: EDM Restoration by essid", extras=extras),
            "extras",
        )

    def test_mvsepless_only_is_mvsepless(self) -> None:
        mvsepless = {
            "mdx_download_list": {
                "MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}
            }
        }
        self.assertEqual(
            catalogue._source_for("MelBand Roformer Karaoke", mvsepless=mvsepless),
            "mvsepless",
        )

    def test_upstream_and_extras_combine_in_merge_order(self) -> None:
        trvlvr = {"mdx_download_list": {"Shared": "shared.onnx"}}
        extras = {"mdx_download_list": {"Shared": {"shared.onnx": "https://u/shared.onnx"}}}
        self.assertEqual(
            catalogue._source_for("Shared", None, trvlvr, extras=extras),
            "TRvlvr+extras",
        )


def _local(source_id: SourceId, payload: dict):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, local_loader=lambda: payload)


def _disabled(source_id: SourceId):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, enabled=lambda: False)


class CollectEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator
        from core.catalogue_types import SourceId

        extras = {
            "roformer_download_list": {
                "Roformer Model: BandSplit Roformer | HyperACE": {
                    "bs_hyperace.ckpt": "https://u/bs_hyperace.ckpt"
                }
            },
            "apollo_download_list": {
                "Apollo Model: EDM Restoration by essid": {
                    "apollo_edm_by_essid.ckpt": "https://u/apollo.ckpt"
                }
            },
        }
        mvsepless = {
            "mdx_download_list": {
                "MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}
            }
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(
                    SourceId.UPSTREAM,
                    {
                        "vr_download_list": {},
                        "mdx_download_list": {},
                        "demucs_download_list": {},
                    },
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _local(SourceId.EXTRAS, extras),
                SourceId.MVSEPLESS: _local(SourceId.MVSEPLESS, mvsepless),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def test_collect_entries_uses_coordinator_sources(self) -> None:
        ctx = catalogue.CatalogueContext()
        _snapshot, entries = catalogue.collect_entries(
            ctx, allow_network=False, coordinator=self._coordinator()
        )
        by_label = {entry.catalogue_label: entry for entry in entries}
        hyperace = by_label["Roformer Model: BandSplit Roformer | HyperACE"]
        self.assertEqual(hyperace.source, "extras")
        self.assertEqual(hyperace.family, "Roformer")
        apollo = by_label["Apollo Model: EDM Restoration by essid"]
        self.assertEqual(apollo.source, "extras")
        self.assertEqual(apollo.family, "Apollo")
        karaoke = by_label["MelBand Roformer Karaoke"]
        self.assertEqual(karaoke.source, "mvsepless")


class OfflinePolicyTests(unittest.TestCase):
    """--offline must be cache-only: no fetch, no writes into model config storage."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-offline-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.calls: list = []

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator

        # An MDX-C entry with a remote yaml: the path that reaches _load_yaml_meta.
        upstream = {
            "vr_download_list": {},
            "mdx_download_list": {
                "MDX23C Model: Test": {
                    "model_test.ckpt": "https://example.invalid/model_test.ckpt",
                    "model_test.yaml": "https://example.invalid/model_test.yaml",
                }
            },
            "demucs_download_list": {},
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(SourceId.UPSTREAM, upstream),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def _patches(self):
        """Record every network entry point instead of raising.

        _fetch_cached swallows URLError/OSError, so a raising stub could be
        silently absorbed and the test would pass while the socket was opened.
        """
        from unittest import mock

        def record_urlopen(request: Any, *args: Any, **kwargs: Any):
            import urllib.error

            url = getattr(request, "full_url", request)
            self.calls.append(f"_urlopen({url})")
            # A URLError is what a real offline machine raises, and _fetch_cached
            # handles it; the recorded call list is what the assertions read.
            raise urllib.error.URLError("blocked by test")

        def record_fetch_config(name: Any, url: Any, *args: Any, **kwargs: Any) -> bool:
            self.calls.append(f"fetch_mdx_config_url({name}, {url})")
            return False

        return [
            mock.patch("core.mdx_config_fetch._urlopen", record_urlopen),
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", record_fetch_config),
            mock.patch.object(catalogue, "_scan_weight_hashes", lambda *a: {}),
            mock.patch.object(catalogue, "POLITREES_CACHE_DIR", os.path.join(self.tmp, "pt")),
            mock.patch.object(catalogue, "COMMUNITY_CACHE_DIR", os.path.join(self.tmp, "cm")),
            mock.patch.object(catalogue, "YAML_CACHE_DIR", os.path.join(self.tmp, "yaml")),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(self.tmp, "ref.tsv")),
            mock.patch.object(cli, "OUTPUT_PATH", os.path.join(self.tmp, "out.md")),
        ]

    def test_build_catalogue_context_offline_makes_no_network_calls(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            catalogue._build_catalogue_context(allow_network=False)
        self.assertEqual(self.calls, [])

    def test_offline_cache_miss_does_not_create_the_cache_dir(self) -> None:
        """Offline is read-only: a miss must not leave an empty cache dir behind."""
        cache_dir = os.path.join(self.tmp, "cold")
        path = catalogue._fetch_cached(
            "https://example.invalid/x.json", cache_dir, "x.json", allow_network=False
        )
        self.assertIsNone(path)
        self.assertFalse(os.path.exists(cache_dir), "offline miss created a cache dir")

    def test_load_yaml_meta_offline_does_not_fetch_or_write_config(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            result = catalogue._load_yaml_meta(
                "model_test.yaml",
                "https://example.invalid/model_test.yaml",
                allow_network=False,
            )
        self.assertEqual(self.calls, [])
        # Falls back to the name heuristic rather than fetching.
        self.assertIsInstance(result, tuple)

    def test_main_offline_makes_no_network_calls(self) -> None:
        import contextlib
        from unittest import mock

        coordinator = self._coordinator()
        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            real = catalogue._snapshot_and_payloads
            seen = {}

            def spy(*, allow_network: bool, coordinator: Any = None, **kwargs: Any):
                seen["allow_network"] = allow_network
                return real(allow_network=allow_network, coordinator=self._co, **kwargs)

            self._co = coordinator
            stack.enter_context(mock.patch.object(catalogue, "_snapshot_and_payloads", spy))
            rc = cli.main(["--offline"])

        self.assertEqual(rc, 0)
        self.assertIs(seen["allow_network"], False)
        self.assertEqual(self.calls, [])

    def test_online_still_fetches(self) -> None:
        """The offline guard must not disable networking for normal runs."""
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            catalogue._build_catalogue_context(allow_network=True)
        self.assertTrue(self.calls, "online mode should still attempt fetches")


class DemucsFinalizationTests(unittest.TestCase):
    """Demucs family facts must land before the single finalization pass.

    The overlay used to run *after* _finalize_entry, so ui_export_note and
    flags were derived from an entry with no instruments and no stem count.
    """

    class _Snapshot:
        def __init__(self, demucs: dict) -> None:
            self.vr: dict = {}
            self.mdx: dict = {}
            self.demucs = demucs
            self.apollo: dict = {}
            self.meta: dict = {}
            self.unsupported: dict = {}

    def _entry(self, label: str, weight: str):
        snapshot = self._Snapshot({label: weight})
        entries = catalogue._entries_from_snapshot(
            snapshot, ({}, {}, {}, {}), catalogue.CatalogueContext(),
            policy=catalogue.OFFLINE_FETCH_POLICY
        )
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_six_stem_demucs_gets_its_export_note(self) -> None:
        entry = self._entry("Demucs v4: htdemucs_6s", "htdemucs_6s.th")
        self.assertEqual(entry.stem_count, 6)
        self.assertEqual(entry.ui_export_note, "UI: per-stem subset or focus row")

    def test_four_stem_demucs_gets_its_export_note(self) -> None:
        entry = self._entry("Demucs v4: htdemucs", "htdemucs.th")
        self.assertEqual(entry.stem_count, 4)
        self.assertEqual(entry.ui_export_note, "UI: per-stem subset or focus row")

    def test_two_stem_uvr_demucs_is_not_labelled_multi_stem(self) -> None:
        """The UVR Demucs model emits vocals+instrumental, not a multi-stem set."""
        entry = self._entry("Demucs v3: UVR Model", "UVR_Demucs_Model_1.th")
        self.assertEqual(entry.stem_count, 2)
        self.assertEqual(entry.backend_focus, "two_stem")

    def test_family_specific_best_result_prose_is_preserved(self) -> None:
        self.assertEqual(self._entry("Demucs v4: htdemucs_6s", "a.th").best_result, "6-stem Demucs")
        self.assertEqual(self._entry("Demucs v4: htdemucs", "b.th").best_result, "4-stem Demucs")
        self.assertEqual(
            self._entry("Demucs v3: UVR Model", "c.th").best_result,
            "2-stem: instrumental + vocals (user picks focus)",
        )

    def test_metadata_source_records_the_heuristic(self) -> None:
        self.assertEqual(
            self._entry("Demucs v4: htdemucs", "b.th").metadata_source, "demucs_heuristic"
        )


class CacheIdentityTests(unittest.TestCase):
    """Ephemeral downloads: keyed by URL, TTL'd, and out of the docs tree."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-cache-id-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fetched: list = []

    def _opener(self, body: bytes = b'{"ok": 1}'):
        from unittest import mock

        def record(request: Any, *args: Any, **kwargs: Any):
            url = getattr(request, "full_url", request)
            self.fetched.append(url)

            class _R:
                def read(self) -> bytes:
                    return body

                def __enter__(self) -> "_R":
                    return self

                def __exit__(self, *exc: Any) -> bool:
                    return False

            return _R()

        return mock.patch("core.mdx_config_fetch._urlopen", record)

    def test_caches_live_under_cache_dir_not_the_docs_tree(self) -> None:
        from core import paths

        for cache_dir in (
            catalogue.YAML_CACHE_DIR,
            catalogue.POLITREES_CACHE_DIR,
            catalogue.COMMUNITY_CACHE_DIR,
        ):
            self.assertTrue(
                cache_dir.startswith(paths.CACHE_DIR),
                f"{cache_dir} is not under CACHE_DIR",
            )
            self.assertNotIn("docs", os.path.relpath(cache_dir, paths.CACHE_DIR))

    def test_same_basename_from_different_urls_does_not_alias(self) -> None:
        """Two models can both ship a 'config.yaml'."""
        with self._opener(b"first"):
            a = catalogue._fetch_cached("https://a.invalid/x/config.yaml", self.tmp, "config.yaml")
        with self._opener(b"second"):
            b = catalogue._fetch_cached("https://b.invalid/y/config.yaml", self.tmp, "config.yaml")
        self.assertNotEqual(a, b)
        assert a is not None and b is not None
        self.assertEqual(open(a, "rb").read(), b"first")
        self.assertEqual(open(b, "rb").read(), b"second")

    def test_a_fresh_cache_entry_is_not_refetched(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            catalogue._fetch_cached(url, self.tmp, "data.json")
            catalogue._fetch_cached(url, self.tmp, "data.json")
        self.assertEqual(len(self.fetched), 1)

    def test_a_stale_cache_entry_is_refetched(self) -> None:
        """A normal online run must not reuse an arbitrarily old supplement."""
        url = "https://a.invalid/data.json"
        with self._opener():
            path = catalogue._fetch_cached(url, self.tmp, "data.json")
            assert path
            os.utime(path, (0, 0))  # epoch: far older than any TTL
            catalogue._fetch_cached(url, self.tmp, "data.json")
        self.assertEqual(len(self.fetched), 2)

    def test_stale_entry_is_still_served_when_offline(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            path = catalogue._fetch_cached(url, self.tmp, "data.json")
            assert path
            os.utime(path, (0, 0))
        with self._opener():
            served = catalogue._fetch_cached(url, self.tmp, "data.json", allow_network=False)
        self.assertEqual(served, path)
        self.assertEqual(len(self.fetched), 1)

    def test_refresh_refetches_even_a_fresh_entry(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            catalogue._fetch_cached(url, self.tmp, "data.json")
            catalogue._fetch_cached(url, self.tmp, "data.json", refresh=True)
        self.assertEqual(len(self.fetched), 2)

    def test_refresh_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(cli._parse_args(["--refresh"]).refresh)
        self.assertFalse(cli._parse_args([]).refresh)


class CoordinatorRefreshTests(unittest.TestCase):
    """--refresh must FORCE-reload membership, not only yaml / models.txt."""

    def _coordinator(self) -> Any:
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        empty = MagicMock()
        empty.state.content = None
        coordinator.source.return_value = empty
        snapshot = MagicMock(name="snapshot")
        coordinator.ensure.return_value = snapshot
        coordinator.snapshot.return_value = snapshot
        return coordinator

    def test_refresh_force_loads_coordinator_sources(self) -> None:
        from core.catalogue_types import RefreshMode

        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(
            allow_network=True, refresh=True, coordinator=coordinator
        )
        coordinator.snapshot.assert_called_once_with(
            vip=False, mode=RefreshMode.FORCE
        )
        coordinator.ensure.assert_not_called()
        coordinator.refresh.assert_not_called()

    def test_default_snapshot_does_not_force_refresh(self) -> None:
        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(
            allow_network=True, refresh=False, coordinator=coordinator
        )
        coordinator.refresh.assert_not_called()
        coordinator.snapshot.assert_not_called()
        coordinator.ensure.assert_called_once_with(vip=False, allow_network=True)

    def test_offline_never_force_refreshes_even_when_asked(self) -> None:
        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(
            allow_network=False, refresh=True, coordinator=coordinator
        )
        coordinator.refresh.assert_not_called()
        coordinator.snapshot.assert_not_called()
        coordinator.ensure.assert_called_once_with(vip=False, allow_network=False)

    def test_collect_entries_forwards_refresh(self) -> None:
        from unittest.mock import MagicMock, patch

        seen: dict = {}

        def spy(
            *,
            allow_network: bool,
            coordinator: Any = None,
            refresh: bool = False,
        ) -> Any:
            seen["refresh"] = refresh
            seen["allow_network"] = allow_network
            return MagicMock(), ({}, {}, {}, {})

        with patch.object(catalogue, "_snapshot_and_payloads", spy), patch.object(
            catalogue, "_entries_from_snapshot", return_value=[]
        ):
            catalogue.collect_entries(
                catalogue.CatalogueContext(),
                policy=catalogue.FetchPolicy(refresh=True),
            )
        self.assertTrue(seen["refresh"])
        self.assertTrue(seen["allow_network"])

    def test_main_refresh_forwards_to_snapshot(self) -> None:
        import contextlib
        import tempfile
        from unittest import mock

        seen: dict = {}

        def spy(
            *,
            allow_network: bool,
            coordinator: Any = None,
            refresh: bool = False,
        ) -> Any:
            seen["refresh"] = refresh
            return mock.MagicMock(unsupported=None, report=None), ({}, {}, {}, {})

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.md")
            with mock.patch.object(cli, "OUTPUT_PATH", out), mock.patch.object(
                catalogue,
                "_build_catalogue_context",
                lambda **k: catalogue.CatalogueContext(),
            ), mock.patch.object(
                catalogue, "_snapshot_and_payloads", spy
            ), mock.patch.object(
                cli,
                "_publication_verdict",
                return_value=cli.PublicationVerdict(ok=True),
            ), contextlib.redirect_stdout(mock.MagicMock()):
                cli.main(["--refresh"])
        self.assertTrue(seen.get("refresh"))


class PublicationGuardTests(unittest.TestCase):
    """A degraded snapshot must not replace a good catalogue document."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-guard-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")

    def _report(self, *, usable: bool = True, failed: tuple = ()):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(mode=RefreshMode.OFFLINE, usable=usable, failed=failed)

    def test_previous_entry_count_is_read_from_an_existing_document(self) -> None:
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **412**\n")
        self.assertEqual(cli._previous_entry_count(self.out), 412)

    def test_missing_document_has_no_previous_count(self) -> None:
        self.assertIsNone(cli._previous_entry_count(self.out))

    def test_unusable_snapshot_is_refused(self) -> None:
        verdict = cli._publication_verdict(
            entries=[], report=self._report(usable=False), previous_count=None
        )
        self.assertFalse(verdict.ok)
        self.assertIn("unusable", verdict.reason.lower())

    def test_a_large_drop_is_refused_even_when_no_source_reported_failure(self) -> None:
        """The real cold-cache case: offline sources are not refreshed, not failed.

        A run against an empty supplemental cache produced 88 entries where the
        published document had 474, with report.usable True and report.failed
        empty -- so failure state cannot be the trigger. The count is.
        """
        verdict = cli._publication_verdict(
            entries=[object()] * 88, report=self._report(), previous_count=474
        )
        self.assertFalse(verdict.ok)
        self.assertIn("474", verdict.reason)

    def test_a_small_drop_still_publishes(self) -> None:
        """Ordinary regeneration jitter must not need an override flag."""
        verdict = cli._publication_verdict(
            entries=[object()] * 398, report=self._report(), previous_count=400
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_failed_sources_are_named_in_the_refusal(self) -> None:
        from core.catalogue_types import SourceId

        verdict = cli._publication_verdict(
            entries=[object()] * 10,
            report=self._report(failed=((SourceId.UPSTREAM, "boom"),)),
            previous_count=400,
        )
        self.assertFalse(verdict.ok)
        self.assertIn("upstream", verdict.reason)

    def test_a_healthy_snapshot_publishes(self) -> None:
        verdict = cli._publication_verdict(
            entries=[object()] * 400, report=self._report(), previous_count=400
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_allow_degraded_overrides_a_refusal(self) -> None:
        verdict = cli._publication_verdict(
            entries=[], report=self._report(usable=False), previous_count=400,
            allow_degraded=True,
        )
        self.assertTrue(verdict.ok, verdict.reason)

    def test_allow_degraded_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(cli._parse_args(["--allow-degraded"]).allow_degraded)
        self.assertFalse(cli._parse_args([]).allow_degraded)


class OfflineYamlCacheTests(unittest.TestCase):
    """The URL-keyed yaml cache must actually be readable, including offline."""

    _YAML = "training:\n  instruments: [vocals, other]\n  target_instrument: other\n"
    _URL = "https://example.invalid/cfg/model_test.yaml"

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-yamlcache-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.calls: list = []

    def _patches(self):
        from unittest import mock

        def record(request: Any, *args: Any, **kwargs: Any):
            self.calls.append(getattr(request, "full_url", request))
            raise urllib.error.URLError("blocked")

        return [
            mock.patch.object(catalogue, "YAML_CACHE_DIR", self.tmp),
            mock.patch("core.mdx_config_fetch._urlopen", record),
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", lambda *a, **k: False),
        ]

    def _seed_cache(self) -> str:
        path = catalogue._cache_path(self.tmp, self._URL, "model_test.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._YAML)
        return path

    def test_yaml_paths_includes_the_url_keyed_cache_entry(self) -> None:
        candidates = catalogue._yaml_paths("model_test.yaml", self._URL)
        expected = catalogue._cache_path(
            catalogue.YAML_CACHE_DIR, self._URL, "model_test.yaml"
        )
        self.assertIn(expected, candidates)

    def test_offline_reads_a_previously_cached_yaml(self) -> None:
        """The whole point of a cache-only offline mode."""
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            cached = self._seed_cache()
            self.assertTrue(os.path.isfile(cached))
            instruments, target, _arch, source = catalogue._load_yaml_meta(
                "model_test.yaml", self._URL, policy=catalogue.OFFLINE_FETCH_POLICY
            )

        self.assertEqual(self.calls, [], "offline must not fetch")
        self.assertEqual(sorted(instruments), ["other", "vocals"])
        self.assertEqual(target, "other")
        self.assertTrue(source.startswith("remote_yaml:"), source)

    def test_offline_without_a_cached_yaml_falls_back_without_fetching(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            catalogue._load_yaml_meta(
                "model_test.yaml", self._URL, policy=catalogue.OFFLINE_FETCH_POLICY
            )
        self.assertEqual(self.calls, [])


class CacheWriteAtomicityTests(unittest.TestCase):
    def test_a_failed_cache_write_does_not_leave_a_truncated_entry(self) -> None:
        """A truncated cache file would be re-served as valid for the whole TTL."""
        import shutil
        import tempfile
        from unittest import mock

        tmp = tempfile.mkdtemp(prefix="uvr-cache-atomic-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        url = "https://a.invalid/data.json"

        body = {"data": b'{"ok": 1}'}

        def opener(request: Any, *args: Any, **kwargs: Any):
            class _R:
                def read(self) -> bytes:
                    return body["data"]

                def __enter__(self) -> "_R":
                    return self

                def __exit__(self, *exc: Any) -> bool:
                    return False

            return _R()

        with mock.patch("core.mdx_config_fetch._urlopen", opener):
            good = catalogue._fetch_cached(url, tmp, "data.json")
            assert good is not None
            # Different bytes, so overwriting in place is distinguishable from
            # a staged write that never lands.
            body["data"] = b'{"ok": 2, "and": "much longer than the original"}'
            with mock.patch("os.replace", side_effect=OSError("disk full")):
                catalogue._fetch_cached(url, tmp, "data.json", refresh=True)

        with open(good, "rb") as handle:
            self.assertEqual(handle.read(), b'{"ok": 1}')
        self.assertEqual(os.listdir(tmp), [os.path.basename(good)])


class EntryMetaProvenanceTests(unittest.TestCase):
    """Metadata that came from the snapshot must not report as unavailable."""

    def test_entry_meta_supplied_metadata_is_recorded_as_its_source(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Roformer",
            weight_file="model.ckpt",
            name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(
            entry,
            EntryMeta(
                label="Some Roformer",
                display="Some Roformer",
                arch="Roformer",
                stems=["vocals", "other"],
                target_instrument="other",
            ),
        )
        self.assertNotEqual(entry.metadata_source, "unavailable")
        self.assertIn("catalogue_meta", entry.metadata_source)

    def test_entry_meta_that_adds_nothing_leaves_the_source_alone(self) -> None:
        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Roformer",
            weight_file="model.ckpt",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(entry, None)
        self.assertEqual(entry.metadata_source, "unavailable")


class SourceAttributionCostTests(unittest.TestCase):
    def test_mvsepless_conversion_is_not_repeated_per_label(self) -> None:
        """_source_for ran a full catalogue conversion once per label (~474x)."""
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(5)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        mvsepless = {"raw": {"needs": "conversion"}}
        with mock.patch(
            "core.mvsepless_catalog.convert_mvsepless_catalog", return_value={}
        ) as convert:
            catalogue._entries_from_snapshot(
                _Snapshot(),
                ({}, {}, {}, mvsepless),
                catalogue.CatalogueContext(),
                policy=catalogue.OFFLINE_FETCH_POLICY,
            )
        self.assertLessEqual(convert.call_count, 1, "converted once per label")


class ReferenceTsvOptInTests(unittest.TestCase):
    """The TSV is a deliberate output, not a side effect of running the command."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-tsv-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tsv = os.path.join(self.tmp, "model_intent_reference.tsv")
        self.out = os.path.join(self.tmp, "models-catalogue.md")

    def _community(self):
        return {
            "model.ckpt": catalogue.CommunityRef(
                filename="model.ckpt",
                arch="Roformer",
                primary_stem="Vocals",
                stems_text="vocals, other",
                friendly_name="Some Model",
                intent="vocals",
            )
        }

    def _run(self, argv: list, *, entries: int = 1) -> int:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(entries)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        ctx = catalogue.CatalogueContext(community_by_file=self._community())
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", self.tsv))
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.out))
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context", lambda **k: ctx)
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads",
                    lambda **k: (_Snapshot(), ({}, {}, {}, {})),
                )
            )
            return cli.main(argv)

    def test_a_default_run_does_not_write_the_tsv(self) -> None:
        self.assertEqual(self._run([]), 0)
        self.assertTrue(os.path.isfile(self.out))
        self.assertFalse(os.path.exists(self.tsv), "TSV written without being asked")

    def test_write_tsv_writes_it(self) -> None:
        self.assertEqual(self._run(["--write-tsv"]), 0)
        self.assertTrue(os.path.isfile(self.tsv))
        with open(self.tsv, encoding="utf-8") as handle:
            self.assertIn("model.ckpt", handle.read())

    def test_a_refused_run_does_not_write_the_tsv(self) -> None:
        """A run that refuses to publish must not mutate the other artifact either."""
        with open(self.out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **400**\n")
        self.assertEqual(self._run(["--write-tsv"], entries=1), 2)
        self.assertFalse(os.path.exists(self.tsv), "refused run still wrote the TSV")

    def test_write_tsv_flag_is_exposed_on_the_cli(self) -> None:
        self.assertTrue(cli._parse_args(["--write-tsv"]).write_tsv)
        self.assertFalse(cli._parse_args([]).write_tsv)


class CheckModeTests(unittest.TestCase):
    """--check reports drift without touching the tree."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        self.tmp = tempfile.mkdtemp(prefix="uvr-check-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.out = os.path.join(self.tmp, "models-catalogue.md")
        self.tsv = os.path.join(self.tmp, "model_intent_reference.tsv")

    def _run(self, argv: list) -> int:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(3)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        ctx = catalogue.CatalogueContext(
            community_by_file={
                "model.ckpt": catalogue.CommunityRef(
                    filename="model.ckpt",
                    arch="Roformer",
                    primary_stem="Vocals",
                    stems_text="vocals, other",
                    friendly_name="Some Model",
                    intent="vocals",
                )
            }
        )
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.out))
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", self.tsv))
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context", lambda **k: ctx)
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads",
                    lambda **k: (_Snapshot(), ({}, {}, {}, {})),
                )
            )
            return cli.main(argv)

    def test_check_on_an_up_to_date_document_exits_zero(self) -> None:
        self.assertEqual(self._run([]), 0)
        before = open(self.out, "rb").read()
        mtime = os.path.getmtime(self.out)
        self.assertEqual(self._run(["--check"]), 0)
        self.assertEqual(open(self.out, "rb").read(), before)
        self.assertEqual(os.path.getmtime(self.out), mtime, "--check rewrote the file")

    def test_check_reports_drift_without_writing(self) -> None:
        self.assertEqual(self._run([]), 0)
        with open(self.out, "a", encoding="utf-8") as handle:
            handle.write("\ndrifted\n")
        drifted = open(self.out, "rb").read()
        self.assertEqual(self._run(["--check"]), 1)
        self.assertEqual(open(self.out, "rb").read(), drifted, "--check wrote anyway")

    def test_check_on_a_missing_document_is_drift(self) -> None:
        self.assertEqual(self._run(["--check"]), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_check_also_covers_the_tsv_when_requested(self) -> None:
        self.assertEqual(self._run(["--write-tsv"]), 0)
        self.assertEqual(self._run(["--check", "--write-tsv"]), 0)
        os.unlink(self.tsv)
        self.assertEqual(self._run(["--check", "--write-tsv"]), 1)
        self.assertFalse(os.path.exists(self.tsv))

    def test_check_and_write_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            cli._parse_args(["--check", "--write"])

    def test_write_is_the_default(self) -> None:
        self.assertFalse(cli._parse_args([]).check)


class VolatileHeaderTests(unittest.TestCase):
    """Drift means the catalogue changed, not that time passed."""

    def test_a_changed_generation_timestamp_is_not_drift(self) -> None:
        rendered = render._render([], unsupported_count=0)
        aged = rendered.replace(
            "Generated: ", "Generated: 1999-01-01 00:00 UTC ignored ", 1
        )
        self.assertNotEqual(rendered, aged)
        self.assertEqual(
            render._canonical_for_diff(rendered),
            render._canonical_for_diff(aged),
        )

    def test_a_changed_entry_is_drift(self) -> None:
        rendered = render._render([], unsupported_count=0)
        changed = rendered.replace("Total catalogue entries: **0**", "**9**", 1)
        self.assertNotEqual(
            render._canonical_for_diff(rendered),
            render._canonical_for_diff(changed),
        )


class ProvenanceBlockTests(unittest.TestCase):
    """The document should say whether it was generated from good data."""

    def _report(
        self,
        *,
        succeeded: tuple = (),
        failed: tuple = (),
        stale: tuple = (),
        usable: bool = True,
    ):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(
            mode=RefreshMode.STALE_WHILE_REVALIDATE,
            succeeded=succeeded,
            failed=failed,
            stale=stale,
            usable=usable,
        )

    def test_names_succeeded_and_failed_sources(self) -> None:
        from core.catalogue_types import SourceId

        text = render._render(
            [],
            unsupported_count=0,
            report=self._report(
                succeeded=(SourceId.UPSTREAM,),
                failed=((SourceId.POLITREES, "timeout"),),
                stale=(SourceId.MVSEPLESS,),
            ),
        )
        self.assertIn("upstream", text)
        self.assertIn("politrees", text)
        self.assertIn("timeout", text)
        self.assertIn("mvsepless", text)

    def test_provenance_lines_do_not_count_as_drift(self) -> None:
        from core.catalogue_types import SourceId

        a = render._render([], unsupported_count=0, report=self._report())
        b = render._render(
            [],
            unsupported_count=0,
            report=self._report(failed=((SourceId.POLITREES, "timeout"),)),
        )
        self.assertNotEqual(a, b)
        self.assertEqual(
            render._canonical_for_diff(a), render._canonical_for_diff(b)
        )

    def test_renders_without_a_report(self) -> None:
        text = render._render([], unsupported_count=0, report=None)
        self.assertIn("Total catalogue entries", text)


class FabricatedFlagTests(unittest.TestCase):
    """Metadata that cannot resolve a backend must not produce mismatch flags."""

    def test_intent_alone_is_not_resolved_metadata(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue.ModelEntry(
            source="mvsepless", family="Roformer",
            catalogue_label="Some Model", weight_file="m.ckpt", name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(
            entry, EntryMeta(label="L", display="L", arch="Roformer", intent="vocals")
        )
        self.assertEqual(entry.metadata_source, "unavailable")

    def test_stems_still_count_as_resolved_metadata(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue.ModelEntry(
            source="mvsepless", family="Roformer",
            catalogue_label="Some Model", weight_file="m.ckpt",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(
            entry,
            EntryMeta(label="L", display="L", arch="Roformer", stems=["vocals", "other"]),
        )
        self.assertEqual(entry.metadata_source, "catalogue_meta")

    def test_unknown_backend_focus_produces_no_mismatch_flags(self) -> None:
        """You cannot detect a mismatch against a backend you could not determine."""
        entry = catalogue.ModelEntry(
            source="mvsepless", family="Roformer",
            catalogue_label="Some Model", weight_file="m.ckpt", name_intent="vocals",
        )
        entry.metadata_source = "catalogue_meta"
        entry.backend_focus = "unknown"
        self.assertEqual(catalogue._flag_mismatches(entry), [])

    def test_intent_only_entry_ends_up_unflagged(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue.ModelEntry(
            source="mvsepless", family="Roformer",
            catalogue_label="Some Model", weight_file="m.ckpt", name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue._apply_entry_meta(
            entry, EntryMeta(label="L", display="L", arch="Roformer", intent="vocals")
        )
        catalogue._finalize_entry(entry)
        self.assertEqual(entry.flags, [])


class YamlProvenanceStabilityTests(unittest.TestCase):
    """The metadata label must not flip between runs, or --check sees drift."""

    def test_a_downloaded_config_reports_the_same_source_on_the_next_run(self) -> None:
        import shutil
        import tempfile
        from unittest import mock

        store = tempfile.mkdtemp(prefix="uvr-cfgstore-")
        self.addCleanup(shutil.rmtree, store, ignore_errors=True)
        url = "https://example.invalid/c/m.yaml"
        body = "training:\n  instruments: [vocals, other]\n  target_instrument: other\n"

        def fake_fetch(name: str, _url: str) -> bool:
            with open(os.path.join(store, name), "w", encoding="utf-8") as handle:
                handle.write(body)
            return True

        with mock.patch("core.paths.MDX_C_CONFIG_PATH", store), mock.patch(
            "core.mdx_config_fetch.fetch_mdx_config_url", fake_fetch
        ):
            first = catalogue._load_yaml_meta("m.yaml", url)[3]
            second = catalogue._load_yaml_meta("m.yaml", url)[3]

        self.assertEqual(first, second, "provenance label flipped between runs")


class CheckContractTests(unittest.TestCase):
    """--check must be genuinely read-only and must not lie about coverage."""

    def test_check_forbids_metadata_writes(self) -> None:
        """fetch_mdx_config_url writes yaml into the repo in the dev layout."""
        policy = cli._policy_for(
            cli._parse_args(["--check"])
        )
        self.assertFalse(policy.allow_metadata_writes)

    def test_a_normal_run_still_allows_metadata_writes(self) -> None:
        policy = cli._policy_for(cli._parse_args([]))
        self.assertTrue(policy.allow_metadata_writes)

    def test_load_yaml_meta_does_not_fetch_configs_when_writes_are_denied(self) -> None:
        from unittest import mock

        called = []

        def spy(name: str, url: str) -> bool:
            called.append(name)
            return False

        policy = catalogue.FetchPolicy(allow_network=True, allow_metadata_writes=False)
        with mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", spy), mock.patch(
            "core.mdx_config_fetch._urlopen",
            side_effect=urllib.error.URLError("blocked"),
        ):
            catalogue._load_yaml_meta(
                "nope.yaml", "https://example.invalid/nope.yaml", policy=policy
            )
        self.assertEqual(called, [], "--check wrote a config into the model store")

    def test_check_does_not_claim_to_refuse_a_write_it_never_makes(self) -> None:
        import contextlib
        import io
        from unittest import mock

        class _Snapshot:
            vr: dict = {}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        import tempfile

        tmp = tempfile.mkdtemp(prefix="uvr-checkmsg-")
        out = os.path.join(tmp, "models-catalogue.md")
        with open(out, "w", encoding="utf-8") as handle:
            handle.write("## Summary\n\n- Total catalogue entries: **400**\n")

        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", out))
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context",
                                  lambda **k: catalogue.CatalogueContext())
            )
            stack.enter_context(
                mock.patch.object(catalogue, "_snapshot_and_payloads",
                                  lambda **k: (_Snapshot(), ({}, {}, {}, {})))
            )
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(["--check"])

        self.assertEqual(rc, 2)
        message = stderr.getvalue()
        self.assertNotIn("Refusing to write", message)
        self.assertIn("cannot judge", message.lower())

    def test_write_tsv_without_community_data_is_reported_not_silent(self) -> None:
        import contextlib
        import io
        import tempfile
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        tmp = tempfile.mkdtemp(prefix="uvr-tsvwarn-")
        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(cli, "OUTPUT_PATH", os.path.join(tmp, "c.md"))
            )
            stack.enter_context(
                mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(tmp, "r.tsv"))
            )
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context",
                                  lambda **k: catalogue.CatalogueContext())
            )
            stack.enter_context(
                mock.patch.object(catalogue, "_snapshot_and_payloads",
                                  lambda **k: (_Snapshot(), ({}, {}, {}, {})))
            )
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(["--write-tsv"])

        self.assertEqual(rc, 0)
        self.assertIn("tsv", stderr.getvalue().lower())


class IntermediateRepresentationTests(unittest.TestCase):
    """A stable machine-readable form that Markdown and TSV render from."""

    def _entry(self, label: str = "Some Model"):
        return catalogue.ModelEntry(
            source="mvsepless", family="Roformer", catalogue_label=label,
            weight_file="m.ckpt", instruments=["vocals", "other"], stem_count=2,
            name_intent="vocals", metadata_source="catalogue_meta",
        )

    def test_carries_a_schema_version(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=0)
        self.assertEqual(ir["schema_version"], catalogue.IR_SCHEMA_VERSION)

    def test_round_trips_through_json(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=3)
        restored = json.loads(json.dumps(ir))
        self.assertEqual(restored["unsupported_omitted"], 3)
        self.assertEqual(restored["entries"][0]["catalogue_label"], "Some Model")
        self.assertEqual(restored["entries"][0]["instruments"], ["vocals", "other"])

    def test_entry_count_is_recorded_for_the_publication_guard(self) -> None:
        ir = catalogue.build_ir([self._entry("a"), self._entry("b")], report=None, unsupported_count=0)
        self.assertEqual(ir["entry_count"], 2)

    def test_provenance_is_included_when_a_report_exists(self) -> None:
        from core.catalogue_types import RefreshMode, RefreshReport, SourceId

        report = RefreshReport(
            mode=RefreshMode.OFFLINE, usable=True, failed=((SourceId.POLITREES, "boom"),)
        )
        ir = catalogue.build_ir([self._entry()], report=report, unsupported_count=0)
        self.assertEqual(ir["provenance"]["mode"], "offline")
        self.assertTrue(ir["provenance"]["failed"])

    def test_no_report_still_produces_valid_ir(self) -> None:
        ir = catalogue.build_ir([self._entry()], report=None, unsupported_count=0)
        self.assertEqual(ir["provenance"], {})

    def test_previous_entry_count_prefers_the_sidecar(self) -> None:
        """More reliable than re-parsing a rendered summary line."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            sidecar = catalogue._ir_path_for(doc)
            with open(sidecar, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema_version": 1,
                        "entry_count": 412,
                        # Must prove it describes this document; see
                        # SidecarTrustTests for the stale case.
                        "document_sha256": catalogue._document_digest(doc),
                    },
                    handle,
                )
            self.assertEqual(cli._previous_entry_count(doc), 412)

    def test_previous_entry_count_falls_back_to_the_document(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            self.assertEqual(cli._previous_entry_count(doc), 7)

    def test_a_corrupt_sidecar_falls_back_rather_than_failing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            doc = os.path.join(tmp, "models-catalogue.md")
            with open(doc, "w", encoding="utf-8") as handle:
                handle.write("- Total catalogue entries: **7**\n")
            with open(catalogue._ir_path_for(doc), "w", encoding="utf-8") as handle:
                handle.write("{not json")
            self.assertEqual(cli._previous_entry_count(doc), 7)


class SummaryModeTests(unittest.TestCase):
    """--summary answers the maintainer's likely question without 7,000 lines."""

    def _entries(self):
        flagged = catalogue.ModelEntry(
            source="TRvlvr", family="Roformer", catalogue_label="Bad Model",
            weight_file="bad.ckpt", name_intent="vocals",
            metadata_source="bundled_yaml:x.yaml",
        )
        flagged.flags = ["NAME says vocal but backend is instrumental-focused"]
        unknown = catalogue.ModelEntry(
            source="extras", family="MDX23C", catalogue_label="Mystery",
            weight_file="m.ckpt", name_intent="unknown",
        )
        fine = catalogue.ModelEntry(
            source="TRvlvr", family="VR Architecture", catalogue_label="Good Model",
            weight_file="g.pth", name_intent="vocals",
            metadata_source="bundled_yaml:y.yaml",
        )
        return [flagged, unknown, fine]

    def test_reports_counts(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=4)
        self.assertIn("**3**", text)
        self.assertIn("4", text)

    def test_lists_flagged_entries(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertIn("Bad Model", text)
        self.assertIn("backend is instrumental-focused", text)

    def test_lists_unknown_intent_entries(self) -> None:
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertIn("Mystery", text)

    def test_omits_the_clean_entries(self) -> None:
        """The point is the exception list, not the full inventory."""
        text = render.render_summary_report(self._entries(), unsupported_count=0)
        self.assertNotIn("Good Model", text)

    def test_is_much_shorter_than_the_full_render(self) -> None:
        entries = self._entries()
        full = render._render(entries, unsupported_count=0)
        summary = render.render_summary_report(entries, unsupported_count=0)
        self.assertLess(len(summary), len(full))

    def test_summary_does_not_overwrite_the_document(self) -> None:
        """A summary is an ad-hoc query, not a replacement for the catalogue."""
        import contextlib
        import io
        import tempfile
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "models-catalogue.md")
            with open(out, "w", encoding="utf-8") as handle:
                handle.write("THE REAL CATALOGUE\n- Total catalogue entries: **400**\n")
            stdout = io.StringIO()
            with mock.patch.object(cli, "OUTPUT_PATH", out), \
                 mock.patch.object(
                     catalogue, "_build_catalogue_context",
                     lambda **k: catalogue.CatalogueContext()
                 ), \
                 mock.patch.object(
                     catalogue, "_snapshot_and_payloads",
                     lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                 ), \
                 contextlib.redirect_stdout(stdout):
                rc = cli.main(["--summary"])

            self.assertEqual(rc, 0)
            with open(out, encoding="utf-8") as handle:
                self.assertIn("THE REAL CATALOGUE", handle.read())
            self.assertFalse(os.path.exists(catalogue._ir_path_for(out)))
        self.assertIn("Counts", stdout.getvalue())

    def test_summary_flag_exists(self) -> None:
        self.assertTrue(cli._parse_args(["--summary"]).summary)
        self.assertFalse(cli._parse_args([]).summary)


class CollectEntriesIsTheRealPathTests(unittest.TestCase):
    """A second entry path exercised only by tests is how main and tests drift."""

    def test_main_collects_through_collect_entries(self) -> None:
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(cli, "OUTPUT_PATH", os.path.join(tmp, "c.md")), \
                 mock.patch.object(
                     catalogue, "_build_catalogue_context",
                     lambda **k: catalogue.CatalogueContext()
                 ), \
                 mock.patch.object(
                     catalogue, "_snapshot_and_payloads",
                     lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                 ), \
                 mock.patch.object(
                     catalogue, "collect_entries", wraps=catalogue.collect_entries
                 ) as collect:
                cli.main([])
        self.assertEqual(collect.call_count, 1, "main did not go through collect_entries")


class SidecarTrustTests(unittest.TestCase):
    """The sidecar may only speak for the document it was written with."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-sidecar-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.doc = os.path.join(self.tmp, "models-catalogue.md")

    def _write_doc(self, count: int) -> None:
        with open(self.doc, "w", encoding="utf-8") as handle:
            handle.write(f"- Total catalogue entries: **{count}**\n")

    def _write_sidecar(self, count: int, *, digest: Optional[str] = None) -> None:
        payload: dict = {"schema_version": 1, "entry_count": count}
        if digest is not None:
            payload["document_sha256"] = digest
        with open(catalogue._ir_path_for(self.doc), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_a_sidecar_written_with_this_document_is_trusted(self) -> None:
        self._write_doc(474)
        self._write_sidecar(474, digest=catalogue._document_digest(self.doc))
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_a_stale_sidecar_cannot_lower_the_guard_floor(self) -> None:
        """The exact hazard: a degraded run's sidecar outliving its document."""
        self._write_doc(474)
        self._write_sidecar(88, digest="sha-of-some-other-document")
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_a_sidecar_with_no_digest_is_not_trusted(self) -> None:
        """Written before the cross-check existed; the document is authoritative."""
        self._write_doc(474)
        self._write_sidecar(88)
        self.assertEqual(cli._previous_entry_count(self.doc), 474)

    def test_the_sidecar_is_used_when_the_document_has_no_count(self) -> None:
        with open(self.doc, "w", encoding="utf-8") as handle:
            handle.write("a document with no summary line\n")
        self._write_sidecar(412, digest=catalogue._document_digest(self.doc))
        self.assertEqual(cli._previous_entry_count(self.doc), 412)

    def test_a_published_run_writes_a_matching_digest(self) -> None:
        import contextlib
        from unittest import mock

        class _Snapshot:
            vr = {"M": "m.pth"}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", self.doc))
            stack.enter_context(
                mock.patch.object(catalogue, "_build_catalogue_context",
                                  lambda **k: catalogue.CatalogueContext())
            )
            stack.enter_context(
                mock.patch.object(catalogue, "_snapshot_and_payloads",
                                  lambda **k: (_Snapshot(), ({}, {}, {}, {})))
            )
            self.assertEqual(cli.main([]), 0)

        with open(catalogue._ir_path_for(self.doc), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["document_sha256"], catalogue._document_digest(self.doc))


class SummaryHonestyTests(unittest.TestCase):
    """A summary of a failed fetch must not read as a clean bill of health."""

    def _dead_report(self):
        from core.catalogue_types import RefreshMode, RefreshReport

        return RefreshReport(mode=RefreshMode.OFFLINE, usable=False)

    def test_an_unusable_snapshot_is_called_out(self) -> None:
        text = render.render_summary_report([], unsupported_count=0, report=self._dead_report())
        self.assertNotIn("Nothing flagged", text)
        self.assertIn("unusable", text.lower())

    def test_an_empty_catalogue_is_called_out_even_without_a_report(self) -> None:
        text = render.render_summary_report([], unsupported_count=0, report=None)
        self.assertNotIn("Nothing flagged", text)
        self.assertIn("no entries", text.lower())

    def test_a_healthy_empty_of_problems_run_still_reads_clean(self) -> None:
        entry = catalogue.ModelEntry(
            source="TRvlvr", family="VR Architecture", catalogue_label="Good",
            weight_file="g.pth", name_intent="vocals",
            metadata_source="bundled_yaml:y.yaml",
        )
        text = render.render_summary_report([entry], unsupported_count=0)
        self.assertIn("Nothing flagged", text)


class EntryMetaOverlayTests(unittest.TestCase):
    def test_fills_blank_stems_target_and_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_KARAOKE

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="MelBand Roformer Karaoke",
            weight_file="kara.ckpt",
            name_intent="unknown",
        )
        meta = EntryMeta(
            label=entry.catalogue_label,
            display="MelBand Roformer — Karaoke",
            arch="MDX",
            stems=["vocals", "other"],
            target_instrument="vocals",
            intent=INTENT_KARAOKE,
        )
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["vocals", "other"])
        self.assertEqual(entry.target_instrument, "vocals")
        self.assertEqual(entry.primary_stem, "vocals")
        self.assertEqual(entry.name_intent, INTENT_KARAOKE)

    def test_does_not_overwrite_resolved_fields_or_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_UNKNOWN

        entry = catalogue.ModelEntry(
            source="extras",
            family="Roformer",
            catalogue_label="Named",
            weight_file="model.ckpt",
            instruments=["drums", "bass"],
            target_instrument="drums",
            primary_stem="drums",
            name_intent="instrumental",
        )
        meta = EntryMeta(
            label=entry.catalogue_label,
            display="Named",
            arch="MDX",
            stems=["vocals"],
            target_instrument="vocals",
            intent=INTENT_UNKNOWN,
        )
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["drums", "bass"])
        self.assertEqual(entry.target_instrument, "drums")
        self.assertEqual(entry.primary_stem, "drums")
        self.assertEqual(entry.name_intent, "instrumental")

        entry.name_intent = "unknown"
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.name_intent, "unknown")


class RenderDisplayTests(unittest.TestCase):
    def test_render_uses_canonical_display_name(self) -> None:
        from core.model_naming import canonical_display_name

        label = "Roformer Model: BandSplit Roformer | HyperACE by Unwa"
        entry = catalogue.ModelEntry(
            source="extras",
            family="Roformer",
            catalogue_label=label,
            weight_file="bs_hyperace.ckpt",
            name_intent="instrumental",
            best_result="Instrumental",
            backend_focus="instrumental_primary",
        )
        rendered = render._render([entry])
        display = canonical_display_name(label)
        self.assertIn(display, rendered)
        self.assertNotIn("Roformer Model:", rendered)

    def test_render_header_lists_all_sources(self) -> None:
        rendered = render._render([])
        self.assertIn("TRvlvr + Politrees + extras + mvsepless", rendered)
        self.assertIn(
            "catalogue helper summarizing primary/target",
            rendered,
        )
        self.assertNotIn("what `ModelConfig` uses as `primary_stem`", rendered)

    def test_parse_args_offline(self) -> None:
        args = cli._parse_args(["--offline"])
        self.assertTrue(args.offline)


class FetchHelperTests(unittest.TestCase):
    def test_fetch_cached_uses_core_urlopen(self) -> None:
        import tempfile
        from unittest.mock import patch

        class _Resp:
            def read(self) -> bytes:
                return b'{"ok": true}'

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp, patch(
            "core.mdx_config_fetch._urlopen", return_value=_Resp()
        ):
            path = catalogue._fetch_cached("https://example.invalid/x.json", tmp, "x.json")
            if path is None:
                self.fail("expected a cached file")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"ok": true}')

    def test_load_yaml_meta_prefers_core_config_fetch(self) -> None:
        import tempfile
        from unittest.mock import patch

        yaml_name = "zz_core_fetch_probe.yaml"
        body = "training:\n  instruments: [vocals, other]\n  target_instrument: vocals\n"

        def fake_fetch(name: str, url: str) -> bool:
            dest = os.path.join(catalogue.paths.MDX_C_CONFIG_PATH, name)
            os.makedirs(catalogue.paths.MDX_C_CONFIG_PATH, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as handle:
                handle.write(body)
            return True

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            catalogue.paths, "MDX_C_CONFIG_PATH", tmp
        ), patch(
            "core.mdx_config_fetch.fetch_mdx_config_url", side_effect=fake_fetch
        ), patch.object(
            catalogue, "_fetch_yaml", side_effect=AssertionError("yaml cache fallback")
        ):
            instruments, target, _arch, source = catalogue._load_yaml_meta(
                yaml_name, "https://example.invalid/x.yaml"
            )
        self.assertEqual(instruments, ["vocals", "other"])
        self.assertEqual(target, "vocals")
        # Labelled by where it now lives, not by whether this run fetched it:
        # the config store label has to match what the next run will report,
        # or the difference reads as catalogue drift.
        self.assertEqual(source, f"bundled_yaml:{yaml_name}")


if __name__ == "__main__":
    unittest.main()
