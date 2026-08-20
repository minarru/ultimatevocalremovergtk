import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, NO_MODEL, VR_ARCH_TYPE
from core.downloads import DownloadManager, vip_downloads
from core import paths
from core.catalog_sources import EntryMeta


def _stub_config_fetch(test: unittest.TestCase) -> None:
    """Stop job resolution from fetching a missing MDX-C config over the network.

    ``resolve_mdx_jobs`` calls ``ensure_mdx_c_config``, which downloads the YAML
    when it is absent locally. Tests only care about the job list, so pretend
    the config is unavailable — the same outcome as an offline machine.
    """
    for target in (
        "core.mdx_config_fetch.ensure_mdx_c_config",
        "core.downloads.ensure_mdx_c_config",
    ):
        patcher = patch(target, return_value=False)
        patcher.start()
        test.addCleanup(patcher.stop)


class DownloadManagerResolveTests(unittest.TestCase):
    def setUp(self):
        _stub_config_fetch(self)
        self.manager = DownloadManager()
        self.manager.vr_download_list = {"VR Test": "test_vr.pth"}
        self.manager.mdx_download_list = {"MDX Test": {"model.onnx": "config.yaml"}}
        self.manager.demucs_download_list = {
            "Demucs Test": {"checkpoint.th": "https://example.com/checkpoint.th"}
        }

    def test_catalogue_urls_collects_resolve_jobs(self):
        urls = self.manager.catalogue_urls()
        self.assertIn("https://example.com/checkpoint.th", urls)
        self.assertTrue(any(url.endswith("test_vr.pth") for url in urls))

    def test_resolve_vr_job(self):
        jobs = self.manager.resolve("VR Test", VR_ARCH_TYPE)
        self.assertEqual(len(jobs), 1)
        url, save_path = jobs[0]
        self.assertTrue(url.endswith("test_vr.pth"))
        self.assertEqual(save_path, os.path.join(paths.VR_MODELS_DIR, "test_vr.pth"))

    def test_resolve_mdx_job(self):
        jobs = self.manager.resolve("MDX Test", MDX_ARCH_TYPE)
        self.assertEqual(len(jobs), 1)
        _, save_path = jobs[0]
        self.assertTrue(save_path.endswith("model.onnx"))

    def test_resolve_demucs_multiple_files(self):
        self.manager.demucs_download_list["Demucs Test"]["meta.yaml"] = "https://example.com/meta.yaml"
        jobs = self.manager.resolve("Demucs Test", DEMUCS_ARCH_TYPE)
        self.assertEqual(len(jobs), 2)

    def test_resolve_empty_selection(self):
        self.assertEqual(self.manager.resolve(NO_MODEL, VR_ARCH_TYPE), [])

    def test_download_existing_file_does_not_raise(self):
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            result = self.manager.download(
                [("https://example.com/missing.onnx", path)],
            )
            self.assertEqual(result, "exists")
        finally:
            os.remove(path)

    def test_download_registers_paired_mdx_c_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hash_dir = os.path.join(tmp, "model_data")
            config_dir = os.path.join(hash_dir, "mdx_c_configs")
            models_dir = os.path.join(tmp, "models")
            os.makedirs(config_dir)
            os.makedirs(models_dir)

            checkpoint = os.path.join(models_dir, "download_model.ckpt")
            yaml_name = "config_musdb18_scnet.yaml"
            with open(checkpoint, "wb") as handle:
                handle.write(b"download registration checkpoint")
            shutil.copyfile(
                os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name), os.path.join(config_dir, yaml_name)
            )

            jobs = [
                ("https://example.com/download_model.ckpt", checkpoint),
                ("https://example.com/model.yaml", os.path.join(config_dir, yaml_name)),
            ]

            repo = Mock()
            original_hash_dir = paths.MDX_HASH_DIR
            original_config_dir = paths.MDX_C_CONFIG_PATH
            original_models_dir = paths.MDX_MODELS_DIR
            try:
                paths.MDX_HASH_DIR = hash_dir
                paths.MDX_C_CONFIG_PATH = config_dir
                paths.MDX_MODELS_DIR = models_dir
                result = self.manager.download(jobs, repo=repo)
            finally:
                paths.MDX_HASH_DIR = original_hash_dir
                paths.MDX_C_CONFIG_PATH = original_config_dir
                paths.MDX_MODELS_DIR = original_models_dir

            self.assertEqual(result, "exists")
            repo.invalidate_models.assert_called_once()


