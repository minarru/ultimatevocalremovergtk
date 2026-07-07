import os
import unittest

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


class VipDownloadsTests(unittest.TestCase):
    def test_wrong_password_returns_no_code(self):
        from bundled.constants import NO_CODE

        self.assertEqual(vip_downloads("definitely-wrong-password"), NO_CODE)


if __name__ == "__main__":
    unittest.main()
