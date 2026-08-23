"""Tests for curated ensemble recipe loading and member resolution."""

from __future__ import annotations
import json
from pathlib import Path
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
from core.model_identity import (
    CatalogueRef,
    IdentityIndex,
    ModelArtifacts,
    ModelIdentityService,
    ModelRecord,
    parse_stored_model_id,
)


class CuratedPresetIdTests(unittest.TestCase):
    def test_every_bundled_member_is_a_canonical_id(self) -> None:
        root = Path("bundled/ensemble_presets")
        for path in root.glob("*.json"):
            payload = json.loads(path.read_text())
            for member in payload["selected_models"]:
                parse_stored_model_id(member)


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
    @staticmethod
    def _resurrection_record() -> ModelRecord:
        return ModelRecord(
            id="mdx:model_BandSplit-Roformer_Resurrection_Vocals_by-Unwa",
            family="mdx",
            basename="model_BandSplit-Roformer_Resurrection_Vocals_by-Unwa",
            display="BandSplit Roformer | Resurrection Vocals by Unwa",
            backend_name="model_BandSplit-Roformer_Resurrection_Vocals_by-Unwa",
            artifacts=ModelArtifacts(
                "model_BandSplit-Roformer_Resurrection_Vocals_by-Unwa.ckpt"
            ),
            installed=False,
        )

    def test_resolve_member_tag_preserves_legacy_text(self) -> None:
        """Saved legacy text remains visible rather than becoming an identity."""
        repo = mock.Mock()
        record = self._resurrection_record()
        index = IdentityIndex({record.id: record})
        with mock.patch.object(
            ModelIdentityService, "_published_index", return_value=index,
        ):
            tag = resolve_member_tag(f"MDX-Net: {record.basename}", repo)
        self.assertEqual(tag, f"MDX-Net: {record.basename}")

    def test_resolve_member_tag_does_not_invert_a_display_label(self) -> None:
        """A catalogue rename must not be able to move a stored member.

        The legacy tag keeps its raw name half so the missing-model report can
        show what was written; it is never silently converted into an id.
        """
        repo = mock.Mock()
        record = self._resurrection_record()
        index = IdentityIndex({record.id: record})
        with mock.patch.object(
            ModelIdentityService, "_published_index", return_value=index,
        ):
            tag = resolve_member_tag(f"MDX-Net: {record.display}", repo)
        self.assertNotEqual(tag, record.id)
        self.assertEqual(tag, f"MDX-Net: {record.display}")

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
        record = ModelRecord(
            id="mdx:model-a",
            family="mdx",
            basename="model-a",
            display="A display that is not a catalogue selection",
            backend_name="model-a",
            artifacts=ModelArtifacts("model-a.ckpt"),
            installed=False,
            catalogue_entry=CatalogueRef("mdx", "sel-a"),
        )
        index = IdentityIndex({record.id: record})
        with mock.patch.object(
            ModelIdentityService, "_published_index", return_value=index,
        ):
            entries, unresolved = download_entries_for_missing(
                ["mdx:model-a", "mdx:model-b"],
                manager,
                mock.Mock(),
            )
        self.assertEqual(entries, [("sel-a", MDX_ARCH_TYPE)])
        self.assertEqual(unresolved, ["mdx:model-b"])



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
        from core.model_repository import ModelRepository

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