class DownloadManagerAvailabilityTests(unittest.TestCase):
    def test_installed_cross_source_alias_is_not_offered(self) -> None:
        retained_label = "SCnet: 4-stems Huge SCNet Strong Fullness by Aname"
        alias_label = "SCNet 4 Stems Huge Strong Fullness by Aname"
        retained_checkpoint = "huge_scnet_4stems_strong_fullness.ckpt"
        installed_checkpoint = "scnet_huge_4stem_str_fullness_aname.ckpt"

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            paths, "MDX_MODELS_DIR", tmp
        ):
            with open(os.path.join(tmp, installed_checkpoint), "wb") as handle:
                handle.write(b"installed alias")

            manager = DownloadManager()
            manager.mdx_download_list = {
                retained_label: {
                    retained_checkpoint: "https://curated/strong-fullness.ckpt"
                }
            }
            manager.catalogue_meta = {
                retained_label: EntryMeta(
                    label=retained_label,
                    display=retained_label,
                    arch=MDX_ARCH_TYPE,
                    checkpoint=retained_checkpoint,
                ),
                alias_label: EntryMeta(
                    label=alias_label,
                    display=alias_label,
                    arch=MDX_ARCH_TYPE,
                    checkpoint=installed_checkpoint,
                ),
            }

            available = manager.available_downloads(MDX_ARCH_TYPE)

        self.assertNotIn(retained_label, available[MDX_ARCH_TYPE])


class LegacyCatalogueSchemaTests(unittest.TestCase):
    def test_rebuild_accepts_bundled_mdx23_key(self) -> None:
        manager = DownloadManager()
        manager.online_data = {
            "mdx23_download_list": {
                "MDX23 Model: Legacy": {"legacy.ckpt": "legacy.yaml"}
            }
        }

        manager._rebuild_catalogues()

        self.assertIn("MDX23 Model: Legacy", manager.mdx_download_list)


class VipDownloadsTests(unittest.TestCase):
    def test_wrong_password_returns_no_code(self):
        from bundled.constants import NO_CODE

        self.assertEqual(vip_downloads("definitely-wrong-password"), NO_CODE)


class WarmSizeCacheTests(unittest.TestCase):
    """The warm marker must not latch while identity HEADs remain capped."""

    def _manager(self):
        from unittest import mock

        from core.downloads import DownloadManager

        manager = DownloadManager.__new__(DownloadManager)
        manager._size_warmup_lock = threading.Lock()
        manager._size_warmup_done_for = None
        manager.ensure_catalogues = mock.MagicMock(return_value=True)
        manager.catalogue_checkpoint_urls = mock.MagicMock(
            return_value=["https://example.test/a.ckpt"]
        )
        manager._reapply_content_dedupe = mock.MagicMock()
        return manager

    def test_capped_identity_pass_leaves_warmup_repeatable(self) -> None:
        from unittest import mock

        from core import downloads as downloads_mod

        manager = self._manager()
        with mock.patch.object(
            downloads_mod, "prefetch_remote_sizes", return_value={
                "total": 1, "fresh": 1, "fetched": 0, "failed": 0
            }
        ), mock.patch.object(
            downloads_mod,
            "prefetch_same_size_identity",
            return_value={"total": 64, "fetched": 0, "failed": 64, "skipped": 0, "capped": 10},
        ):
            manager.warm_size_cache()
        self.assertIsNone(
            manager._size_warmup_done_for,
            "latched while identity candidates remained, stranding them for the session",
        )

    def test_uncapped_identity_pass_marks_warm(self) -> None:
        from unittest import mock

        from core import downloads as downloads_mod

        manager = self._manager()
        with mock.patch.object(
            downloads_mod, "prefetch_remote_sizes", return_value={
                "total": 1, "fresh": 1, "fetched": 0, "failed": 0
            }
        ), mock.patch.object(
            downloads_mod,
            "prefetch_same_size_identity",
            return_value={"total": 2, "fetched": 2, "failed": 0, "skipped": 0, "capped": 0},
        ):
            manager.warm_size_cache()
        self.assertEqual(
            manager._size_warmup_done_for, frozenset({"https://example.test/a.ckpt"})
        )


