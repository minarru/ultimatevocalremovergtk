"""Tests for Download Center catalogue deduplication."""

from __future__ import annotations

import typing
import unittest
from unittest import mock

from bundled.constants import MDX_ARCH_TYPE
from core.catalog_dedupe import (
    dedupe_download_catalogue,
    normalize_catalogue_label,
    normalize_checkpoint_url,
    primary_checkpoint_name,
    primary_checkpoint_url,
)
from core.downloads import DownloadManager
from core.mvsepless_catalog import unsupported_mvsepless_downloads


class NormalizeLabelTests(unittest.TestCase):
    def test_strips_roformer_prefix_and_punctuation(self) -> None:
        upstream = "Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen"
        mvsepless = "Mel-Band Roformer Vocals by Kimberley Jensen"
        self.assertEqual(
            normalize_catalogue_label(upstream),
            normalize_catalogue_label(mvsepless),
        )

    def test_instvoc_variants_match(self) -> None:
        a = normalize_catalogue_label("MDX23C Model: MDX23C-InstVoc HQ")
        b = normalize_catalogue_label("MDX23C Inst-Voc HQ")
        self.assertEqual(a, b)

    def test_deecho_hyphen_variants(self) -> None:
        a = normalize_catalogue_label("VR Arch Single Model v5: UVR-De-Echo-Normal by FoxJoy")
        b = normalize_catalogue_label("VR Arch Single Model v5: UVR-DeEcho-Normal by FoxJoy")
        self.assertEqual(a, b)

    def test_scnet_prefix_and_inline_family_variants_match(self) -> None:
        curated = normalize_catalogue_label(
            "SCnet: 4-stems Huge SCNet Fullness by Aname"
        )
        mvsepless = normalize_catalogue_label(
            "SCNet 4 Stems Huge Fullness by Aname"
        )
        self.assertEqual(curated, mvsepless)

    def test_hq_variant_remains_distinct(self) -> None:
        regular = normalize_catalogue_label("MDX-Net Model: UVR-MDX-NET Inst 1")
        hq = normalize_catalogue_label("MDX-Net Model: UVR-MDX-NET Inst HQ 1")
        self.assertNotEqual(regular, hq)

    def test_plus_variant_matches_written_plus_but_not_base(self) -> None:
        symbol = normalize_catalogue_label("Mel-Band Roformer Instrumental v1+")
        written = normalize_catalogue_label("Mel-Band Roformer Instrumental v1 Plus")
        base = normalize_catalogue_label("Mel-Band Roformer Instrumental v1")
        self.assertEqual(symbol, written)
        self.assertNotEqual(symbol, base)


class PrimaryCheckpointTests(unittest.TestCase):
    def test_dict_skips_yaml(self) -> None:
        self.assertEqual(
            primary_checkpoint_name(
                {"a.yaml": "https://x/a.yaml", "a.ckpt": "https://x/a.ckpt"}
            ),
            "a.ckpt",
        )

    def test_plain_filename(self) -> None:
        self.assertEqual(primary_checkpoint_name("1_HP-UVR.pth"), "1_HP-UVR.pth")


class NormalizeCheckpointUrlTests(unittest.TestCase):
    def test_strips_download_query(self) -> None:
        a = "https://hf.co/x/a.ckpt?download=true"
        b = "https://hf.co/x/a.ckpt"
        self.assertEqual(normalize_checkpoint_url(a), normalize_checkpoint_url(b))

    def test_keeps_other_query_params(self) -> None:
        url = "https://hf.co/x/a.ckpt?revision=main&download=true"
        self.assertEqual(
            normalize_checkpoint_url(url),
            "https://hf.co/x/a.ckpt?revision=main",
        )


class PrimaryCheckpointUrlTests(unittest.TestCase):
    def test_skips_yaml(self) -> None:
        self.assertEqual(
            primary_checkpoint_url(
                {
                    "a.yaml": "https://x/a.yaml",
                    "a.ckpt": "https://x/a.ckpt?download=true",
                }
            ),
            "https://x/a.ckpt",
        )


