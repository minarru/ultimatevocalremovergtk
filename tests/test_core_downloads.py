import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, NO_MODEL, VR_ARCH_TYPE
from core.downloads import DownloadManager
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

    def test_download_is_transfer_only(self) -> None:
        """`download` transfers files and nothing else.

        Registration and publication moved to
        `core.model_install.finalize_downloaded_model`, which owns them for one
        logical model. The paired MDX-C registration this used to assert now
        lives in `tests/test_model_install.py`.
        """
        import inspect
        from unittest.mock import patch as _patch

        from core.downloads import DownloadManager

        # No repository is accepted, so no publication decision can be made here.
        self.assertNotIn(
            "repo", inspect.signature(DownloadManager.download).parameters
        )

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = os.path.join(tmp, "already_there.ckpt")
            with open(checkpoint, "wb") as handle:
                handle.write(b"present")
            jobs = [("https://example.com/already_there.ckpt", checkpoint)]

            with _patch(
                "core.mdx_c_registry.register_mdx_c_from_download_jobs"
            ) as mdx_c, _patch(
                "core.apollo_registry.register_apollo_from_download_jobs"
            ) as apollo:
                result = self.manager.download(jobs)

            self.assertEqual(result, "exists")
            mdx_c.assert_not_called()
            apollo.assert_not_called()


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


class AdditionalPublicRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = DownloadManager()

    def test_former_vip_vr_model_uses_additional_public_repo(self) -> None:
        label = "VR Arch Single Model VIP: Added"
        self.manager.vr_download_list = {label: "added.pth"}
        jobs = self.manager.resolve(label, VR_ARCH_TYPE)
        self.assertEqual(
            jobs[0][0],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/added.pth",
        )

    def test_former_vip_mdx_model_uses_additional_public_repo(self) -> None:
        label = "MDX-Net Model VIP: UVR-MDX-NET_Main_427"
        self.manager.mdx_download_list = {
            label: "UVR-MDX-NET_Main_427.onnx"
        }
        jobs = self.manager.resolve(label, MDX_ARCH_TYPE, fetch_config=False)
        self.assertEqual(
            jobs[0][0],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/"
            "UVR-MDX-NET_Main_427.onnx",
        )

    def test_former_vip_mdx_c_checkpoint_uses_additional_public_repo(self) -> None:
        label = "MDX23C Model VIP: MDX23C_D1581"
        self.manager.mdx_download_list = {
            label: {"MDX23C_D1581.ckpt": "model_2_stem_061321.yaml"}
        }
        jobs = self.manager.resolve(label, MDX_ARCH_TYPE, fetch_config=False)
        self.assertEqual(
            jobs[0][0],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/"
            "MDX23C_D1581.ckpt",
        )


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
    def test_overlay_plan_and_commit_serialize_real_local_writer(self) -> None:
        import io
        import json
        import tempfile
        from unittest import mock

        from core import downloads as downloads_mod
        from core import name_mapper
        from core.downloads import DownloadManager

        remote = {"upstream.ckpt": "Fresh upstream"}
        with tempfile.TemporaryDirectory() as tmp:
            mapper = os.path.join(tmp, "mdx_mapper.json")
            overlay = name_mapper.local_overlay_path(mapper)
            with open(mapper, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "legacy.ckpt": "Legacy evidence",
                        "upstream.ckpt": "Old upstream",
                    },
                    handle,
                )

            class _FileResp:
                def __init__(self, payload: dict[str, str]) -> None:
                    self._buf = io.StringIO(json.dumps(payload))

                def __enter__(self) -> io.StringIO:
                    return self._buf

                def __exit__(self, *args: object) -> None:
                    return None

            plan_derived = threading.Event()
            release_refresh = threading.Event()
            writer_started = threading.Event()
            writer_done = threading.Event()
            refresh_results: list[bool] = []
            writer_results: list[bool] = []
            failures: list[BaseException] = []
            real_plan = name_mapper.plan_local_overlay_migration

            def pause_after_plan(
                mapper_path: str, incoming: dict[str, str]
            ) -> dict[str, str] | None:
                planned = real_plan(mapper_path, incoming)
                plan_derived.set()
                if not release_refresh.wait(5):
                    raise TimeoutError("test did not release mapper refresh")
                return planned

            def refresh() -> None:
                try:
                    refresh_results.append(DownloadManager().update_model_settings())
                except BaseException as exc:
                    failures.append(exc)

            def add_name() -> None:
                writer_started.set()
                try:
                    writer_results.append(
                        name_mapper.add_local_name(mapper, "concurrent.ckpt", "Concurrent evidence")
                    )
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    writer_done.set()

            with (
                mock.patch.object(downloads_mod, "_MODEL_DATA_URLS", [("https://x/mdx", mapper)]),
                mock.patch.object(downloads_mod, "_NAME_MAPPER_DESTS", frozenset({mapper})),
                mock.patch.object(downloads_mod, "_urlopen", return_value=_FileResp(remote)),
                mock.patch.object(
                    name_mapper,
                    "plan_local_overlay_migration",
                    side_effect=pause_after_plan,
                ),
            ):
                refresh_thread = threading.Thread(target=refresh)
                writer_thread = threading.Thread(target=add_name)
                refresh_thread.start()
                self.assertTrue(plan_derived.wait(2), "refresh did not reach planning boundary")
                writer_thread.start()
                self.assertTrue(writer_started.wait(2), "writer thread did not start")
                writer_blocked = False
                try:
                    writer_blocked = not writer_done.wait(0.5)
                finally:
                    release_refresh.set()
                    refresh_thread.join(2)
                    writer_thread.join(2)

            self.assertTrue(
                writer_blocked,
                "writer replaced the overlay after the refresh derived a stale plan",
            )
            self.assertFalse(refresh_thread.is_alive())
            self.assertFalse(writer_thread.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(refresh_results, [True])
            self.assertEqual(writer_results, [True])
            with open(mapper, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), remote)
            with open(overlay, encoding="utf-8") as handle:
                self.assertEqual(
                    json.load(handle),
                    {
                        "legacy.ckpt": "Legacy evidence",
                        "concurrent.ckpt": "Concurrent evidence",
                    },
                )

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


    def _run_update(
        self,
        *,
        local: dict,
        remote: list,
        name_dest_indexes: tuple[int, ...] = (2, 3),
    ):
        """Drive `update_model_settings` over four temp mapper files.

        Returns the mock repository so a caller can assert which invalidation
        event the refresh chose.
        """
        import io
        import json
        import tempfile
        from unittest import mock

        from core import downloads as downloads_mod
        from core.downloads import DownloadManager

        with tempfile.TemporaryDirectory() as tmp:
            dests = [
                os.path.join(tmp, name)
                for name in ("vr.json", "mdx_hash.json", "mdx_name.json", "demucs.json")
            ]
            for dest in dests:
                with open(dest, "w", encoding="utf-8") as handle:
                    json.dump(local, handle)

            class _FileResp:
                def __init__(self, payload: dict) -> None:
                    self._buf = io.StringIO(json.dumps(payload))

                def __enter__(self) -> io.StringIO:
                    return self._buf

                def __exit__(self, *args: object) -> None:
                    return None

            side = [_FileResp(payload) for payload in remote]
            repo = mock.Mock()
            with mock.patch.object(
                downloads_mod,
                "_MODEL_DATA_URLS",
                [(f"https://x/{i}", dest) for i, dest in enumerate(dests)],
            ), mock.patch.object(
                downloads_mod,
                "_NAME_MAPPER_DESTS",
                frozenset(dests[i] for i in name_dest_indexes),
            ), mock.patch.object(downloads_mod, "_urlopen", side_effect=side):
                ok = DownloadManager().update_model_settings(repo)
            self.assertTrue(ok)
            return repo

    def test_hash_map_change_takes_the_full_invalidation(self) -> None:
        same = {"a.ckpt": "A"}
        repo = self._run_update(
            local=same,
            remote=[{"a.ckpt": "CHANGED"}, same, same, same],
        )
        repo.invalidate_models.assert_called_once_with()
        repo.invalidate_model_presentation.assert_not_called()

    def test_name_mapper_only_change_takes_the_presentation_event(self) -> None:
        same = {"a.ckpt": "A"}
        repo = self._run_update(
            local=same,
            remote=[same, same, {"a.ckpt": "Friendlier A"}, same],
        )
        repo.invalidate_model_presentation.assert_called_once_with(reload_mappers=True)
        repo.invalidate_models.assert_not_called()

    def test_hash_change_subsumes_a_simultaneous_name_change(self) -> None:
        """One mapper transaction never emits both events."""
        same = {"a.ckpt": "A"}
        repo = self._run_update(
            local=same,
            remote=[{"a.ckpt": "X"}, same, {"a.ckpt": "Friendlier A"}, same],
        )
        repo.invalidate_models.assert_called_once_with()
        repo.invalidate_model_presentation.assert_not_called()

    def test_no_semantic_change_emits_neither_event(self) -> None:
        same = {"a.ckpt": "A"}
        repo = self._run_update(local=same, remote=[same, same, same, same])
        repo.invalidate_models.assert_not_called()
        repo.invalidate_model_presentation.assert_not_called()

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
            mode=RefreshMode.OFFLINE,
            policy=AccessPolicy(allow_network=False, allow_metadata_writes=False),
        ).mdx)
        self.assertTrue(manager.ensure_catalogues(allow_network=True))


if __name__ == "__main__":
    unittest.main()
