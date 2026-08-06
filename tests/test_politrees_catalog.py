"""Tests for Politrees catalogue merge and download resolution."""
import typing

import os
import tempfile
import unittest
from unittest.mock import patch

from bundled.constants import MDX_ARCH_TYPE, NORMAL_REPO
from core.downloads import DownloadManager
from core.politrees_catalog import (
    build_weight_url_index,
    clear_politrees_cache,
    hf_fallback_url,
    merge_politrees_catalogues,
    merge_supplemental_list,
    resolve_mdx_jobs,
    resolve_vr_jobs,
)


class MergeCatalogueTests(unittest.TestCase):
    def test_merge_supplemental_skips_existing_keys(self) -> None:
        base = {"A": "a.onnx"}
        extra = {"A": "other.onnx", "B": "b.onnx"}
        merged = merge_supplemental_list(base, extra)
        self.assertEqual(merged["A"], "a.onnx")
        self.assertEqual(merged["B"], "b.onnx")

    def test_merge_politrees_adds_roformer_entries(self) -> None:
        tr_mdx = {"TR Roformer": {"model.ckpt": "model.yaml"}}
        politrees = {
            "roformer_download_list": {
                "Community Roformer": {
                    "community.ckpt": "https://huggingface.co/example/community.ckpt",
                    "community.yaml": "https://example.com/community.yaml",
                }
            }
        }
        _, mdx, _ = merge_politrees_catalogues({}, tr_mdx, {}, politrees)
        self.assertIn("TR Roformer", mdx)
        self.assertIn("Community Roformer", mdx)


class ResolveJobsTests(unittest.TestCase):
    def setUp(self) -> None:
        # resolve_mdx_jobs fetches a missing MDX-C config; these tests only
        # assert on the resolved job list.
        patcher = patch("core.mdx_config_fetch.ensure_mdx_c_config", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_resolve_trvlvr_mdx_job(self) -> None:
        jobs = resolve_mdx_jobs({"model.onnx": "config.yaml"}, NORMAL_REPO)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0][0].startswith(NORMAL_REPO))

    def test_resolve_politrees_mdx_jobs(self) -> None:
        model = {
            "community.ckpt": "https://huggingface.co/example/community.ckpt",
            "community.yaml": "https://example.com/community.yaml",
        }
        jobs = resolve_mdx_jobs(model, NORMAL_REPO)
        self.assertEqual(len(jobs), 2)
        urls = {job[0] for job in jobs}
        self.assertIn("https://huggingface.co/example/community.ckpt", urls)
        self.assertIn("https://example.com/community.yaml", urls)

    def test_resolve_politrees_vr_job(self) -> None:
        jobs = resolve_vr_jobs(
            {"test.pth": "https://huggingface.co/example/test.pth"},
            NORMAL_REPO,
        )
        self.assertEqual(jobs[0][0], "https://huggingface.co/example/test.pth")


class HfFallbackTests(unittest.TestCase):
    def test_hf_fallback_maps_trvlvr_filename(self) -> None:
        index = build_weight_url_index(
            {
                "mdx_download_list": {
                    "MDX": {"Kim_Inst.onnx": "https://huggingface.co/example/Kim_Inst.onnx"}
                }
            }
        )
        url = hf_fallback_url(f"{NORMAL_REPO}Kim_Inst.onnx", index)
        self.assertEqual(url, "https://huggingface.co/example/Kim_Inst.onnx")


class DownloadManagerPolitreesTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_politrees_cache()
        self.manager = DownloadManager()
        self.manager.online_data = {
            "roformer_download_list": {
                "TR Roformer": {"model.ckpt": "model.yaml"},
            }
        }
        self.manager._rebuild_catalogues()

    def tearDown(self) -> None:
        clear_politrees_cache()

    # The politrees load moved into core.catalog_sources when the two merge
    # paths were unified; patch it where it is now looked up.
    @patch("core.catalog_sources.load_politrees_links")
    def test_refresh_merges_politrees_models(self, mock_load: typing.Any) -> None:
        mock_load.return_value = {
            "roformer_download_list": {
                "Extra Roformer": {
                    "extra.ckpt": "https://huggingface.co/example/extra.ckpt",
                    "extra.yaml": "https://example.com/extra.yaml",
                }
            }
        }
        self.manager._merge_politrees_supplement()
        self.assertIn("Extra Roformer", self.manager.mdx_download_list)
        self.assertIn("TR Roformer", self.manager.mdx_download_list)

    def test_resolve_politrees_selection(self) -> None:
        self.manager.mdx_download_list["Extra"] = {
            "extra.ckpt": "https://huggingface.co/example/extra.ckpt",
            "extra.yaml": "https://example.com/extra.yaml",
        }
        jobs = self.manager.resolve("Extra", MDX_ARCH_TYPE)
        self.assertEqual(len(jobs), 2)


if __name__ == "__main__":
    unittest.main()
