"""Generator offline behavior."""

import os
import unittest
import urllib.error
from typing import Any
from unittest import mock

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as fixtures

import generate_models_catalogue as cli
from catalogue import audit_types as catalogue_audit_types
from catalogue import cache as catalogue_cache
from catalogue import collect as catalogue
from catalogue import config_evidence as catalogue_config_evidence
from catalogue import entry_rules as catalogue_entry_rules
from catalogue import evidence as catalogue_evidence
from catalogue import locations as catalogue_locations
from catalogue import render
from catalogue import types as catalogue_types
from catalogue.audit_types import (
    CatalogueEvidenceCounts,
    StemAuditDiagnostic,
    StemAuditResult,
)

from core import paths as core_paths
from core.catalogue_types import SourceId




# isort: on

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
                SourceId.UPSTREAM: fixtures._local(SourceId.UPSTREAM, upstream),
                SourceId.POLITREES: fixtures._disabled(SourceId.POLITREES),
                SourceId.EXTRAS: fixtures._disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: fixtures._disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def _patches(self):
        """Record every network entry point instead of raising.

        fetch_cached swallows URLError/OSError, so a raising stub could be
        silently absorbed and the test would pass while the socket was opened.
        """
        from unittest import mock

        def record_urlopen(request: Any, *args: Any, **kwargs: Any):
            import urllib.error

            url = getattr(request, "full_url", request)
            self.calls.append(f"_urlopen({url})")
            # A URLError is what a real offline machine raises, and fetch_cached
            # handles it; the recorded call list is what the assertions read.
            raise urllib.error.URLError("blocked by test")

        def record_fetch_config(name: Any, url: Any, *args: Any, **kwargs: Any) -> bool:
            self.calls.append(f"fetch_mdx_config_url({name}, {url})")
            return False

        return [
            mock.patch("core.mdx_config_fetch._urlopen", record_urlopen),
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", record_fetch_config),
            mock.patch.object(catalogue_locations, "COMMUNITY_CACHE_DIR", os.path.join(self.tmp, "cm")),
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", os.path.join(self.tmp, "yaml")),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(self.tmp, "ref.tsv")),
            mock.patch.object(cli, "OUTPUT_PATH", os.path.join(self.tmp, "out.md")),
            mock.patch.object(
                cli,
                "DISPLAY_REFERENCE_TSV_PATH",
                os.path.join(self.tmp, "display.tsv"),
            ),
            mock.patch.object(
                cli,
                "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                os.path.join(self.tmp, "stem.tsv"),
            ),
            mock.patch.object(
                cli.stem_audit,
                "audit_catalogue_stems",
                side_effect=fixtures._clean_stem_audit,
            ),
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
        path = catalogue_cache.fetch_cached(
            "https://example.invalid/x.json", cache_dir, "x.json", allow_network=False
        )
        self.assertIsNone(path)
        self.assertFalse(os.path.exists(cache_dir), "offline miss created a cache dir")

    def test_load_yaml_meta_offline_does_not_fetch_or_write_config(self) -> None:
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            result = catalogue_config_evidence._load_yaml_meta(
                "model_test.yaml",
                "https://example.invalid/model_test.yaml",
                allow_network=False,
            )
        self.assertEqual(self.calls, [])
        # Falls back to the name heuristic rather than fetching.
        self.assertIsInstance(result, tuple)

    def test_main_offline_degrades_without_supplemental_evidence(self) -> None:
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

        self.assertEqual(rc, 2)
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


class CommunitySupplementAvailabilityTests(unittest.TestCase):
    """Malformed community evidence must not look like a valid empty source."""

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-community-evidence-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _context_from_cached_community_bytes(self, data: bytes) -> catalogue_types.CatalogueContext:
        from unittest import mock

        cache_dir = os.path.join(self.tmp, "cached-community")
        cache_path = catalogue_cache._cache_path(
            cache_dir,
            catalogue._COMMUNITY_MODELS_URL,
            "models.txt",
        )
        os.makedirs(cache_dir)
        with open(cache_path, "wb") as handle:
            handle.write(data)
        with mock.patch.object(catalogue_locations, "COMMUNITY_CACHE_DIR", cache_dir):
            return catalogue._build_catalogue_context(
                policy=catalogue_cache.FetchPolicy(allow_network=False)
            )

    def _context_from_fetched_community_bytes(self, data: bytes) -> catalogue_types.CatalogueContext:
        from unittest import mock

        class _Response:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def read(self) -> bytes:
                return self.payload

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        def urlopen(url: object) -> _Response:
            if str(url) == catalogue._COMMUNITY_MODELS_URL:
                return _Response(data)
            return _Response(b"{}")

        with (
            mock.patch.object(
                catalogue_locations,
                "COMMUNITY_CACHE_DIR",
                os.path.join(self.tmp, "fetched-community"),
            ),
            mock.patch("core.mdx_config_fetch._urlopen", side_effect=urlopen),
        ):
            return catalogue._build_catalogue_context(
                policy=catalogue_cache.FetchPolicy(allow_cache_writes=False)
            )

    def test_valid_empty_community_bytes_remain_available_from_cache(self) -> None:
        self.assertEqual(catalogue_entry_rules._parse_community_models_bytes(b""), ({}, True))

        context = self._context_from_cached_community_bytes(b"")
        self.assertEqual(context.community_by_file, {})
        self.assertNotIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

    def test_supported_rows_survive_well_formed_demucs_yaml_rows(self) -> None:
        payload = (
            b"fixture.ckpt  MDX  vocals*, other  Fixture Model\n"
            b"htdemucs.yaml  Demucs  vocals, drums, bass, other  htdemucs\n"
        )
        refs, available = catalogue_entry_rules._parse_community_models_bytes(payload)

        self.assertTrue(available)
        self.assertEqual(set(refs), {"fixture.ckpt"})
        self.assertEqual(refs["fixture.ckpt"].friendly_name, "Fixture Model")
        context = self._context_from_cached_community_bytes(payload)
        self.assertNotIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

    def test_invalid_community_bytes_are_unavailable_from_cache(self) -> None:
        self.assertEqual(catalogue_entry_rules._parse_community_models_bytes(b"\xff"), ({}, False))

        context = self._context_from_cached_community_bytes(b"\xff")
        self.assertIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

    def test_malformed_community_text_is_unavailable_from_cache(self) -> None:
        malformed = b"this is not a models.txt row\n"
        self.assertEqual(catalogue_entry_rules._parse_community_models_bytes(malformed), ({}, False))

        context = self._context_from_cached_community_bytes(malformed)
        self.assertIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

    def test_invalid_in_memory_community_bytes_degrade_publication(self) -> None:
        import tempfile
        from unittest import mock

        context = self._context_from_fetched_community_bytes(b"\xff")
        self.assertIn(
            "community models.txt reference",
            context.unavailable_supplemental_evidence,
        )

        class _Snapshot:
            unsupported: dict[str, object] = {}
            report = None

        entry = catalogue_types.ModelEntry(
            source="fixture",
            family="MDX23C",
            catalogue_label="Fixture",
            weight_file="fixture.ckpt",
            metadata_source="fixture",
        )
        with tempfile.TemporaryDirectory(prefix="uvr-community-degraded-") as output_dir:
            with (
                mock.patch.object(cli, "OUTPUT_PATH", os.path.join(output_dir, "catalogue.md")),
                mock.patch.object(
                    cli, "REFERENCE_TSV_PATH", os.path.join(output_dir, "intent.tsv")
                ),
                mock.patch.object(
                    cli,
                    "DISPLAY_REFERENCE_TSV_PATH",
                    os.path.join(output_dir, "display.tsv"),
                ),
                mock.patch.object(
                    cli,
                    "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                    os.path.join(output_dir, "stem.tsv"),
                ),
                mock.patch.object(catalogue, "_build_catalogue_context", return_value=context),
                mock.patch.object(
                    catalogue, "collect_entries", return_value=(_Snapshot(), [entry])
                ),
                mock.patch.object(
                    cli.stem_audit,
                    "audit_catalogue_stems",
                    side_effect=fixtures._clean_stem_audit,
                ),
            ):
                self.assertEqual(cli.main([]), 2)


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
            catalogue_locations.YAML_CACHE_DIR,
            catalogue_locations.COMMUNITY_CACHE_DIR,
        ):
            self.assertTrue(
                cache_dir.startswith(paths.CACHE_DIR),
                f"{cache_dir} is not under CACHE_DIR",
            )
            self.assertNotIn("docs", os.path.relpath(cache_dir, paths.CACHE_DIR))

    def test_same_basename_from_different_urls_does_not_alias(self) -> None:
        """Two models can both ship a 'config.yaml'."""
        with self._opener(b"first"):
            a = catalogue_cache.fetch_cached("https://a.invalid/x/config.yaml", self.tmp, "config.yaml")
        with self._opener(b"second"):
            b = catalogue_cache.fetch_cached("https://b.invalid/y/config.yaml", self.tmp, "config.yaml")
        self.assertNotEqual(a, b)
        assert a is not None and b is not None
        with open(a, "rb") as handle:
            self.assertEqual(handle.read(), b"first")
        with open(b, "rb") as handle:
            self.assertEqual(handle.read(), b"second")

    def test_yaml_fetch_accepts_compact_yml_extension(self) -> None:
        with mock.patch.object(
            catalogue_cache,
            "fetch_cached_bytes",
            return_value=(b"training: {}", "/cache/config.yml"),
        ) as fetch:
            result = catalogue_cache.fetch_yaml_bytes(
                "https://example.test/config.yml",
                "config.yml",
            )

        self.assertEqual(result, (b"training: {}", "/cache/config.yml"))
        fetch.assert_called_once_with(
            "https://example.test/config.yml",
            catalogue_locations.YAML_CACHE_DIR,
            "config.yml",
            policy=catalogue_cache.DEFAULT_FETCH_POLICY,
        )

    def test_a_fresh_cache_entry_is_not_refetched(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            catalogue_cache.fetch_cached(url, self.tmp, "data.json")
            catalogue_cache.fetch_cached(url, self.tmp, "data.json")
        self.assertEqual(len(self.fetched), 1)

    def test_a_stale_cache_entry_is_refetched(self) -> None:
        """A normal online run must not reuse an arbitrarily old supplement."""
        url = "https://a.invalid/data.json"
        with self._opener():
            path = catalogue_cache.fetch_cached(url, self.tmp, "data.json")
            assert path
            os.utime(path, (0, 0))  # epoch: far older than any TTL
            catalogue_cache.fetch_cached(url, self.tmp, "data.json")
        self.assertEqual(len(self.fetched), 2)

    def test_stale_entry_is_still_served_when_offline(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            path = catalogue_cache.fetch_cached(url, self.tmp, "data.json")
            assert path
            os.utime(path, (0, 0))
        with self._opener():
            served = catalogue_cache.fetch_cached(url, self.tmp, "data.json", allow_network=False)
        self.assertEqual(served, path)
        self.assertEqual(len(self.fetched), 1)

    def test_refresh_refetches_even_a_fresh_entry(self) -> None:
        url = "https://a.invalid/data.json"
        with self._opener():
            catalogue_cache.fetch_cached(url, self.tmp, "data.json")
            catalogue_cache.fetch_cached(url, self.tmp, "data.json", refresh=True)
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
        from core.access_policy import AccessPolicy
        from core.catalogue_types import RefreshMode

        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(allow_network=True, refresh=True, coordinator=coordinator)
        coordinator.snapshot.assert_called_once_with(
            mode=RefreshMode.FORCE,
            policy=AccessPolicy(allow_network=True, allow_metadata_writes=True),
        )
        coordinator.ensure.assert_not_called()
        coordinator.refresh.assert_not_called()

    def test_default_snapshot_does_not_force_refresh(self) -> None:
        from core.access_policy import AccessPolicy

        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(allow_network=True, refresh=False, coordinator=coordinator)
        coordinator.refresh.assert_not_called()
        coordinator.snapshot.assert_not_called()
        coordinator.ensure.assert_called_once_with(
            allow_network=True,
            policy=AccessPolicy(allow_network=True, allow_metadata_writes=True),
        )

    def test_offline_never_force_refreshes_even_when_asked(self) -> None:
        from core.access_policy import AccessPolicy

        coordinator = self._coordinator()
        catalogue._snapshot_and_payloads(allow_network=False, refresh=True, coordinator=coordinator)
        coordinator.refresh.assert_not_called()
        coordinator.snapshot.assert_not_called()
        coordinator.ensure.assert_called_once_with(
            allow_network=False,
            policy=AccessPolicy(allow_network=False, allow_metadata_writes=True),
        )

    def test_collect_entries_forwards_refresh(self) -> None:
        from unittest.mock import MagicMock, patch

        seen: dict = {}

        def spy(
            *,
            allow_network: bool,
            coordinator: Any = None,
            refresh: bool = False,
            policy: Any = None,
        ) -> Any:
            seen["refresh"] = refresh
            seen["allow_network"] = allow_network
            seen["policy"] = policy
            return MagicMock(), ({}, {}, {}, {})

        with (
            patch.object(catalogue, "_snapshot_and_payloads", spy),
            patch.object(catalogue, "_entries_from_snapshot", return_value=[]),
        ):
            catalogue.collect_entries(
                catalogue_types.CatalogueContext(),
                policy=catalogue_cache.FetchPolicy(refresh=True),
            )
        self.assertTrue(seen["refresh"])
        self.assertTrue(seen["allow_network"])
        self.assertTrue(seen["policy"].allow_cache_writes)

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
            policy: Any = None,
        ) -> Any:
            seen["refresh"] = refresh
            seen["policy"] = policy
            return mock.MagicMock(unsupported=None, report=None), ({}, {}, {}, {})

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.md")
            with (
                mock.patch.object(cli, "OUTPUT_PATH", out),
                mock.patch.object(
                    catalogue,
                    "_build_catalogue_context",
                    lambda **k: catalogue_types.CatalogueContext(),
                ),
                mock.patch.object(catalogue, "_snapshot_and_payloads", spy),
                mock.patch.object(
                    cli,
                    "_publication_verdict",
                    return_value=cli.PublicationVerdict(ok=True),
                ),
                contextlib.redirect_stdout(mock.MagicMock()),
            ):
                cli.main(["--refresh"])
        self.assertTrue(seen.get("refresh"))
        self.assertTrue(seen["policy"].allow_cache_writes)


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
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", self.tmp),
            mock.patch("core.mdx_config_fetch._urlopen", record),
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", lambda *a, **k: False),
        ]

    def _seed_cache(self) -> str:
        path = catalogue_cache._cache_path(self.tmp, self._URL, "model_test.yaml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self._YAML)
        return path

    def test_yaml_paths_includes_the_url_keyed_cache_entry(self) -> None:
        from unittest import mock

        runtime_path = os.path.join(self.tmp, "runtime-configs", "model_test.yaml")
        with mock.patch.object(
            core_paths,
            "MDX_C_CONFIG_PATH",
            os.path.dirname(runtime_path),
        ):
            candidates = catalogue_config_evidence._yaml_paths("model_test.yaml", self._URL)
        expected = catalogue_cache._cache_path(catalogue_locations.YAML_CACHE_DIR, self._URL, "model_test.yaml")
        self.assertIn(expected, candidates)
        self.assertNotIn(runtime_path, candidates)

    def test_offline_reads_a_previously_cached_yaml(self) -> None:
        """The whole point of a cache-only offline mode."""
        import contextlib

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            cached = self._seed_cache()
            self.assertTrue(os.path.isfile(cached))
            instruments, target, _arch, source, _digest = catalogue_config_evidence._load_yaml_meta(
                "model_test.yaml", self._URL, policy=catalogue_cache.OFFLINE_FETCH_POLICY
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
            catalogue_config_evidence._load_yaml_meta(
                "model_test.yaml", self._URL, policy=catalogue_cache.OFFLINE_FETCH_POLICY
            )
        self.assertEqual(self.calls, [])

    def test_unparseable_cached_yaml_is_not_strict_signature_evidence(self) -> None:
        import contextlib

        path = catalogue_cache._cache_path(self.tmp, self._URL, "model_test.yaml")
        with open(path, "wb") as handle:
            handle.write(b"training: [unterminated")
        ctx = catalogue_types.CatalogueContext()

        with contextlib.ExitStack() as stack:
            for patch in self._patches():
                stack.enter_context(patch)
            entry = catalogue._parse_catalogue_entry(
                source="fixture",
                family="Roformer",
                label="Roformer Model: Invalid YAML",
                payload={
                    "model.ckpt": "https://example.invalid/model.ckpt",
                    "model_test.yaml": self._URL,
                },
                ctx=ctx,
                policy=catalogue_cache.OFFLINE_FETCH_POLICY,
            )[0]

        self.assertEqual(entry.instruments, [])
        self.assertEqual(entry.target_instrument, "")
        self.assertTrue(entry.metadata_source.startswith("yaml_parse_failed:"))
        self.assertEqual(ctx.unavailable_yaml_evidence, {"model_test.yaml"})


class StrictCatalogueInputIsolationTests(unittest.TestCase):
    """Strict publication inputs must not depend on installed runtime models."""

    _YAML_NAME = "zz_runtime_conflict.yaml"
    _YAML_URL = "https://example.invalid/configs/zz_runtime_conflict.yaml"
    _WEIGHT_NAME = "zz_runtime_conflict.ckpt"
    _WEIGHT_URL = "https://example.invalid/models/zz_runtime_conflict.ckpt"
    _WARM_YAML = (
        b"training:\n"
        b"  instruments: [vocals, other]\n"
        b"  target_instrument: vocals\n"
        b"model:\n"
        b"  num_bands: 64\n"
    )
    _CONFLICTING_YAML = (
        b"training:\n"
        b"  instruments: [drums, bass]\n"
        b"  target_instrument: drums\n"
        b"model:\n"
        b"  band_specs: {}\n"
    )

    def setUp(self) -> None:
        import shutil
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="uvr-strict-inputs-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cache_root = os.path.join(self.tmp, "generator-cache")
        self.community_cache = os.path.join(self.cache_root, "community")
        self.yaml_cache = os.path.join(self.cache_root, "yaml")

    @staticmethod
    def _write(path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)

    def _seed_cache(self) -> None:
        rows = (
            (
                self.community_cache,
                catalogue._COMMUNITY_MODELS_URL,
                "models.txt",
                b"",
            ),
            (self.yaml_cache, self._YAML_URL, self._YAML_NAME, self._WARM_YAML),
        )
        for cache_dir, url, filename, data in rows:
            self._write(catalogue_cache._cache_path(cache_dir, url, filename), data)

    def _strict_projection(self, runtime_root: str) -> dict[str, object]:
        from dataclasses import asdict
        from unittest import mock

        runtime_configs = os.path.join(runtime_root, "configs")
        runtime_mdx_models = os.path.join(runtime_root, "mdx-models")
        runtime_vr_models = os.path.join(runtime_root, "vr-models")

        class _Snapshot:
            vr: dict[str, object] = {}
            mdx = {
                "Roformer Model: Strict Input Fixture": {
                    self._WEIGHT_NAME: self._WEIGHT_URL,
                    self._YAML_NAME: self._YAML_URL,
                }
            }
            demucs: dict[str, object] = {}
            apollo: dict[str, object] = {}
            meta: dict[str, object] = {}
            unsupported: dict[str, object] = {}
            report = None

        upstream = {
            "vr_download_list": {},
            "mdx_download_list": _Snapshot.mdx,
            "demucs_download_list": {},
        }
        from core.model_stem_manifest import BUNDLED_MANIFEST_PATH, load_stem_manifest

        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        with (
            mock.patch.object(catalogue_locations, "COMMUNITY_CACHE_DIR", self.community_cache),
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", self.yaml_cache),
            mock.patch.object(core_paths, "MDX_C_CONFIG_PATH", runtime_configs),
            mock.patch.object(
                core_paths,
                "MDX_HASH_JSON",
                os.path.join(runtime_root, "mdx-model-data.json"),
            ),
            mock.patch.object(
                core_paths,
                "VR_HASH_JSON",
                os.path.join(runtime_root, "vr-model-data.json"),
            ),
            mock.patch.object(core_paths, "MDX_MODELS_DIR", runtime_mdx_models),
            mock.patch.object(core_paths, "VR_MODELS_DIR", runtime_vr_models),
        ):
            ctx = catalogue._build_catalogue_context(policy=catalogue_cache.OFFLINE_FETCH_POLICY)
            entries = catalogue._entries_from_snapshot(
                _Snapshot(),
                (upstream, {}, {}, {}),
                ctx,
                policy=catalogue_cache.OFFLINE_FETCH_POLICY,
            )
            catalogue_evidence.reconcile_stem_semantics(entries, registry=registry)
            audit = cli.stem_audit.audit_catalogue_stems(
                entries,
                ctx,
                registry=registry,
            )
            catalogue_text = render._render(entries, unsupported_count=0, report=None)
            bundle = cli._render_publication_bundle(
                entries,
                ctx=ctx,
                unsupported=0,
                report=None,
                catalogue_text=catalogue_text,
                document_sha256=cli._text_digest(catalogue_text),
                audit=audit,
                manifest_audit=catalogue_audit_types.ManifestCandidateResult(
                    document={},
                    diagnostics=(),
                    current_model_ids=(),
                    retired_model_ids=(),
                    evidence_states={},
                ),
            )
        return {
            "entries": [asdict(entry) for entry in entries],
            "catalogue": bundle.catalogue,
            "intent_reference": bundle.intent_reference,
            "display_reference": asdict(bundle.display_reference),
            "stem_reference": bundle.stem_reference,
            "ir": cli._canonical_ir_for_diff(bundle.ir),
            "diagnostics": [asdict(diagnostic) for diagnostic in audit.diagnostics],
        }

    def test_warm_cache_is_identical_across_conflicting_runtime_data_dirs(self) -> None:
        """Installed same-name YAML/weights cannot alter strict output or diagnostics."""
        clean_runtime = os.path.join(self.tmp, "runtime-clean")
        conflicting_runtime = os.path.join(self.tmp, "runtime-conflicting")
        conflicting_weight = os.path.join(conflicting_runtime, "mdx-models", self._WEIGHT_NAME)
        self._write(conflicting_weight, b"runtime model bytes")
        self._seed_cache()
        self._write(
            os.path.join(conflicting_runtime, "configs", self._YAML_NAME),
            self._CONFLICTING_YAML,
        )
        before = {}
        for directory, _subdirs, names in os.walk(conflicting_runtime):
            for name in names:
                path = os.path.join(directory, name)
                with open(path, "rb") as handle:
                    before[os.path.relpath(path, conflicting_runtime)] = handle.read()

        clean = self._strict_projection(clean_runtime)
        conflicting = self._strict_projection(conflicting_runtime)

        self.assertEqual(clean, conflicting)
        after = {}
        for directory, _subdirs, names in os.walk(conflicting_runtime):
            for name in names:
                path = os.path.join(directory, name)
                with open(path, "rb") as handle:
                    after[os.path.relpath(path, conflicting_runtime)] = handle.read()
        self.assertEqual(before, after)

    def test_cold_offline_yaml_evidence_degrades_before_structural_audit(self) -> None:
        """A full membership snapshot without required YAML is unavailable, not invalid."""
        import contextlib
        import io
        from unittest import mock

        class _Snapshot:
            vr: dict[str, object] = {}
            mdx = {
                "Roformer Model: Cold YAML Fixture": {
                    self._WEIGHT_NAME: self._WEIGHT_URL,
                    self._YAML_NAME: self._YAML_URL,
                }
            }
            demucs: dict[str, object] = {}
            apollo: dict[str, object] = {}
            meta: dict[str, object] = {}
            unsupported: dict[str, object] = {}
            report = None

        upstream = {
            "vr_download_list": {},
            "mdx_download_list": _Snapshot.mdx,
            "demucs_download_list": {},
        }
        ctx = catalogue_types.CatalogueContext()
        stderr = io.StringIO()
        network_calls: list[str] = []
        invalid = StemAuditResult(
            catalogue_model_ids=("mdx:zz_runtime_conflict",),
            reviewed_model_ids=(),
            waived_model_ids=(),
            raw_model_ids=("mdx:zz_runtime_conflict",),
            evidence_counts=CatalogueEvidenceCounts(0, 0, 0, ()),
            diagnostics=(
                StemAuditDiagnostic(
                    code="catalogue-unreviewed",
                    model_ids=("mdx:zz_runtime_conflict",),
                    message="missing guessed signature would create structural spam",
                ),
            ),
        )

        def record_network(target: object) -> None:
            network_calls.append(str(target))
            return None

        with (
            mock.patch.object(cli, "OUTPUT_PATH", os.path.join(self.tmp, "cold.md")),
            mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(self.tmp, "cold.tsv")),
            mock.patch.object(
                cli,
                "DISPLAY_REFERENCE_TSV_PATH",
                os.path.join(self.tmp, "cold-display.tsv"),
            ),
            mock.patch.object(
                cli,
                "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                os.path.join(self.tmp, "cold-stems.tsv"),
            ),
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", os.path.join(self.tmp, "cold-yaml")),
            mock.patch.object(
                core_paths,
                "MDX_C_CONFIG_PATH",
                os.path.join(self.tmp, "cold-runtime-configs"),
            ),
            mock.patch.object(catalogue, "_build_catalogue_context", return_value=ctx),
            mock.patch.object(
                catalogue,
                "_snapshot_and_payloads",
                return_value=(_Snapshot(), (upstream, {}, {}, {})),
            ),
            mock.patch("core.mdx_config_fetch._urlopen", side_effect=record_network),
            mock.patch.object(
                cli.stem_audit,
                "audit_catalogue_stems",
                return_value=invalid,
            ) as audit,
            contextlib.redirect_stderr(stderr),
        ):
            rc = cli.main(["--offline"])

        self.assertEqual(rc, 2)
        self.assertEqual(network_calls, [])
        audit.assert_not_called()
        self.assertNotIn("Stem audit", stderr.getvalue())
        self.assertIn(self._YAML_NAME, ctx.unavailable_yaml_evidence)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "cold-yaml")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "cold-runtime-configs")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "cold.md")))

    def test_refresh_replaces_generator_yaml_without_writing_runtime_storage(self) -> None:
        """Refresh owns only its URL-keyed cache, never the model config store."""
        from unittest import mock

        fresh_yaml = (
            b"training:\n"
            b"  instruments: [vocals, other]\n"
            b"  target_instrument: other\n"
            b"model:\n"
            b"  num_bands: 64\n"
        )
        cache_path = catalogue_cache._cache_path(self.yaml_cache, self._YAML_URL, self._YAML_NAME)
        self._write(cache_path, self._CONFLICTING_YAML)
        runtime_path = os.path.join(self.tmp, "runtime-configs", self._YAML_NAME)
        self._write(runtime_path, self._CONFLICTING_YAML)

        class _Response:
            def read(self) -> bytes:
                return fresh_yaml

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        calls: list[object] = []

        def urlopen(target: object) -> _Response:
            calls.append(target)
            return _Response()

        policy = catalogue_cache.FetchPolicy(allow_network=True, refresh=True)
        with (
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", self.yaml_cache),
            mock.patch.object(
                core_paths,
                "MDX_C_CONFIG_PATH",
                os.path.dirname(runtime_path),
            ),
            mock.patch("core.mdx_config_fetch._urlopen", side_effect=urlopen),
        ):
            instruments, target, _arch, source, _digest = catalogue_config_evidence._load_yaml_meta(
                self._YAML_NAME,
                self._YAML_URL,
                policy=policy,
            )
            offline = catalogue_config_evidence._load_yaml_meta(
                self._YAML_NAME,
                self._YAML_URL,
                policy=catalogue_cache.OFFLINE_FETCH_POLICY,
            )

        self.assertEqual(instruments, ["vocals", "other"])
        self.assertEqual(target, "other")
        self.assertEqual(source, f"remote_yaml:{self._YAML_NAME}")
        self.assertEqual(offline[:2], (instruments, target))
        self.assertEqual(offline[3], source)
        self.assertEqual(len(calls), 1)
        with open(cache_path, "rb") as handle:
            self.assertEqual(handle.read(), fresh_yaml)
        with open(runtime_path, "rb") as handle:
            self.assertEqual(handle.read(), self._CONFLICTING_YAML)


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
            good = catalogue_cache.fetch_cached(url, tmp, "data.json")
            assert good is not None
            # Different bytes, so overwriting in place is distinguishable from
            # a staged write that never lands.
            body["data"] = b'{"ok": 2, "and": "much longer than the original"}'
            with mock.patch("os.replace", side_effect=OSError("disk full")):
                catalogue_cache.fetch_cached(url, tmp, "data.json", refresh=True)

        with open(good, "rb") as handle:
            self.assertEqual(handle.read(), b'{"ok": 1}')
        self.assertEqual(os.listdir(tmp), [os.path.basename(good)])


class YamlProvenanceStabilityTests(unittest.TestCase):
    """The metadata label must not flip between runs, or --check sees drift."""

    def test_a_downloaded_config_reports_the_same_source_on_the_next_run(self) -> None:
        import shutil
        import tempfile
        from unittest import mock

        cache_dir = tempfile.mkdtemp(prefix="uvr-generator-yaml-")
        self.addCleanup(shutil.rmtree, cache_dir, ignore_errors=True)
        url = "https://example.invalid/c/m.yaml"
        body = b"training:\n  instruments: [vocals, other]\n  target_instrument: other\n"

        class _Response:
            def read(self) -> bytes:
                return body

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with (
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", cache_dir),
            mock.patch("core.mdx_config_fetch._urlopen", return_value=_Response()) as fetch,
        ):
            first = catalogue_config_evidence._load_yaml_meta("m.yaml", url)[3]
            second = catalogue_config_evidence._load_yaml_meta("m.yaml", url)[3]

        self.assertEqual(first, second, "provenance label flipped between runs")
        self.assertEqual(first, "remote_yaml:m.yaml")
        self.assertEqual(fetch.call_count, 1)
