"""Generator check contract behavior."""

import json
import os
import unittest
import urllib.error

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as fixtures

import generate_models_catalogue as cli
from catalogue import cache as catalogue_cache
from catalogue import collect as catalogue
from catalogue import config_evidence as catalogue_config_evidence
from catalogue import locations as catalogue_locations
from catalogue import types as catalogue_types

from core import paths as core_paths
from core.catalogue_types import SourceId




# isort: on

class CheckContractTests(unittest.TestCase):
    """--check must be genuinely read-only and must not lie about coverage."""

    def _assert_default_online_swr_is_read_only(
        self, *, argv: list[str], stale_source: bool
    ) -> None:
        import contextlib
        import io
        import shutil
        import tempfile
        import threading
        from unittest import mock

        from core import catalogue_stem_cache, download_sizes, paths
        from core.catalogue_coordinator import CatalogueCoordinator
        from core.remote_catalog_cache import RemoteJsonSource

        tmp = tempfile.mkdtemp(prefix="uvr-online-swr-readonly-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache_root = os.path.join(tmp, "cache")
        supplemental_cache = os.path.join(cache_root, "supplemental")
        community_cache = os.path.join(cache_root, "community")
        yaml_cache = os.path.join(cache_root, "yaml")
        source_cache = os.path.join(cache_root, "sources", "upstream.json")
        stem_cache = os.path.join(cache_root, "derived-stems", "stems.json")
        size_cache = os.path.join(cache_root, "derived-sizes", "sizes.json")
        model_store = os.path.join(tmp, "model-store")
        legacy_data = os.path.join(tmp, "legacy-data")
        legacy_base = os.path.join(tmp, "legacy-base")
        legacy_size = os.path.join(legacy_data, "download_size_cache.json")
        out = os.path.join(tmp, "models-catalogue.md")
        intent_ref = os.path.join(tmp, "model_intent_reference.tsv")
        display_ref = os.path.join(tmp, "model_display_reference.tsv")
        sidecar = catalogue._ir_path_for(out)

        os.makedirs(legacy_data)
        legacy_size_bytes = b'{"legacy": true}\n'
        with open(legacy_size, "wb") as handle:
            handle.write(legacy_size_bytes)

        old_payload = {
            "vr_download_list": {},
            "mdx_download_list": {
                "MDX23C Model: Old": {"old.ckpt": "https://example.invalid/old.ckpt"}
            },
            "demucs_download_list": {},
        }
        source_bytes: bytes | None = None
        if stale_source:
            os.makedirs(os.path.dirname(source_cache))
            source_bytes = json.dumps({"fetched_at": 1.0, "data": old_payload}).encode("utf-8")
            with open(source_cache, "wb") as handle:
                handle.write(source_bytes)

        sentinels = {
            out: b"catalogue sentinel\n",
            intent_ref: b"intent sentinel\n",
            display_ref: b"display sentinel\n",
            sidecar: b'{"sidecar": "sentinel"}\n',
        }
        for path, data in sentinels.items():
            with open(path, "wb") as handle:
                handle.write(data)

        class _Response:
            status = 200
            headers: dict = {}

            def __init__(self, data: bytes) -> None:
                self.data = data

            def read(self, *_args: object) -> bytes:
                return self.data

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        fresh_payload = {
            "vr_download_list": {},
            "mdx_download_list": {
                "MDX23C Model: Fresh Async": {
                    "fresh.ckpt": "https://example.invalid/fresh.ckpt",
                    "fresh.yaml": "https://example.invalid/fresh.yaml",
                }
            },
            "demucs_download_list": {},
        }
        source_started = threading.Event()
        release_source = threading.Event()

        def source_open(_target: object) -> _Response:
            source_started.set()
            release_source.wait(timeout=2)
            return _Response(json.dumps(fresh_payload).encode("utf-8"))

        def supplemental_open(target: object) -> _Response:
            url = str(getattr(target, "full_url", target))
            if url == catalogue._COMMUNITY_MODELS_URL:
                return _Response(b"")
            raise AssertionError(f"unexpected fetch: {url}")

        source = RemoteJsonSource(
            source_id=SourceId.UPSTREAM,
            url="https://example.invalid/upstream.json",
            cache_filename="upstream.json",
            cache_path=source_cache,
            ttl_seconds=60,
            opener=source_open,
        )
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: source,
                SourceId.POLITREES: fixtures._disabled(SourceId.POLITREES),
                SourceId.EXTRAS: fixtures._disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: fixtures._disabled(SourceId.MVSEPLESS),
            }
        )
        real_close = coordinator.close

        def wait_for_refresh_then_close() -> None:
            self.assertTrue(source_started.wait(timeout=2), "SWR fetch did not start")
            release_source.set()
            with source._lock:
                flight = source._flight
            self.assertIsNotNone(flight, "SWR worker was not registered")
            assert flight is not None
            self.assertTrue(flight.wait(timeout=2), "SWR publish did not finish")
            real_close()

        coordinator.close = wait_for_refresh_then_close  # type: ignore[method-assign]
        self.addCleanup(real_close)
        self.addCleanup(release_source.set)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(fixtures._legacy_publication_manifest_fixture())
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", out))
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", intent_ref))
            stack.enter_context(mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", display_ref))
            stack.enter_context(
                mock.patch.object(catalogue, "CatalogueCoordinator", lambda: coordinator)
            )
            stack.enter_context(
                mock.patch.object(catalogue_locations, "COMMUNITY_CACHE_DIR", community_cache)
            )
            stack.enter_context(mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", yaml_cache))
            stack.enter_context(mock.patch.object(paths, "DATA_DIR", legacy_data))
            stack.enter_context(mock.patch.object(paths, "BASE_PATH", legacy_base))
            stack.enter_context(mock.patch.object(paths, "MDX_C_CONFIG_PATH", model_store))
            stack.enter_context(mock.patch.object(paths, "CATALOGUE_STEM_CACHE_FILE", stem_cache))
            stack.enter_context(mock.patch.object(paths, "DOWNLOAD_SIZE_CACHE_FILE", size_cache))
            stack.enter_context(mock.patch.object(catalogue_stem_cache, "_memory_entries", None))
            stack.enter_context(mock.patch.object(download_sizes, "_memory_payload", None))
            stack.enter_context(mock.patch.object(download_sizes, "_memory_path", None))
            stack.enter_context(mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": ""}))
            stack.enter_context(mock.patch("core.mdx_config_fetch._urlopen", supplemental_open))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(argv)

        self.assertEqual(rc, 1, stderr.getvalue())
        latest = coordinator._latest
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertIn("MDX23C Model: Fresh Async", latest.mdx)
        if source_bytes is None:
            self.assertFalse(os.path.exists(os.path.dirname(source_cache)))
        else:
            with open(source_cache, "rb") as handle:
                self.assertEqual(handle.read(), source_bytes)
        self.assertTrue(
            os.path.isfile(legacy_size),
            "SWR publication migrated the legacy download-size cache",
        )
        with open(legacy_size, "rb") as handle:
            self.assertEqual(handle.read(), legacy_size_bytes)
        self.assertFalse(os.path.exists(os.path.dirname(size_cache)))
        self.assertFalse(os.path.exists(os.path.dirname(stem_cache)))
        self.assertFalse(os.path.exists(supplemental_cache))
        self.assertFalse(os.path.exists(community_cache))
        self.assertFalse(os.path.exists(yaml_cache))
        self.assertFalse(os.path.exists(model_store))
        for path, data in sentinels.items():
            with self.subTest(path=path):
                with open(path, "rb") as handle:
                    self.assertEqual(handle.read(), data)

    def test_default_online_check_swr_publish_keeps_every_cache_and_artifact_read_only(
        self,
    ) -> None:
        self._assert_default_online_swr_is_read_only(
            argv=["--check", "--write-display-reference"], stale_source=True
        )

    def test_default_online_summary_swr_publish_keeps_every_cache_and_artifact_read_only(
        self,
    ) -> None:
        self._assert_default_online_swr_is_read_only(argv=["--summary"], stale_source=False)

    def test_online_check_fetches_in_memory_without_mutating_any_cache_or_artifact(
        self,
    ) -> None:
        import contextlib
        import io
        import shutil
        import tempfile
        from unittest import mock

        from core.catalogue_coordinator import CatalogueCoordinator
        from core.remote_catalog_cache import RemoteJsonSource

        tmp = tempfile.mkdtemp(prefix="uvr-online-check-readonly-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache_root = os.path.join(tmp, "cache")
        supplemental_cache = os.path.join(cache_root, "supplemental")
        community_cache = os.path.join(cache_root, "community")
        yaml_cache = os.path.join(cache_root, "yaml")
        source_cache = os.path.join(cache_root, "sources", "upstream.json")
        stem_cache = os.path.join(cache_root, "derived", "stems.json")
        size_cache = os.path.join(cache_root, "identity", "sizes.json")
        model_store = os.path.join(tmp, "model-store")
        out = os.path.join(tmp, "models-catalogue.md")
        intent_ref = os.path.join(tmp, "model_intent_reference.tsv")
        display_ref = os.path.join(tmp, "model_display_reference.tsv")
        sidecar = catalogue._ir_path_for(out)

        os.makedirs(community_cache)
        stale_path = catalogue_cache._cache_path(
            community_cache,
            catalogue._COMMUNITY_MODELS_URL,
            "models.txt",
        )
        with open(stale_path, "wb") as handle:
            handle.write(b'{"stale": true}')
        os.utime(stale_path, (1, 1))

        sentinels = {
            out: b"catalogue sentinel\n",
            intent_ref: b"intent sentinel\n",
            display_ref: b"display sentinel\n",
            sidecar: b'{"sidecar": "sentinel"}\n',
        }
        for path, data in sentinels.items():
            with open(path, "wb") as handle:
                handle.write(data)

        class _Response:
            status = 200
            headers: dict = {}

            def __init__(self, data: bytes) -> None:
                self.data = data

            def read(self, *_args: object) -> bytes:
                return self.data

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        upstream_payload = {
            "vr_download_list": {"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"},
            "mdx_download_list": {
                "MDX23C Model: Fresh": {
                    "fresh.ckpt": "https://example.invalid/fresh.ckpt",
                    "fresh.yaml": "https://example.invalid/fresh.yaml",
                }
            },
            "demucs_download_list": {},
        }
        source_calls: list[str] = []

        def source_open(target: object) -> _Response:
            source_calls.append(str(getattr(target, "full_url", target)))
            return _Response(json.dumps(upstream_payload).encode("utf-8"))

        supplement_calls: list[str] = []

        def supplemental_open(target: object) -> _Response:
            url = str(getattr(target, "full_url", target))
            supplement_calls.append(url)
            if url == catalogue._COMMUNITY_MODELS_URL:
                return _Response(b"")
            if url == "https://example.invalid/fresh.yaml":
                return _Response(
                    b"training:\n  instruments: [vocals, other]\n  target_instrument: other\n"
                )
            raise AssertionError(f"unexpected fetch: {url}")

        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: RemoteJsonSource(
                    source_id=SourceId.UPSTREAM,
                    url="https://example.invalid/upstream.json",
                    cache_path=source_cache,
                    opener=source_open,
                ),
                SourceId.POLITREES: fixtures._disabled(SourceId.POLITREES),
                SourceId.EXTRAS: fixtures._disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: fixtures._disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)

        stderr = io.StringIO()
        from core import catalogue_stem_cache, download_sizes

        with contextlib.ExitStack() as stack:
            stack.enter_context(fixtures._legacy_publication_manifest_fixture())
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", out))
            stack.enter_context(mock.patch.object(cli, "REFERENCE_TSV_PATH", intent_ref))
            stack.enter_context(mock.patch.object(cli, "DISPLAY_REFERENCE_TSV_PATH", display_ref))
            stack.enter_context(
                mock.patch.object(catalogue, "CatalogueCoordinator", lambda: coordinator)
            )
            stack.enter_context(
                mock.patch.object(catalogue_locations, "COMMUNITY_CACHE_DIR", community_cache)
            )
            stack.enter_context(mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", yaml_cache))
            stack.enter_context(
                mock.patch.object(core_paths, "MDX_C_CONFIG_PATH", model_store)
            )
            stack.enter_context(
                mock.patch.object(core_paths, "CATALOGUE_STEM_CACHE_FILE", stem_cache)
            )
            stack.enter_context(
                mock.patch.object(core_paths, "DOWNLOAD_SIZE_CACHE_FILE", size_cache)
            )
            stack.enter_context(mock.patch.object(catalogue_stem_cache, "_memory_entries", None))
            stack.enter_context(mock.patch.object(download_sizes, "_memory_payload", None))
            stack.enter_context(mock.patch.object(download_sizes, "_memory_path", None))
            stack.enter_context(mock.patch.dict(os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": ""}))
            stack.enter_context(mock.patch("core.mdx_config_fetch._urlopen", supplemental_open))
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=fixtures._clean_stem_audit
                )
            )
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(["--check", "--refresh", "--write-display-reference"])

        self.assertEqual(rc, 1, stderr.getvalue())
        self.assertTrue(source_calls, "coordinator network data was not compared")
        self.assertEqual(
            set(supplement_calls),
            {
                catalogue._COMMUNITY_MODELS_URL,
                "https://example.invalid/fresh.yaml",
            },
        )
        self.assertIn("Out of date", stderr.getvalue())
        with open(stale_path, "rb") as handle:
            self.assertEqual(handle.read(), b'{"stale": true}')
        for path, data in sentinels.items():
            with self.subTest(path=path):
                with open(path, "rb") as handle:
                    self.assertEqual(handle.read(), data)
        self.assertFalse(os.path.exists(supplemental_cache))
        self.assertEqual(os.listdir(community_cache), [os.path.basename(stale_path)])
        self.assertFalse(os.path.exists(yaml_cache))
        self.assertFalse(os.path.exists(os.path.dirname(source_cache)))
        self.assertFalse(os.path.exists(os.path.dirname(stem_cache)))
        self.assertFalse(os.path.exists(os.path.dirname(size_cache)))
        self.assertFalse(os.path.exists(model_store))

    def test_check_forbids_metadata_writes(self) -> None:
        """fetch_mdx_config_url writes yaml into the repo in the dev layout."""
        policy = cli._policy_for(cli._parse_args(["--check"]))
        self.assertFalse(policy.allow_metadata_writes)
        self.assertFalse(policy.allow_cache_writes)

    def test_a_normal_run_still_allows_metadata_writes(self) -> None:
        policy = cli._policy_for(cli._parse_args([]))
        self.assertTrue(policy.allow_metadata_writes)
        self.assertTrue(policy.allow_cache_writes)

    def test_load_yaml_meta_does_not_fetch_configs_when_writes_are_denied(self) -> None:
        from unittest import mock

        called = []

        def spy(name: str, url: str) -> bool:
            called.append(name)
            return False

        policy = catalogue_cache.FetchPolicy(allow_network=True, allow_metadata_writes=False)
        with (
            mock.patch("core.mdx_config_fetch.fetch_mdx_config_url", spy),
            mock.patch(
                "core.mdx_config_fetch._urlopen",
                side_effect=urllib.error.URLError("blocked"),
            ),
        ):
            catalogue_config_evidence._load_yaml_meta(
                "nope.yaml", "https://example.invalid/nope.yaml", policy=policy
            )
        self.assertEqual(called, [], "--check wrote a config into the model store")

    def test_read_only_online_yaml_fetch_is_parsed_without_creating_a_cache(self) -> None:
        import shutil
        import tempfile
        from unittest import mock

        tmp = tempfile.mkdtemp(prefix="uvr-yaml-readonly-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        cache_dir = os.path.join(tmp, "yaml-cache")
        model_store = os.path.join(tmp, "model-store")
        body = (
            b"training:\n"
            b"  instruments: [vocals, other]\n"
            b"  target_instrument: other\n"
            b"model:\n"
            b"  num_bands: 64\n"
        )

        class _Response:
            def read(self, *_args: object) -> bytes:
                return body

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        policy = catalogue_cache.FetchPolicy(
            allow_network=True,
            allow_metadata_writes=False,
            allow_cache_writes=False,
        )
        with (
            mock.patch.object(catalogue_locations, "YAML_CACHE_DIR", cache_dir),
            mock.patch.object(core_paths, "MDX_C_CONFIG_PATH", model_store),
            mock.patch(
                "core.mdx_config_fetch.fetch_mdx_config_url",
                side_effect=AssertionError("model-store write path used"),
            ),
            mock.patch("core.mdx_config_fetch._urlopen", return_value=_Response()),
        ):
            instruments, target, arch, source, _digest = catalogue_config_evidence._load_yaml_meta(
                "fresh.yaml",
                "https://example.invalid/fresh.yaml",
                policy=policy,
            )

        self.assertEqual(instruments, ["vocals", "other"])
        self.assertEqual(target, "other")
        self.assertEqual(arch, "Mel-Band Roformer")
        self.assertEqual(source, "remote_yaml:fresh.yaml")
        self.assertFalse(os.path.exists(cache_dir))
        self.assertFalse(os.path.exists(model_store))

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
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue_types.CatalogueContext()
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                )
            )
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(["--check"])

        self.assertEqual(rc, 2)
        message = stderr.getvalue()
        self.assertNotIn("Refusing to write", message)
        self.assertIn("cannot judge", message.lower())

    def test_legacy_tsv_flag_writes_the_empty_but_available_reference(self) -> None:
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
            stack.enter_context(fixtures._legacy_publication_manifest_fixture())
            stack.enter_context(mock.patch.object(cli, "OUTPUT_PATH", os.path.join(tmp, "c.md")))
            stack.enter_context(
                mock.patch.object(cli, "REFERENCE_TSV_PATH", os.path.join(tmp, "r.tsv"))
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "DISPLAY_REFERENCE_TSV_PATH",
                    os.path.join(tmp, "display.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli,
                    "STEM_SEMANTICS_REFERENCE_TSV_PATH",
                    os.path.join(tmp, "stem.tsv"),
                )
            )
            stack.enter_context(
                mock.patch.object(
                    cli.stem_audit, "audit_catalogue_stems", side_effect=fixtures._clean_stem_audit
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_build_catalogue_context", lambda **k: catalogue_types.CatalogueContext()
                )
            )
            stack.enter_context(
                mock.patch.object(
                    catalogue, "_snapshot_and_payloads", lambda **k: (_Snapshot(), ({}, {}, {}, {}))
                )
            )
            stack.enter_context(contextlib.redirect_stderr(stderr))
            rc = cli.main(["--write-tsv"])

        self.assertEqual(rc, 0)
        self.assertIn("deprecated", stderr.getvalue().lower())
