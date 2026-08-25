"""Ensemble collection retains trusted planned role/tag metadata."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace

from core.ensembler import CollectedStem, Ensembler, planned_ensemble_stems
from core.export_naming import format_stem_basename
from core.stem_roles import StemLiteral, StemRoleId
from core.stems import StemId, StemRoute, StemRouteKind


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
            {
                "Vocals": CollectedStem(
                    StemRoleId("vocal.vocals"), "Vocals", "mdx:member"
                )
            },
        )

    def test_reviewed_roles_combine_but_raw_literals_remain_member_scoped(self) -> None:
        reviewed_a = CollectedStem(StemRoleId("vocal.vocals"), "Vocals", "member-a")
        reviewed_b = CollectedStem(StemRoleId("vocal.vocals"), "Vocals", "member-b")
        raw_a = CollectedStem(StemLiteral("Vocals"), "Vocals", "member-a")
        raw_b = CollectedStem(StemLiteral("Vocals"), "Vocals", "member-b")

        self.assertEqual(reviewed_a.group_key, reviewed_b.group_key)
        self.assertNotEqual(raw_a.group_key, raw_b.group_key)


if __name__ == "__main__":
    unittest.main()