class UpdateModelSettingsTests(unittest.TestCase):
    def test_name_mapper_keeps_local_only_keys(self) -> None:
        import io
        import json
        import tempfile
        from unittest import mock

        from core import downloads as downloads_mod
        from core.downloads import DownloadManager

        remote_mdx = {"a.ckpt": "Upstream A"}
        remote_demucs = {"d.th": "Upstream D"}
        remote_vr_hash = {"h1": {}}
        remote_mdx_hash = {"h2": {}}

        with tempfile.TemporaryDirectory() as tmp:
            mdx_mapper = os.path.join(tmp, "mdx_mapper.json")
            demucs_mapper = os.path.join(tmp, "demucs_mapper.json")
            vr_hash = os.path.join(tmp, "vr_hash.json")
            mdx_hash = os.path.join(tmp, "mdx_hash.json")
            with open(mdx_mapper, "w", encoding="utf-8") as handle:
                json.dump({"local_only.ckpt": "Local Only", "a.ckpt": "Old A"}, handle)

            # json.load uses the response as a file-like object
            class _FileResp:
                def __init__(self, data: dict) -> None:
                    self._buf = io.StringIO(json.dumps(data))

                def __enter__(self) -> io.StringIO:
                    return self._buf

                def __exit__(self, *args: object) -> None:
                    return None

            side = [
                _FileResp(remote_vr_hash),
                _FileResp(remote_mdx_hash),
                _FileResp(remote_mdx),
                _FileResp(remote_demucs),
            ]

            with mock.patch.object(
                downloads_mod,
                "_MODEL_DATA_URLS",
                [
                    ("https://x/vr", vr_hash),
                    ("https://x/mdx_hash", mdx_hash),
                    ("https://x/mdx_name", mdx_mapper),
                    ("https://x/demucs_name", demucs_mapper),
                ],
            ), mock.patch.object(
                downloads_mod,
                "_NAME_MAPPER_DESTS",
                frozenset({mdx_mapper, demucs_mapper}),
            ), mock.patch.object(downloads_mod, "_urlopen", side_effect=side):
                ok = DownloadManager().update_model_settings()
            self.assertTrue(ok)
            from core.name_mapper import load_name_mapper

            # The mirror now tracks upstream exactly; the fork key was migrated
            # into the sibling overlay and comes back through the merged read.
            with open(mdx_mapper, encoding="utf-8") as handle:
                mirror = json.load(handle)
            self.assertEqual(mirror, remote_mdx)

            merged = load_name_mapper(mdx_mapper)
            self.assertEqual(merged["local_only.ckpt"], "Local Only")
            self.assertEqual(merged["a.ckpt"], "Upstream A")

    def test_identical_payload_skips_invalidate(self) -> None:
        import io
        import json
        import tempfile
        from unittest import mock

        from core import downloads as downloads_mod
        from core.downloads import DownloadManager

        data = {"a.ckpt": "A"}
        with tempfile.TemporaryDirectory() as tmp:
            dests = [
                os.path.join(tmp, name)
                for name in ("vr.json", "mdx_hash.json", "mdx_name.json", "demucs.json")
            ]
            for dest in dests:
                with open(dest, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)

            class _FileResp:
                def __init__(self, payload: dict) -> None:
                    self._buf = io.StringIO(json.dumps(payload))

                def __enter__(self) -> io.StringIO:
                    return self._buf

                def __exit__(self, *args: object) -> None:
                    return None

            side = [_FileResp(data) for _ in dests]
            repo = mock.Mock()
            with mock.patch.object(
                downloads_mod,
                "_MODEL_DATA_URLS",
                [(f"https://x/{i}", dest) for i, dest in enumerate(dests)],
            ), mock.patch.object(
                downloads_mod,
                "_NAME_MAPPER_DESTS",
                frozenset(dests[2:]),
            ), mock.patch.object(downloads_mod, "_urlopen", side_effect=side):
                ok = DownloadManager().update_model_settings(repo)
            self.assertTrue(ok)
            repo.invalidate_models.assert_not_called()

    def test_update_model_settings_reloads_the_hash_mappers(self):
        """Rewriting the hash map on disk must reach `repo.mdx_hash_MAPPER`.

        `update_model_settings` called `invalidate_stem_check()` only, so the
        freshly downloaded mapper data sat on disk while the in-memory mappers
        stayed stale for the rest of the session.
        """
        import io
        import json
        import tempfile
        from unittest import mock

        from core import downloads as downloads_mod
        from core import paths
        from core.downloads import DownloadManager
        from core.model_repository import ModelRepository

        payload = {"fresh-md5": {"primary_stem": "Vocals"}}
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["UVR_DATA_DIR"] = tmp
            self.addCleanup(lambda: os.environ.pop("UVR_DATA_DIR", None))
            mdx_hash_json = os.path.join(tmp, "mdx_model_data.json")
            with open(mdx_hash_json, "w", encoding="utf-8") as handle:
                json.dump({}, handle)

            class _FileResp:
                def __init__(self, data: dict) -> None:
                    self._buf = io.StringIO(json.dumps(data))

                def __enter__(self) -> io.StringIO:
                    return self._buf

                def __exit__(self, *args: object) -> None:
                    return None

            with mock.patch.object(paths, "MDX_HASH_JSON", mdx_hash_json):
                repo = ModelRepository()
                self.assertNotIn("fresh-md5", repo.mdx_hash_MAPPER)
                with mock.patch.object(
                    downloads_mod,
                    "_MODEL_DATA_URLS",
                    [("https://x/mdx", mdx_hash_json)],
                ), mock.patch.object(
                    downloads_mod, "_NAME_MAPPER_DESTS", frozenset()
                ), mock.patch.object(
                    downloads_mod, "_urlopen", side_effect=[_FileResp(payload)]
                ):
                    ok = DownloadManager().update_model_settings(repo)

            self.assertTrue(ok)
            self.assertIn("fresh-md5", repo.mdx_hash_MAPPER)


