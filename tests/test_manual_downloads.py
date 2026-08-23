"""The manual-download dialog reads the same merge as everything else.

``manual_download_data`` used to build its own catalogue from ``online_data``
plus Politrees, with no extras, no mvsepless and no dedupe — a third merge path
alongside the two ``catalog_sources`` unified. It listed 197 models where the
Download Center listed 459.
"""

from __future__ import annotations

import typing
import unittest
from unittest import mock

from core.downloads import DownloadManager


class ManualDownloadMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        # manual_links resolves jobs, which fetches a missing MDX-C config.
        patcher = mock.patch(
            "core.mdx_config_fetch.ensure_mdx_c_config", return_value=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = DownloadManager()
        self.manager.online_data = {
            "roformer_download_list": {"TR Roformer": {"tr.ckpt": "tr.yaml"}},
        }

    def test_supplemental_entries_are_listed(self) -> None:
        with mock.patch(
            "core.catalog_sources._supplemental_sources",
            return_value=({}, {"Supplemental Model": {"s.ckpt": "https://x/s.ckpt"}}, {}, {}),
        ):
            data = self.manager.manual_download_data()
        self.assertIn("Supplemental Model", data["mdx"])
        self.assertIn("TR Roformer", data["mdx"])

    def test_duplicates_are_deduped(self) -> None:
        self.manager.online_data = {
            "vr_download_list": {
                "VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth",
                "VR Arch Single Model v5: 1_HP-UVR duplicate": "1_HP-UVR.pth",
            }
        }
        with mock.patch(
            "core.catalog_sources._supplemental_sources", return_value=({}, {}, {}, {})
        ):
            data = self.manager.manual_download_data()
        self.assertEqual(len(data["vr"]), 1)

    def test_vip_entries_are_public_without_state_or_code(self) -> None:
        self.manager.online_data = {
            "mdx23c_download_vip_list": {
                "MDX23C Model VIP: Added": {"v.ckpt": "v.yaml"}
            },
        }
        with mock.patch(
            "core.catalog_sources._supplemental_sources", return_value=({}, {}, {}, {})
        ):
            data = self.manager.manual_download_data()
        self.assertIn("MDX23C Model VIP: Added", data["mdx"])

    def test_entries_are_sorted_by_display_name(self) -> None:
        self.manager.online_data = {
            "roformer_download_list": {
                "Roformer Model: Zebra by X": {"z.ckpt": "z.yaml"},
                "Roformer Model: Apple by X": {"a.ckpt": "a.yaml"},
            }
        }
        with mock.patch(
            "core.catalog_sources._supplemental_sources", return_value=({}, {}, {}, {})
        ):
            data = self.manager.manual_download_data()
        self.assertEqual(
            [k.split(": ", 1)[1] for k in data["mdx"]], ["Apple by X", "Zebra by X"]
        )

    def test_labels_stay_raw_so_manual_links_still_resolve(self) -> None:
        """Keys remain catalogue labels; the dialog renders the canonical name."""
        with mock.patch(
            "core.catalog_sources._supplemental_sources", return_value=({}, {}, {}, {})
        ):
            data = self.manager.manual_download_data()
        model = data["mdx"]["TR Roformer"]
        links = DownloadManager.manual_links("MDX-Net", model)
        self.assertTrue(links)

    def test_former_vip_manual_link_uses_additional_public_repo(self) -> None:
        label = "MDX-Net Model VIP: UVR-MDX-NET_Main_427"
        links = DownloadManager.manual_links(
            "MDX-Net", "UVR-MDX-NET_Main_427.onnx", selection=label
        )
        self.assertEqual(
            links[0][1],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/"
            "UVR-MDX-NET_Main_427.onnx",
        )


class ManualDownloadRowTitleTests(unittest.TestCase):
    def test_dialog_renders_the_canonical_name(self) -> None:
        from core.model_naming import canonical_display_name

        self.assertEqual(
            canonical_display_name("MDX-Net Model: UVR-MDX-NET Inst HQ 1"),
            "MDX-Net — UVR-MDX-NET Inst HQ 1",
        )


if __name__ == "__main__":
    unittest.main()