class DedupeCatalogueTests(unittest.TestCase):
    def test_keeps_first_checkpoint_collision(self) -> None:
        catalogue = {
            "Upstream Label": {"shared.ckpt": "https://up/shared.ckpt"},
            "Duplicate Label": {"shared.ckpt": "https://mv/shared.ckpt"},
            "Unique": {"other.ckpt": "https://x/other.ckpt"},
        }
        out = dedupe_download_catalogue(catalogue)
        self.assertEqual(list(out), ["Upstream Label", "Unique"])
        self.assertEqual(out["Upstream Label"]["shared.ckpt"], "https://up/shared.ckpt")

    def test_keeps_first_normalized_label_collision(self) -> None:
        catalogue = {
            "Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen": {
                "kim_up.ckpt": "https://up/kim.ckpt"
            },
            "Mel-Band Roformer Vocals by Kimberley Jensen": {
                "mbr_vocals_kim.ckpt": "https://mv/mbr_vocals_kim.ckpt"
            },
        }
        out = dedupe_download_catalogue(catalogue)
        self.assertEqual(list(out), list(catalogue)[:1])

    def test_drops_scnet_cross_source_alias(self) -> None:
        catalogue = {
            "SCnet: 4-stems Huge SCNet Fullness by Aname": {
                "huge_scnet_4stems_fullness.ckpt": "https://curated/fullness.ckpt"
            },
            "SCNet 4 Stems Huge Fullness by Aname": {
                "scnet_huge_4stem_fullness_aname.ckpt": "https://mv/fullness.ckpt"
            },
        }
        out = dedupe_download_catalogue(catalogue)
        self.assertEqual(list(out), list(catalogue)[:1])

    def test_casefold_checkpoint_collision(self) -> None:
        catalogue = {
            "A": {"Model.ckpt": "https://a"},
            "B": {"model.ckpt": "https://b"},
        }
        out = dedupe_download_catalogue(catalogue)
        self.assertEqual(list(out), ["A"])

    def test_demucs_bags_dedupe_identical_maps_only(self) -> None:
        bag = {
            "a.th": "https://x/a.th",
            "bag.yaml": "https://x/bag.yaml",
        }
        shared_member = {
            "a.th": "https://x/a.th",
            "other.yaml": "https://x/other.yaml",
        }
        catalogue = {
            "Bag A": bag,
            "Bag A copy": dict(bag),
            "Bag B shares file": shared_member,
        }
        out = dedupe_download_catalogue(catalogue, demucs_bags=True)
        self.assertEqual(list(out), ["Bag A", "Bag B shares file"])

    def test_keeps_first_normalized_url_collision(self) -> None:
        catalogue = {
            "Bleedless": {
                "a.ckpt": "https://hf.co/x/fullness.ckpt?download=true",
                "a.yaml": "https://hf.co/x/a.yaml",
            },
            "Fullness": {
                "b.ckpt": "https://hf.co/x/fullness.ckpt",
                "b.yaml": "https://hf.co/x/b.yaml",
            },
        }
        out = dedupe_download_catalogue(catalogue)
        self.assertEqual(list(out), ["Bleedless"])

    def test_same_url_prefers_checkpoint_name_matching_remote(self) -> None:
        url = "https://hf.co/x/mel_band_roformer_vocals_fullness_aname.ckpt"
        catalogue = {
            "Vocals Bleedless": {
                "melband_roformer_vocals_bleedness_by_aname.ckpt": url,
            },
            "Vocals Fullness": {
                "mel_band_roformer_vocals_fullness_aname.ckpt": url,
            },
        }
        out = dedupe_download_catalogue(catalogue)
        self.assertEqual(list(out), ["Vocals Fullness"])

    def test_keeps_first_content_id_collision(self) -> None:
        catalogue = {
            "HyperACE official": {
                "bs_roformer_inst_hyperacev2.ckpt": "https://pcunwa/v2_inst.ckpt",
            },
            "HyperACE finetuned alias": {
                "bs_inst_hyperace2_unwa.ckpt": "https://mvsepless/hyperace2.ckpt",
            },
        }
        content_ids = {
            "https://pcunwa/v2_inst.ckpt": "etag-same",
            "https://mvsepless/hyperace2.ckpt": "etag-same",
        }
        out = dedupe_download_catalogue(catalogue, content_ids=content_ids)
        self.assertEqual(list(out), ["HyperACE official"])

    def test_demucs_ignores_url_and_content_ids(self) -> None:
        bag_a = {"a.th": "https://x/a.th", "a.yaml": "https://x/a.yaml"}
        bag_b = {"a.th": "https://x/a.th", "b.yaml": "https://x/b.yaml"}
        out = dedupe_download_catalogue(
            {"Bag A": bag_a, "Bag B": bag_b},
            demucs_bags=True,
            content_ids={"https://x/a.th": "shared"},
        )
        self.assertEqual(list(out), ["Bag A", "Bag B"])


class UnsupportedNormFilterTests(unittest.TestCase):
    def test_unsupported_skips_normalized_upstream_label(self) -> None:
        converted = {
            "unsupported": {
                MDX_ARCH_TYPE: [
                    ("Mel-Band Roformer Vocals by Kimberley Jensen", "needs bridge"),
                    ("Truly Missing", "needs bridge"),
                ]
            }
        }
        existing = {
            "Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen": {
                "x.ckpt": "https://up/x.ckpt"
            }
        }
        rows = unsupported_mvsepless_downloads(converted, existing_labels=existing)
        labels = [label for label, _ in rows.get(MDX_ARCH_TYPE, [])]
        self.assertEqual(labels, ["Truly Missing"])


class DownloadManagerDedupeTests(unittest.TestCase):
    @mock.patch("core.downloads.unsupported_mvsepless_downloads", return_value={})
    @mock.patch("core.catalog_sources.merge_mvsepless_catalogues")
    @mock.patch("core.catalog_sources.merge_extra_catalogues")
    @mock.patch("core.catalog_sources.load_politrees_links", return_value=None)
    def test_merge_dedupes_checkpoint_collisions(
        self,
        _politrees: typing.Any,
        mock_extra: typing.Any,
        mock_mv: typing.Any,
        _unsupported: typing.Any,
    ) -> None:
        mock_extra.side_effect = lambda vr, mdx, demucs: (dict(vr), dict(mdx), dict(demucs))
        mock_mv.side_effect = lambda vr, mdx, demucs, **_kwargs: (
            dict(vr),
            {
                "First": {"same.ckpt": "https://a/same.ckpt"},
                "Second": {"same.ckpt": "https://b/same.ckpt"},
                "Mel-Band Roformer Vocals by Kimberley Jensen": {
                    "mbr.ckpt": "https://m/mbr.ckpt"
                },
                "Roformer Model: MelBand Roformer | Vocals by Kimberley Jensen": {
                    "kim.ckpt": "https://k/kim.ckpt"
                },
            },
            dict(demucs),
        )
        manager = DownloadManager()
        manager.mdx_download_list = {}
        manager._merge_politrees_supplement()
        self.assertIn("First", manager.mdx_download_list)
        self.assertNotIn("Second", manager.mdx_download_list)
        # First normalized label wins (dict order from mock_mv).
        labels = list(manager.mdx_download_list)
        kim_labels = [label for label in labels if "Kimberley" in label]
        self.assertEqual(len(kim_labels), 1)


if __name__ == "__main__":
    unittest.main()
