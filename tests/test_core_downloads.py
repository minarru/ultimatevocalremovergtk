import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, NO_MODEL, VR_ARCH_TYPE
from core.downloads import DownloadManager, vip_downloads
from core import paths


class DownloadManagerResolveTests(unittest.TestCase):
    def setUp(self):
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
            repo.invalidate_stem_check.assert_called_once()


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
            repo.invalidate_stem_check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