class CatalogueChangedSubscriberTests(unittest.TestCase):
    """`_reapply_content_dedupe` must tell listeners when rows disappear.

    The identity HEAD pass finishes long after the Download Center has rendered,
    so a rehosted duplicate stays on screen unless the drop is announced.
    """

    def _manager(self) -> DownloadManager:
        manager = DownloadManager()
        manager.vr_download_list = {}
        manager.demucs_download_list = {}
        manager.apollo_download_list = {}
        # Same bytes rehosted under a different name/label/URL: only the shared
        # content id can collapse these two.
        manager.mdx_download_list = {
            "Kept Model": {"kept.ckpt": "https://example.test/kept.ckpt"},
            "Rehosted Copy": {"rehosted.ckpt": "https://mirror.test/rehosted.ckpt"},
        }
        return manager

    def test_notifies_subscribers_when_dedupe_drops_a_row(self):
        manager = self._manager()
        calls = []
        manager.subscribe_catalogue_changed(lambda: calls.append(1))

        with patch(
            "core.downloads.content_ids_from_cache",
            return_value={
                "https://example.test/kept.ckpt": "etag-abc",
                "https://mirror.test/rehosted.ckpt": "etag-abc",
            },
        ):
            manager._reapply_content_dedupe()

        self.assertEqual(list(manager.mdx_download_list), ["Kept Model"])
        self.assertEqual(len(calls), 1)

    def test_silent_when_nothing_is_dropped(self):
        """The warm path is the common one — it must cost no re-render."""
        manager = self._manager()
        calls = []
        manager.subscribe_catalogue_changed(lambda: calls.append(1))

        with patch(
            "core.downloads.content_ids_from_cache",
            return_value={
                "https://example.test/kept.ckpt": "etag-abc",
                "https://mirror.test/rehosted.ckpt": "etag-xyz",
            },
        ):
            manager._reapply_content_dedupe()

        self.assertEqual(len(manager.mdx_download_list), 2)
        self.assertEqual(calls, [])

    def test_unsubscribe_stops_delivery(self):
        manager = self._manager()
        calls = []

        def listener() -> None:
            calls.append(1)

        manager.subscribe_catalogue_changed(listener)
        manager.unsubscribe_catalogue_changed(listener)

        with patch(
            "core.downloads.content_ids_from_cache",
            return_value={
                "https://example.test/kept.ckpt": "etag-abc",
                "https://mirror.test/rehosted.ckpt": "etag-abc",
            },
        ):
            manager._reapply_content_dedupe()

        self.assertEqual(calls, [])

    def test_dropping_rows_invalidates_the_display_merge(self):
        """The merged catalogue is memoized; dedupe has to bump its generation.

        `merged_catalogues` keys on the caller's label set and the display
        generation -- not on the content-id map it dedupes with. On a fresh
        install the display index is built before the identity HEADs have filled
        any etags, so when they arrive the inputs are unchanged and the cached
        pre-dedupe row set is reused for the rest of the session.
        """
        from core import model_display

        manager = self._manager()
        generation_before = model_display._display_generation

        with patch(
            "core.downloads.content_ids_from_cache",
            return_value={
                "https://example.test/kept.ckpt": "etag-abc",
                "https://mirror.test/rehosted.ckpt": "etag-abc",
            },
        ):
            manager._reapply_content_dedupe()

        self.assertGreater(model_display._display_generation, generation_before)

    def test_no_drop_leaves_the_display_merge_alone(self):
        """Re-merging costs ~125ms; don't pay it when nothing changed."""
        from core import model_display

        manager = self._manager()
        generation_before = model_display._display_generation

        with patch(
            "core.downloads.content_ids_from_cache",
            return_value={
                "https://example.test/kept.ckpt": "etag-abc",
                "https://mirror.test/rehosted.ckpt": "etag-xyz",
            },
        ):
            manager._reapply_content_dedupe()

        self.assertEqual(model_display._display_generation, generation_before)

    def test_failing_subscriber_does_not_break_the_warmup_thread(self):
        manager = self._manager()
        calls = []

        def boom() -> None:
            raise RuntimeError("subscriber blew up")

        manager.subscribe_catalogue_changed(boom)
        manager.subscribe_catalogue_changed(lambda: calls.append(1))

        with patch(
            "core.downloads.content_ids_from_cache",
            return_value={
                "https://example.test/kept.ckpt": "etag-abc",
                "https://mirror.test/rehosted.ckpt": "etag-abc",
            },
        ):
            manager._reapply_content_dedupe()

        self.assertEqual(len(calls), 1)


