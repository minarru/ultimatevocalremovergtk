"""Tests for curated ensemble recipe loading and member resolution."""

from __future__ import annotations
import typing

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
        self.assertEqual(data["ensemble_main_stem"], "vocals_instrumental")
        self.assertEqual(data["ensemble_type"], "Average/Average")
        self.assertGreaterEqual(len(data["selected_models"]), 2)
        from core.model_identity import ModelId

        for member in data["selected_models"]:
            parsed = ModelId.parse(member)
            self.assertEqual(parsed.family, "mdx")

    def test_karaoke_preset_uses_karaoke_id(self) -> None:
        data = load_curated_ensemble("Karaoke")
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data["ensemble_main_stem"], "karaoke")

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
        ):
            tag = resolve_member_tag(
                "MDX-Net: BandSplit Roformer | Resurrection Vocals by Unwa",
                repo,
            )
        self.assertEqual(
            tag,
            "mdx:model_BandSplit-Roformer_Resurrection_Vocals_by-Unwa",
        )

    def test_classify_missing_members(self) -> None:
        repo = mock.Mock()

        def _installed(tag: typing.Any, _repo: typing.Any):
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



class IneligibleMemberTests(unittest.TestCase):
    """A karaoke model saved into a Vocals/Instrumental preset is now ineligible.

    Karaoke models moved to their own stem pair, so presets saved before that
    list members ``ensemble_model_list`` no longer returns. Loading such a
    preset must skip the member, never raise.
    """

    def test_find_download_selection_returns_none_for_unknown_member(self) -> None:
        from core.ensemble_presets import find_download_selection

        class _Manager:
            mdx_download_list = {"MDX-Net Model: Something Else": {"a.ckpt": "u"}}

            def ensure_catalogues(self) -> None:
                return None

        self.assertIsNone(
            find_download_selection("MDX-Net: A Model That No Longer Exists", _Manager())
        )

    def test_find_download_selection_resolves_a_present_member(self) -> None:
        from core.ensemble_presets import find_download_selection

        class _Manager:
            mdx_download_list = {"MDX-Net Model: Something Else": {"a.ckpt": "u"}}

            def ensure_catalogues(self) -> None:
                return None

        result = find_download_selection("MDX-Net: Something Else", _Manager())
        self.assertEqual(result, ("MDX-Net Model: Something Else", "MDX-Net"))

    def test_classify_preset_members_reports_missing_without_raising(self) -> None:
        from core.ensemble_presets import classify_preset_members
        from core.model_data import ModelRepository

        # A real repository with nothing installed: resolve_member_tag reads
        # mapper attributes a hand-rolled fake would not have.
        repo = ModelRepository()
        with mock.patch.object(ModelRepository, "list_mdx_models", return_value=[]), \
             mock.patch.object(ModelRepository, "list_vr_models", return_value=[]), \
             mock.patch.object(ModelRepository, "list_demucs_models", return_value=[]):
            installed, missing = classify_preset_members(["MDX-Net: Gone"], repo)
        self.assertEqual(installed, [])
        self.assertEqual(missing, ["MDX-Net: Gone"])


if __name__ == "__main__":
    unittest.main()
