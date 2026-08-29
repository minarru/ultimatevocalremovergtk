"""MDX architecture classification from YAML bodies and catalogue labels.

Politrees / mvsepless checkpoints often use ``mbr_`` / ``bs_`` prefixes that
filename hints cannot see. Identity still has to resolve so a completed
download can publish.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from bundled.constants import MDX_ARCH_TYPE
from core.catalog_sources import EntryMeta
from core.model_identity import MdxSpec
from core.model_inventory import build_identity_index, mdx_kind_from_names


def _repo(**overrides: Any):
    values = {
        "list_vr_models": lambda: [],
        "list_mdx_models": lambda: [],
        "list_demucs_models": lambda: [],
        "inventory_generation": 0,
        "catalogue_revision": "x",
        "naming_revision": 0,
        "mdx_name_select_MAPPER": {},
        "demucs_name_select_MAPPER": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _snapshot(*, mdx: Any = None, meta: Any = None):
    families = {
        "vr": {},
        "mdx": mdx or {},
        "demucs": {},
        "apollo": {},
    }
    return SimpleNamespace(
        **families,
        meta_by_family={family: dict((meta or {}).get(family, {})) for family in families},
        unsupported={},
        display_index_vr={},
        display_index_mdx={},
        display_index_demucs={},
    )


def _mdx_entry(
    selection: str,
    files: dict[str, str],
    *,
    display: str,
    checkpoint: str,
) -> tuple[str, dict[str, str], EntryMeta]:
    entry = EntryMeta(
        label=selection,
        display=display,
        arch=MDX_ARCH_TYPE,
        files=files,
        checkpoint=checkpoint,
    )
    return selection, files, entry


class MdxKindFromYamlTests(unittest.TestCase):
    def test_abbreviated_mbr_yaml_on_config_path_is_mel_band(self) -> None:
        from core import paths

        ckpt = "mbr_hybrid_arch_aname.ckpt"
        yaml_name = "mbr_hybrid_arch_aname_config.yaml"
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, yaml_name), "w", encoding="utf-8") as handle:
                handle.write("model:\n  num_bands: 60\n")
            with patch.object(paths, "MDX_C_CONFIG_PATH", directory):
                self.assertEqual(
                    mdx_kind_from_names((ckpt, yaml_name)),
                    "mel_band_roformer",
                )

    def test_polarformer_yaml_on_config_path_is_bs_roformer(self) -> None:
        from core import paths

        ckpt = "bs_pope_polarformer.ckpt"
        yaml_name = "bs_pope_polarformer.yaml"
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, yaml_name), "w", encoding="utf-8") as handle:
                handle.write("model:\n  freqs_per_bands: [2, 4, 8, 16]\n")
            with patch.object(paths, "MDX_C_CONFIG_PATH", directory):
                self.assertEqual(
                    mdx_kind_from_names((ckpt, yaml_name)),
                    "bs_roformer",
                )

    def test_filename_hints_still_classify_without_yaml(self) -> None:
        self.assertEqual(
            mdx_kind_from_names(("mel_band_roformer_inst.ckpt",)),
            "mel_band_roformer",
        )

    def test_unlabeled_pair_without_yaml_stays_unknown(self) -> None:
        from core import paths

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(paths, "MDX_C_CONFIG_PATH", directory):
                self.assertIsNone(
                    mdx_kind_from_names(("model.ckpt", "config.yaml")),
                )


class AbbreviatedMdxIdentityTests(unittest.TestCase):
    def test_hybrid_arch_is_complete_when_yaml_exists(self) -> None:
        from core import paths

        ckpt = "mbr_hybrid_arch_aname.ckpt"
        yaml_name = "mbr_hybrid_arch_aname_config.yaml"
        selection, files, entry = _mdx_entry(
            "Roformer Model: Hybrid Arch",
            {ckpt: "http://example.invalid/ckpt", yaml_name: "http://example.invalid/yaml"},
            display="Hybrid Arch · Aname",
            checkpoint=ckpt,
        )
        snapshot = _snapshot(mdx={selection: files}, meta={"mdx": {selection: entry}})
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, yaml_name), "w", encoding="utf-8") as handle:
                handle.write("model:\n  num_bands: 60\n")
            with patch.object(paths, "MDX_C_CONFIG_PATH", directory):
                record = build_identity_index(_repo(), snapshot=snapshot).lookup(
                    "mdx:mbr_hybrid_arch_aname"
                )

        self.assertEqual(record.mdx, MdxSpec("mel_band_roformer"))
        self.assertTrue(record.identity_complete)
        self.assertIsNone(record.identity_error)

    def test_hybrid_arch_is_complete_from_catalogue_label_without_yaml(self) -> None:
        from core import paths

        ckpt = "mbr_hybrid_arch_aname.ckpt"
        yaml_name = "mbr_hybrid_arch_aname_config.yaml"
        selection, files, entry = _mdx_entry(
            "Mel-Band Roformer Hybrid Arch by Aname",
            {ckpt: "http://example.invalid/ckpt", yaml_name: "http://example.invalid/yaml"},
            display="MelBand Roformer — Hybrid Arch · Aname",
            checkpoint=ckpt,
        )
        snapshot = _snapshot(mdx={selection: files}, meta={"mdx": {selection: entry}})
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(paths, "MDX_C_CONFIG_PATH", directory):
                record = build_identity_index(_repo(), snapshot=snapshot).lookup(
                    "mdx:mbr_hybrid_arch_aname"
                )

        self.assertEqual(record.mdx, MdxSpec("mel_band_roformer"))
        self.assertTrue(record.identity_complete)

    def test_polarformer_is_complete_when_yaml_exists(self) -> None:
        from core import paths

        ckpt = "bs_pope_polarformer.ckpt"
        yaml_name = "bs_pope_polarformer.yaml"
        selection, files, entry = _mdx_entry(
            "Roformer Model: PolarFormer Pope",
            {ckpt: "http://example.invalid/ckpt", yaml_name: "http://example.invalid/yaml"},
            display="PolarFormer Pope",
            checkpoint=ckpt,
        )
        snapshot = _snapshot(mdx={selection: files}, meta={"mdx": {selection: entry}})
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, yaml_name), "w", encoding="utf-8") as handle:
                handle.write("model:\n  freqs_per_bands: [2, 4, 8, 16]\n")
            with patch.object(paths, "MDX_C_CONFIG_PATH", directory):
                record = build_identity_index(_repo(), snapshot=snapshot).lookup(
                    "mdx:bs_pope_polarformer"
                )

        self.assertEqual(record.mdx, MdxSpec("bs_roformer"))
        self.assertTrue(record.identity_complete)


if __name__ == "__main__":
    unittest.main()
