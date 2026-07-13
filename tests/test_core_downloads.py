import os
import tempfile
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
            with open(os.path.join(config_dir, yaml_name), "w", encoding="utf-8") as handle:
                handle.write(open(paths.MDX_C_CONFIG_PATH + "/" + yaml_name, encoding="utf-8").read())

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


if __name__ == "__main__":
    unittest.main()
