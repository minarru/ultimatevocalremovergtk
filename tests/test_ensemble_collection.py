"""Ensemble collection retains trusted planned role/tag metadata."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any

from core.ensembler import CollectedStem, Ensembler, planned_ensemble_stems
from core.export_naming import format_stem_basename
from core.stem_roles import StemLiteral, StemRoleId
from core.stems import StemId, StemRoute, StemRouteKind, run_export_routes


def _collector() -> Ensembler:
    """An Ensembler whose reader can be used without creating run folders."""
    return object.__new__(Ensembler)


def _write_member(folder: str, track: str, model_name: str, tag: str) -> str:
    name = format_stem_basename(f"{track} {model_name}", tag) + ".wav"
    with open(os.path.join(folder, name), "wb") as handle:
        handle.write(b"")
    return name


class PlannedCollectionTests(unittest.TestCase):
    def test_reader_uses_the_planned_tag_without_normalizing_filename_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            trusted = _write_member(folder, "Song", "ModelA", "Vocals")
            _write_member(folder, "Song", "ModelB", "vocals")
            found = _collector().get_files_to_ensemble_for_stem(
                folder=folder, prefix="Song", stem_tag="Vocals"
            )

        self.assertEqual([os.path.basename(path) for path in found], [trusted])

    def test_planned_member_stems_carry_role_and_registry_tag(self) -> None:
        model = SimpleNamespace(
            canonical_id="mdx:member",
            is_vocal_split_model=False,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_inst_only_voc_splitter=False,
            is_sec_bv_rebalance=False,
            is_ensemble_mode=False,
            selected_stem_routes=(
                StemRoute(
                    StemId("native-vocals"),
                    StemRoleId("vocal.vocals"),
                    "Vocals",
                    "Vocals",
                    StemRouteKind.NATIVE,
                ),
            ),
            available_stem_routes=(),
        )

        self.assertEqual(
            planned_ensemble_stems(model),
            {"Vocals": CollectedStem(StemRoleId("vocal.vocals"), "Vocals", "mdx:member")},
        )

    def test_reviewed_roles_combine_but_raw_literals_remain_member_scoped(self) -> None:
        reviewed_a = CollectedStem(StemRoleId("vocal.vocals"), "Vocals", "member-a")
        reviewed_b = CollectedStem(StemRoleId("vocal.vocals"), "Vocals", "member-b")
        raw_a = CollectedStem(StemLiteral("Vocals"), "Vocals", "member-a")
        raw_b = CollectedStem(StemLiteral("Vocals"), "Vocals", "member-b")

        self.assertEqual(reviewed_a.group_key, reviewed_b.group_key)
        self.assertNotEqual(raw_a.group_key, raw_b.group_key)

    def test_planned_raw_literals_without_a_scope_remain_member_scoped(self) -> None:
        """Fail closed when a raw route reaches collection without its scope."""
        route = StemRoute(
            StemId("Mystery"),
            StemLiteral("Mystery"),
            "Mystery",
            "Mystery",
            selection_scope="",
        )
        member_a = SimpleNamespace(
            canonical_id="mdx:unknown-a",
            is_vocal_split_model=False,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_inst_only_voc_splitter=False,
            is_sec_bv_rebalance=False,
            is_ensemble_mode=False,
            selected_stem_routes=(route,),
            available_stem_routes=(),
        )
        member_b = SimpleNamespace(
            canonical_id="demucs:unknown-b",
            is_vocal_split_model=False,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_inst_only_voc_splitter=False,
            is_sec_bv_rebalance=False,
            is_ensemble_mode=False,
            selected_stem_routes=(route,),
            available_stem_routes=(),
        )

        planned_a = planned_ensemble_stems(member_a)["Mystery"]
        planned_b = planned_ensemble_stems(member_b)["Mystery"]

        self.assertNotEqual(planned_a.group_key, planned_b.group_key)
        self.assertEqual(planned_a.raw_scope, "mdx:unknown-a")
        self.assertEqual(planned_b.raw_scope, "demucs:unknown-b")

    def test_incomplete_four_stem_member_has_no_dual_pair_exports(self) -> None:
        """A partial member cannot leak one reviewed role into a dual pair."""
        from bundled.constants import IS_SAVE_INST_ONLY, IS_SAVE_VOC_ONLY
        from core.model_config.config import ModelConfig
        from core.settings import Settings
        from core.types import ProcessMethod

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.process.stem_focus = "vocal.vocals"
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        member: Any = SimpleNamespace(
            settings=settings,
            canonical_id="mdx:model_scnet_ep_54_sdr_9.8051",
            primary_stem="Drums",
            primary_stem_native="Drums",
            secondary_stem="",
            target_instrument="",
            is_vocal_split_model=False,
            is_karaoke=False,
            is_bv_model=False,
            mdx_stem_count=4,
            demucs_stem_count=0,
            mdx_model_stems=["Drums", "Bass", "Other", "Vocals"],
            demucs_source_list=[],
            mdxnet_stems_selected=[],
            is_mdx_include_stem_complement=False,
            is_ensemble_mode=True,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_inst_only_voc_splitter=False,
            is_sec_bv_rebalance=False,
            ensemble_pair_roles=(
                StemRoleId("vocal.vocals"),
                StemRoleId("mix.instrumental"),
            ),
            ensemble_primary_stem="Vocals",
            ensemble_secondary_stem="Instrumental",
        )

        ModelConfig._apply_stem_focus(member)  # type: ignore[arg-type]

        self.assertEqual(member.selected_stem_routes, ())
        self.assertEqual(run_export_routes(member), ())
        self.assertEqual(
            ModelConfig._exclusive_sides_from_routes(member),  # type: ignore[arg-type]
            (False, False),
        )
        self.assertFalse(
            ModelConfig.check_only_selection_stem(  # type: ignore[arg-type]
                member, IS_SAVE_VOC_ONLY
            )
        )
        self.assertFalse(
            ModelConfig.check_only_selection_stem(  # type: ignore[arg-type]
                member, IS_SAVE_INST_ONLY
            )
        )

    def test_complete_pair_member_keeps_an_explicit_role_focus(self) -> None:
        """A matched role focus must not be widened to both pair exports."""
        from bundled.constants import IS_SAVE_INST_ONLY, IS_SAVE_VOC_ONLY
        from core.model_config.config import ModelConfig
        from core.settings import Settings
        from core.types import ProcessMethod

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.process.stem_focus = "vocal.vocals"
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        member: Any = SimpleNamespace(
            settings=settings,
            canonical_id="mdx:MelBandRoformerBigSYHFTV1",
            primary_stem="Vocals",
            primary_stem_native="Vocals",
            secondary_stem="other",
            target_instrument="vocals",
            is_vocal_split_model=False,
            is_karaoke=False,
            is_bv_model=False,
            mdx_stem_count=1,
            demucs_stem_count=0,
            mdx_model_stems=["vocals"],
            demucs_source_list=[],
            mdxnet_stems_selected=[],
            is_mdx_include_stem_complement=False,
            is_ensemble_mode=True,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_inst_only_voc_splitter=False,
            is_sec_bv_rebalance=False,
            ensemble_pair_roles=(
                StemRoleId("vocal.vocals"),
                StemRoleId("mix.instrumental"),
            ),
            ensemble_primary_stem="Vocals",
            ensemble_secondary_stem="Instrumental",
        )

        ModelConfig._apply_stem_focus(member)  # type: ignore[arg-type]

        self.assertEqual(
            [route.role for route in member.selected_stem_routes],
            [StemRoleId("vocal.vocals")],
        )
        self.assertEqual(
            [route.role for route in run_export_routes(member)],
            [StemRoleId("vocal.vocals")],
        )
        self.assertEqual(
            ModelConfig._exclusive_sides_from_routes(member),  # type: ignore[arg-type]
            (True, False),
        )
        self.assertTrue(
            ModelConfig.check_only_selection_stem(  # type: ignore[arg-type]
                member, IS_SAVE_VOC_ONLY
            )
        )
        self.assertFalse(
            ModelConfig.check_only_selection_stem(  # type: ignore[arg-type]
                member, IS_SAVE_INST_ONLY
            )
        )

    def test_karaoke_pair_ignores_giantailab_residual_focus(self) -> None:
        """A matched non-pair role must not escape karaoke pair routing."""
        from core.model_config.config import ModelConfig
        from core.settings import Settings
        from core.types import ProcessMethod

        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.process.stem_focus = "residual.backing_vocal"
        settings.ensemble.main_stem = "pair.karaoke"
        member: Any = SimpleNamespace(
            settings=settings,
            canonical_id="mdx:bs_karaoke_3stem_giantailab",
            primary_stem="vocals",
            primary_stem_native="vocals",
            secondary_stem="instrumental",
            target_instrument="",
            is_vocal_split_model=False,
            is_karaoke=False,
            is_bv_model=False,
            mdx_stem_count=3,
            demucs_stem_count=0,
            mdx_model_stems=["vocals", "backing_vocal", "instrumental"],
            demucs_source_list=[],
            mdxnet_stems_selected=[],
            is_mdx_include_stem_complement=False,
            is_ensemble_mode=True,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_inst_only_voc_splitter=False,
            is_sec_bv_rebalance=False,
        )

        ModelConfig._apply_stem_focus(member)  # type: ignore[arg-type]

        expected_roles = [
            StemRoleId("mix.instrumental_with_backing_vocals"),
            StemRoleId("vocal.lead"),
        ]
        self.assertEqual([route.role for route in member.selected_stem_routes], expected_roles)
        self.assertEqual([route.role for route in run_export_routes(member)], expected_roles)


if __name__ == "__main__":
    unittest.main()
