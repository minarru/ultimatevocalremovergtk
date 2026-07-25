"""Tests for curated ensemble recipe loading and member resolution."""

from __future__ import annotations

import unittest
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE
from core.ensemble_presets import (
    classify_preset_members,
    curated_combo_label,
    curated_id_from_combo_label,
    download_entries_for_missing,
    find_download_selection,
    list_curated_ensembles,
    load_curated_ensemble,
    resolve_member_tag,
)


class CuratedPresetLoadTests(unittest.TestCase):
    def test_list_includes_shipped_recipes(self) -> None:
        names = list_curated_ensembles()
        self.assertIn("Vocal_Balanced", names)
        self.assertIn("Karaoke", names)

    def test_load_schema(self) -> None:
        data = load_curated_ensemble("Vocal_Balanced")
        self.assertIsNotNone(data)
        assert data is not None
        self.assertIn("description", data)
        self.assertEqual(data["ensemble_main_stem"], "Vocals/Instrumental")
        self.assertEqual(data["ensemble_type"], "Average/Average")
        self.assertGreaterEqual(len(data["selected_models"]), 2)
        self.assertTrue(data["selected_models"][0].startswith("MDX-Net: "))

    def test_combo_label_roundtrip(self) -> None:
        label = curated_combo_label("Vocal_Balanced")
        self.assertTrue(label.startswith("Curated: "))
        self.assertEqual(curated_id_from_combo_label(label), "Vocal_Balanced")


class ResolveAndDownloadTests(unittest.TestCase):
    def test_resolve_member_tag_uses_display(self) -> None:
        repo = mock.Mock()
        repo.mdx_name_select_MAPPER = {}
        repo.mdx_catalogue_display_index.return_value = {
            "model_BandSplit-Roformer_Resurrection_Vocals_by-Unwa": (
                "BandSplit Roformer | Resurrection Vocals by Unwa"
            ),
        }
        with mock.patch(
            "core.ensemble_presets.resolve_model_basename",
            return_value="model_BandSplit-Roformer_Resurrection_Vocals_by-Unwa",
        ), mock.patch(
            "core.ensemble_presets.display_name_for_model",
            return_value="BandSplit Roformer | Resurrection Vocals by Unwa",
        ):
            tag = resolve_member_tag(
                "MDX-Net: BandSplit Roformer | Resurrection Vocals by Unwa",
                repo,
            )
        self.assertEqual(
            tag,
            "MDX-Net: BandSplit Roformer | Resurrection Vocals by Unwa",
        )

    def test_classify_missing_members(self) -> None:
        repo = mock.Mock()

        def _installed(tag, _repo):
            return tag.endswith(": A")

        with mock.patch(
            "core.ensemble_presets.member_is_installed",
            side_effect=_installed,
        ), mock.patch(
            "core.ensemble_presets.resolve_member_tag",
            side_effect=lambda tag, _repo: tag,
        ):
            installed, missing = classify_preset_members(
                ["MDX-Net: A", "MDX-Net: B"],
                repo,
            )
        self.assertEqual(installed, ["MDX-Net: A"])
        self.assertEqual(missing, ["MDX-Net: B"])

    def test_find_download_selection_by_display(self) -> None:
        manager = mock.Mock()
        manager.ensure_catalogues = mock.Mock()
        manager.mdx_download_list = {
            "Roformer Model: MelBand Roformer | Karaoke by becruily": {
                "melband_roformer_karaoke_becruily.ckpt": "config.yaml",
            }
        }
        manager.vr_download_list = {}
        manager.demucs_download_list = {}
        found = find_download_selection(
            "MDX-Net: MelBand Roformer | Karaoke by becruily",
            manager,
        )
        self.assertEqual(
            found,
            (
                "Roformer Model: MelBand Roformer | Karaoke by becruily",
                MDX_ARCH_TYPE,
            ),
        )

    def test_download_entries_for_missing(self) -> None:
        manager = mock.Mock()
        with mock.patch(
            "core.ensemble_presets.find_download_selection",
            side_effect=[
                ("sel-a", MDX_ARCH_TYPE),
                None,
            ],
        ):
            entries, unresolved = download_entries_for_missing(
                ["MDX-Net: A", "MDX-Net: B"],
                manager,
            )
        self.assertEqual(entries, [("sel-a", MDX_ARCH_TYPE)])
        self.assertEqual(unresolved, ["MDX-Net: B"])


if __name__ == "__main__":
    unittest.main()
