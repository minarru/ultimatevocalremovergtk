"""Installed copies of retired catalogue duplicates link to the kept entry."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from bundled.constants import MDX_ARCH_TYPE
from core.catalog_dedupe import CatalogueDuplicate
from core.catalog_sources import EntryMeta
from core.catalogue_coordinator import _checkpoint_alias_index
from core.model_identity import CatalogueRef, ModelRecord
from core.model_inventory import build_identity_index

_KEPT = "Roformer Model: MelBand Roformer | Vocals by Someone"


def _snapshot(aliases: dict[str, str] | None = None) -> Any:
    files = {"kept.ckpt": "kept.yaml"}
    entry = EntryMeta(
        label=_KEPT,
        display="MelBand Roformer — Vocals · Someone",
        arch=MDX_ARCH_TYPE,
        files=files,
        checkpoint="kept.ckpt",
        stems=["vocals", "other"],
    )
    families = {"vr": {}, "mdx": {_KEPT: files}, "demucs": {}, "apollo": {}}
    return SimpleNamespace(
        **families,
        meta_by_family={"vr": {}, "mdx": {_KEPT: entry}, "demucs": {}, "apollo": {}},
        unsupported={},
        display_index_vr={},
        display_index_mdx={},
        display_index_demucs={},
        checkpoint_aliases={"mdx": dict(aliases or {})},
    )


def _repo(*mdx_files: str) -> Any:
    return SimpleNamespace(
        list_vr_models=lambda: [],
        list_mdx_models=lambda: [],
        list_demucs_models=lambda: [],
        inventory_generation=0,
        catalogue_revision="x",
        naming_revision=0,
        mdx_name_select_MAPPER={},
        demucs_name_select_MAPPER={},
        _model_artifact_files=lambda family: list(mdx_files) if family == "mdx" else [],
    )


def _records(repo: Any, snapshot: Any) -> dict[str, ModelRecord]:
    index = build_identity_index(
        repo, snapshot=snapshot, bundled_demucs_specs={}, registered_demucs={}
    )
    return {record.id: record for record in index.records()}


class RetiredDuplicateIdentityTests(unittest.TestCase):
    def test_installed_copy_links_to_the_kept_entry_and_keeps_its_id(self) -> None:
        records = _records(_repo("copy.ckpt", "copy.yaml"), _snapshot({"copy.ckpt": _KEPT}))
        copy = records["mdx:copy"]
        self.assertTrue(copy.installed)
        self.assertEqual(copy.artifacts.primary_filename, "copy.ckpt")
        self.assertEqual(copy.catalogue_entry, CatalogueRef("mdx", _KEPT))
        # The kept entry itself is still a separate, not-installed catalogue row.
        self.assertFalse(records["mdx:kept"].installed)

    def test_without_an_alias_the_copy_stays_unlinked(self) -> None:
        records = _records(_repo("copy.ckpt", "copy.yaml"), _snapshot())
        self.assertIsNone(records["mdx:copy"].catalogue_entry)

    def test_alias_to_an_unpublished_selection_is_ignored(self) -> None:
        records = _records(
            _repo("copy.ckpt", "copy.yaml"), _snapshot({"copy.ckpt": "Not Published"})
        )
        self.assertIsNone(records["mdx:copy"].catalogue_entry)

    def test_exact_filename_match_still_wins(self) -> None:
        records = _records(_repo("kept.ckpt", "kept.yaml"), _snapshot({"kept.ckpt": "Other"}))
        self.assertTrue(records["mdx:kept"].installed)
        self.assertEqual(records["mdx:kept"].catalogue_entry, CatalogueRef("mdx", _KEPT))

    def test_link_does_not_rename_the_installed_copy(self) -> None:
        linked = _records(_repo("copy.ckpt", "copy.yaml"), _snapshot({"copy.ckpt": _KEPT}))
        unlinked = _records(_repo("copy.ckpt", "copy.yaml"), _snapshot())
        self.assertEqual(linked["mdx:copy"].display, unlinked["mdx:copy"].display)
        self.assertNotIn("Someone", linked["mdx:copy"].display)

    def test_picker_shows_the_kept_entrys_outputs(self) -> None:
        from ui.model_picker_state import project_installed

        snapshot = _snapshot({"copy.ckpt": _KEPT})
        record = _records(_repo("copy.ckpt", "copy.yaml"), snapshot)["mdx:copy"]
        (model,) = project_installed((record,), snapshot, {})
        self.assertNotEqual(model.outputs, "Output details unavailable")
        self.assertIn("vocals", model.outputs)


class CheckpointAliasIndexTests(unittest.TestCase):
    def test_maps_each_duplicate_filename_to_its_kept_selection(self) -> None:
        catalogue = {
            "Kept": {"kept.ckpt": "kept.yaml"},
            "Copy": {"copy.ckpt": "https://example.invalid/copy.ckpt"},
        }
        index = _checkpoint_alias_index(catalogue, {"Copy": CatalogueDuplicate("Kept", "sha256")})
        self.assertEqual(index, {"copy.ckpt": "Kept"})

    def test_filename_shared_by_duplicates_of_different_kept_rows_is_dropped(self) -> None:
        catalogue = {
            "Copy A": {"copy.ckpt": "https://a.invalid/copy.ckpt"},
            "Copy B": {"copy.ckpt": "https://b.invalid/copy.ckpt"},
        }
        index = _checkpoint_alias_index(
            catalogue,
            {
                "Copy A": CatalogueDuplicate("A", "sha256"),
                "Copy B": CatalogueDuplicate("B", "url"),
            },
        )
        self.assertEqual(index, {})


if __name__ == "__main__":
    unittest.main()