class DownloadManagerSwrFreshnessTests(unittest.TestCase):
    """SWR completion must refresh manager lists without ``refresh()`` (bulletin HTTP)."""

    def test_ensure_catalogues_applies_swr_update(self) -> None:
        from core.access_policy import AccessPolicy
        from core.catalogue_coordinator import CatalogueCoordinator
        from core.catalogue_types import RefreshMode, SourceId
        from core.remote_catalog_cache import RemoteJsonSource
        from tests.test_catalogue_coordinator import (
            _Clock,
            _disabled,
            _gated_opener,
            _wait_until,
            _write_envelope,
        )

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
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: RemoteJsonSource(
                    source_id=SourceId.UPSTREAM,
                    url="https://example.test/upstream.json",
                    cache_filename="upstream.json",
                    cache_path=path,
                    ttl_seconds=60,
                    opener=opener,
                    clock=clock,
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: _disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        manager = DownloadManager(coordinator)
        self.assertTrue(manager.ensure_catalogues(allow_network=True))
        self.assertIn("Old", manager.mdx_download_list)
        self.assertNotIn("New", manager.mdx_download_list)
        self.assertTrue(fetched.wait(timeout=2))
        release.set()
        self.assertTrue(
            _wait_until(
                lambda: coordinator._latest is not None
                and "New" in coordinator._latest.mdx
            )
        )
        self.assertTrue(
            _wait_until(lambda: "New" in manager.mdx_download_list),
            "manager lists must pick up the SWR snapshot without calling refresh()",
        )
        self.assertNotIn("Old", manager.mdx_download_list)
        self.assertIn("New", coordinator.snapshot(
            vip=False,
            mode=RefreshMode.OFFLINE,
            policy=AccessPolicy(allow_network=False, allow_metadata_writes=False),
        ).mdx)
        self.assertTrue(manager.ensure_catalogues(allow_network=True))


if __name__ == "__main__":
    unittest.main()
