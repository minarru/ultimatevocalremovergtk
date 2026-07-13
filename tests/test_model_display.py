"""Tests for unified model display naming."""

import unittest
from unittest.mock import MagicMock

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE

from core.model_display import (
    build_demucs_display_index,
    build_vr_display_index,
    display_name_for_basename,
    format_tag_subtitle,
    format_tag_title,
    lookup_mapper_display,
    parse_model_tag,
    resolve_mapper_basename,
    resolve_vr_model_basename,
    sanitize_catalogue_label,
    sanitize_demucs_catalogue_label,
    sanitize_vr_catalogue_label,
)


class SanitizeCatalogueLabelTests(unittest.TestCase):
    def test_strips_mdx_net_model_prefix(self) -> None:
        self.assertEqual(
            sanitize_catalogue_label("MDX-Net Model: UVR-MDX-NET Main"),
            "UVR-MDX-NET Main",
        )

    def test_keeps_community_author_suffix(self) -> None:
        label = "Roformer Model: MelBand Roformer Kim | FT v2 by Unwa"
        self.assertEqual(
            sanitize_catalogue_label(label),
            "MelBand Roformer Kim | FT v2 by Unwa",
        )


class SanitizeVrCatalogueLabelTests(unittest.TestCase):
    def test_strips_single_model_prefix(self) -> None:
        self.assertEqual(
            sanitize_vr_catalogue_label("VR Arch Single Model v5: 1_HP-UVR"),
            "v5: 1_HP-UVR",
        )


class SanitizeDemucsCatalogueLabelTests(unittest.TestCase):
    def test_converts_to_mapper_style(self) -> None:
        self.assertEqual(
            sanitize_demucs_catalogue_label("Demucs v4: htdemucs"),
            "v4 | htdemucs",
        )


class MapperLookupTests(unittest.TestCase):
    def test_exact_key_beats_substring(self) -> None:
        mapper = {
            "Kim_Vocal_1": "Kim Vocal 1",
            "Kim_Vocal_10": "Kim Vocal 10",
        }
        self.assertEqual(lookup_mapper_display("Kim_Vocal_1", mapper), "Kim Vocal 1")
        self.assertEqual(resolve_mapper_basename("Kim Vocal 1", mapper), "Kim_Vocal_1")

    def test_exact_stem_match(self) -> None:
        mapper = {"model.ckpt": "Display Name"}
        self.assertEqual(lookup_mapper_display("model", mapper), "Display Name")


class VrDisplayIndexTests(unittest.TestCase):
    def test_maps_flat_vr_catalogue_entry(self) -> None:
        catalogues = [{"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"}]
        index = build_vr_display_index(catalogues)
        self.assertEqual(index["1_HP-UVR"], "v5: 1_HP-UVR")


class DemucsDisplayIndexTests(unittest.TestCase):
    def test_maps_yaml_stem(self) -> None:
        catalogues = [
            {
                "Demucs v4: htdemucs": {
                    "htdemucs.yaml": "https://example.com/htdemucs.yaml",
                }
            }
        ]
        index = build_demucs_display_index(catalogues)
        self.assertEqual(index["htdemucs"], "v4 | htdemucs")


class ParseModelTagTests(unittest.TestCase):
    def test_splits_on_first_colon_space_only(self) -> None:
        tag = "VR Arc: v5: 1_HP-UVR"
        self.assertEqual(parse_model_tag(tag), ("VR Arc", "v5: 1_HP-UVR"))

    def test_format_tag_subtitle_returns_arch(self) -> None:
        self.assertEqual(format_tag_subtitle("MDX-Net: Kim Vocal 2"), "MDX-Net")


class FormatTagTitleTests(unittest.TestCase):
    def test_uses_repo_display_helper(self) -> None:
        repo = MagicMock()
        repo.mdx_name_select_MAPPER = {"Kim_Vocal_2": "Kim Vocal 2"}
        repo.mdx_catalogue_display_index.return_value = {}
        title = format_tag_title("MDX-Net: Kim Vocal 2", repo)
        self.assertEqual(title, "Kim Vocal 2")


class ResolveVrModelBasenameTests(unittest.TestCase):
    def test_resolves_sanitized_display(self) -> None:
        index = {"1_HP-UVR": "v5: 1_HP-UVR"}
        self.assertEqual(
            resolve_vr_model_basename("v5: 1_HP-UVR", catalogue_index=index),
            "1_HP-UVR",
        )

    def test_resolves_upstream_catalogue_key(self) -> None:
        index = {"1_HP-UVR": "v5: 1_HP-UVR"}
        self.assertEqual(
            resolve_vr_model_basename(
                "VR Arch Single Model v5: 1_HP-UVR",
                catalogue_index=index,
            ),
            "1_HP-UVR",
        )


class DisplayNameForBasenameTests(unittest.TestCase):
    def test_mapper_priority_over_catalogue(self) -> None:
        mapper = {"known": "Mapper Name"}
        catalogue = {"known": "Catalogue Name"}
        self.assertEqual(
            display_name_for_basename("known", mapper, catalogue_index=catalogue),
            "Mapper Name",
        )


if __name__ == "__main__":
    unittest.main()
