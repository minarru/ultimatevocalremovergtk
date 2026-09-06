"""The manual-download dialog reads the same merge as everything else.

``manual_download_data`` used to build its own catalogue from ``online_data``
plus Politrees, with no extras, no mvsepless and no dedupe — a third merge path
alongside the two ``catalog_sources`` unified. It listed 197 models where the
Download Center listed 459.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.catalog_sources import EntryMeta
from core.downloads import DownloadManager


class ManualDownloadMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        # manual_links resolves jobs, which fetches a missing MDX-C config.
        patcher = mock.patch("core.mdx_config_fetch.ensure_mdx_c_config", return_value=False)
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
            "mdx23c_download_vip_list": {"MDX23C Model VIP: Added": {"v.ckpt": "v.yaml"}},
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
        self.assertEqual([k.split(": ", 1)[1] for k in data["mdx"]], ["Apple by X", "Zebra by X"])

    def test_labels_stay_raw_so_manual_links_still_resolve(self) -> None:
        """The compatibility mapping continues to retain raw catalogue keys."""
        with mock.patch(
            "core.catalog_sources._supplemental_sources", return_value=({}, {}, {}, {})
        ):
            data = self.manager.manual_download_data()
        model = data["mdx"]["TR Roformer"]
        links = DownloadManager.manual_links("MDX-Net", model)
        self.assertTrue(links)

    def test_exact_projection_controls_row_title_sort_and_link_selection(self) -> None:
        hp = "VR Arch Single Model v5: 1_HP-UVR"
        aardvark = "VR Arch Single Model v5: Aardvark"
        self.manager.online_data = {
            "vr_download_list": {
                hp: "1_HP-UVR.pth",
                aardvark: "Aardvark.pth",
            }
        }
        with mock.patch(
            "core.catalog_sources._supplemental_sources",
            return_value=({}, {}, {}, {}),
        ):
            rows = self.manager.manual_download_rows()["vr"]

        self.assertEqual(
            [(row.display, row.selection) for row in rows],
            [("VR v5 — Aardvark", aardvark), ("VR v5 — HP 1", hp)],
        )
        hp_row = rows[1]
        self.assertEqual(hp_row.model, "1_HP-UVR.pth")
        with mock.patch.object(
            DownloadManager,
            "manual_links",
            return_value=[("Model", "https://example.invalid/model")],
        ) as resolve:
            self.assertTrue(hp_row.resolve_links())
        resolve.assert_called_once_with(
            VR_ARCH_TYPE,
            "1_HP-UVR.pth",
            selection=hp,
        )

    def test_online_overlay_uses_fresh_scoped_meta_after_stale_snapshot(self) -> None:
        """A stale coordinator must not hide the compatibility overlay row."""
        hp = "VR Arch Single Model v5: 1_HP-UVR"
        aardvark = "VR Arch Single Model v5: Aardvark"
        self.manager.online_data = {
            "vr_download_list": {
                hp: "1_HP-UVR.pth",
                aardvark: "Aardvark.pth",
            }
        }
        self.manager._coordinator = SimpleNamespace(
            latest_snapshot=SimpleNamespace(meta_by_family={"vr": {}})
        )

        with mock.patch(
            "core.catalog_sources._supplemental_sources",
            return_value=({}, {}, {}, {}),
        ):
            data = self.manager.manual_download_data()
            rows = self.manager.manual_download_rows()["vr"]

        self.assertIn(hp, self.manager.catalogue_meta_by_family["vr"])
        self.assertEqual(list(data["vr"]), [aardvark, hp])
        self.assertEqual(
            [(row.display, row.selection) for row in rows],
            [
                ("VR v5 — Aardvark", aardvark),
                ("VR v5 — HP 1", hp),
            ],
        )

    def _same_label_without_snapshot(self) -> tuple[str, str]:
        """Install a collision-prone flat MDX row without a coordinator."""
        shared = "VR Arch Single Model v5: 1_HP-UVR"
        aardvark = "VR Arch Single Model v5: Aardvark"
        shared_raw = {"1_HP-UVR.pth": "https://example.invalid/shared"}
        self.manager.online_data = {}
        self.manager.vr_download_list = {
            shared: shared_raw,
            aardvark: {"Aardvark.pth": "https://example.invalid/aardvark"},
        }
        # The flat map retains the MDX row after two families select the same
        # label. There is deliberately no family-scoped snapshot to resolve.
        self.manager.mdx_download_list = {shared: shared_raw}
        self.manager.demucs_download_list = {}
        self.manager.apollo_download_list = {}
        self.manager.catalogue_meta = {
            shared: EntryMeta(
                label=shared,
                display=shared,
                arch=MDX_ARCH_TYPE,
                files=shared_raw,
                checkpoint="1_HP-UVR.pth",
            )
        }
        self.manager._coordinator = None
        self.manager.catalogue_meta_by_family = {}
        return shared, aardvark

    def test_manual_download_data_rejects_flat_cross_family_meta_without_snapshot(self) -> None:
        shared, aardvark = self._same_label_without_snapshot()

        data = self.manager.manual_download_data()

        # The raw fallback for the shared VR row sorts before Aardvark. If the
        # flat MDX metadata reached exact projection it would become "HP 1"
        # and sort after it instead.
        self.assertEqual(list(data["vr"]), [shared, aardvark])
        self.assertIn(shared, data["mdx"])

    def test_manual_download_rows_reject_flat_cross_family_meta_without_snapshot(self) -> None:
        shared, aardvark = self._same_label_without_snapshot()

        rows = self.manager.manual_download_rows()["vr"]

        self.assertEqual(
            [(row.display, row.selection) for row in rows],
            [
                ("VR v5 — 1_HP-UVR", shared),
                ("VR v5 — Aardvark", aardvark),
            ],
        )

    def test_former_vip_manual_link_uses_additional_public_repo(self) -> None:
        label = "MDX-Net Model VIP: UVR-MDX-NET_Main_427"
        links = DownloadManager.manual_links(
            "MDX-Net", "UVR-MDX-NET_Main_427.onnx", selection=label
        )
        self.assertEqual(
            links[0][1],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/UVR-MDX-NET_Main_427.onnx",
        )


class StructureOnlyFormatterCompatibilityTests(unittest.TestCase):
    def test_canonical_formatter_remains_available(self) -> None:
        from core.model_naming import canonical_display_name

        self.assertEqual(
            canonical_display_name("MDX-Net Model: UVR-MDX-NET Inst HQ 1"),
            "MDX-Net — UVR-MDX-NET Inst HQ 1",
        )


if __name__ == "__main__":
    unittest.main()
