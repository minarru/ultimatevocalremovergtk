"""Tests for the mvsepless_resources catalogue merge."""

from __future__ import annotations

import json
import os
import tempfile
import typing
import unittest
from unittest import mock

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core import mvsepless_catalog
from core.catalog_dedupe import dedupe_download_catalogue, primary_checkpoint_name
from core.catalog_sources import _build_meta, _metadata_alias_index
from core.downloads import DownloadManager
from core.mvsepless_catalog import (
    classify_entry,
    clear_mvsepless_cache,
    convert_mvsepless_catalog,
    entry_files,
    merge_mvsepless_catalogues,
    unsupported_mvsepless_downloads,
    url_basename,
)


def _entry(
    *,
    model_type: str,
    full_name: str,
    ckpt: str,
    cfg: str,
    entry_id: str = "sample",
) -> dict:
    base = "https://huggingface.co/noblebarkrr/mvsepless_resources/resolve/main"
    return {
        entry_id: {
            "model_type": model_type,
            "category": "test",
            "id": 1,
            "full_name": full_name,
            "stems": ["vocals", "other"],
            "target_instrument": "vocals",
            "checkpoint_url": f"{base}/{ckpt}?download=true",
            "config_url": f"{base}/{cfg}?download=true",
        }
    }


class UrlBasenameTests(unittest.TestCase):
    def test_strips_query(self) -> None:
        self.assertEqual(
            url_basename("https://example.com/path/mbr_vocals_kim.ckpt?download=true"),
            "mbr_vocals_kim.ckpt",
        )


class ClassifyTests(unittest.TestCase):
    def test_supported_mel_band(self) -> None:
        ok, reason = classify_entry(
            "mbr_vocals_kim",
            {"model_type": "mel_band_roformer", "full_name": "Kim"},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_medley_vox_denied(self) -> None:
        ok, reason = classify_entry("multi_singing", {"model_type": "medley_vox", "full_name": "X"})
        self.assertFalse(ok)
        self.assertIn("Medley-Vox", reason)

    def test_wsa_id_denied(self) -> None:
        ok, reason = classify_entry(
            "mbr_wsa", {"model_type": "mel_band_roformer", "full_name": "WSA"}
        )
        self.assertFalse(ok)
        self.assertIn("Sink", reason)

    def test_skip_connection_ids_supported(self) -> None:
        ok, reason = classify_entry(
            "mbr_4stemxl1_aname",
            {"model_type": "mel_band_roformer", "full_name": "XL"},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_scnet_masked_and_tran_supported(self) -> None:
        for model_type in ("scnet_masked", "scnet_tran"):
            ok, reason = classify_entry(
                f"id_{model_type}",
                {"model_type": model_type, "full_name": model_type},
            )
            self.assertTrue(ok, msg=reason)

    def test_vr_and_mdxnet_denied(self) -> None:
        ok, reason = classify_entry("1_hp-uvr", {"model_type": "vr"})
        self.assertFalse(ok)
        self.assertIn("VR", reason)
        ok, reason = classify_entry("mdx_kim", {"model_type": "mdxnet"})
        self.assertFalse(ok)
        self.assertIn("ONNX", reason)


class ConvertTests(unittest.TestCase):
    def test_duplicate_full_names_are_exact_id_suffixed_independent_of_raw_order(self) -> None:
        entries = {
            "mbr_inst_becruily": next(
                iter(
                    _entry(
                        model_type="mel_band_roformer",
                        full_name="Same Name",
                        ckpt="mel/mbr_inst_becruily.ckpt",
                        cfg="mel/mbr_inst_becruily.yaml",
                        entry_id="mbr_inst_becruily",
                    ).values()
                )
            ),
            "mbr_guitar_becruily": next(
                iter(
                    _entry(
                        model_type="mel_band_roformer",
                        full_name="Same Name",
                        ckpt="mel/mbr_guitar_becruily.ckpt",
                        cfg="mel/mbr_guitar_becruily.yaml",
                        entry_id="mbr_guitar_becruily",
                    ).values()
                )
            ),
        }

        first = convert_mvsepless_catalog(entries)["mdx_download_list"]
        second = convert_mvsepless_catalog(dict(reversed(tuple(entries.items()))))[
            "mdx_download_list"
        ]

        expected = {
            "Same Name [mbr_guitar_becruily]": "mbr_guitar_becruily.ckpt",
            "Same Name [mbr_inst_becruily]": "mbr_inst_becruily.ckpt",
        }
        for converted in (first, second):
            self.assertEqual(
                {label: primary_checkpoint_name(files) for label, files in converted.items()},
                expected,
            )

    def test_dedupe_keeps_politrees_and_both_exact_duplicate_name_artifacts(self) -> None:
        entries = {
            "mbr_inst_becruily": next(
                iter(
                    _entry(
                        model_type="mel_band_roformer",
                        full_name="Same Name",
                        ckpt="mel/mbr_inst_becruily.ckpt",
                        cfg="mel/mbr_inst_becruily.yaml",
                        entry_id="mbr_inst_becruily",
                    ).values()
                )
            ),
            "mbr_guitar_becruily": next(
                iter(
                    _entry(
                        model_type="mel_band_roformer",
                        full_name="Same Name",
                        ckpt="mel/mbr_guitar_becruily.ckpt",
                        cfg="mel/mbr_guitar_becruily.yaml",
                        entry_id="mbr_guitar_becruily",
                    ).values()
                )
            ),
        }
        politrees = {"Roformer Model: Same Name": {"politrees.ckpt": "https://p/politrees.ckpt"}}

        for raw in (entries, dict(reversed(tuple(entries.items())))):
            converted = convert_mvsepless_catalog(raw)
            _vr, merged, _demucs = merge_mvsepless_catalogues(
                {}, politrees, {}, converted=converted
            )
            kept = dedupe_download_catalogue(merged)
            self.assertEqual(
                {primary_checkpoint_name(files) for files in kept.values()},
                {"politrees.ckpt", "mbr_inst_becruily.ckpt", "mbr_guitar_becruily.ckpt"},
            )

    def test_ambiguous_normalized_metadata_alias_is_not_selected_by_order(self) -> None:
        metadata = {
            "Roformer Model: Same Name": {"entry_id": "politrees", "stems": ["Vocals"]},
            "Same Name": {"entry_id": "mvsepless", "stems": ["Guitar"]},
        }

        aliases = _metadata_alias_index(metadata)
        built = _build_meta(
            {"Same Name": {"exact.ckpt": "https://x/exact.ckpt"}},
            MDX_ARCH_TYPE,
            metadata,
            aliases,
        )

        self.assertNotIn("same name", aliases)
        self.assertEqual(built["Same Name"].stems, ["Guitar"])

    def test_supported_types_land_in_mdx_list(self) -> None:
        for model_type, ckpt, cfg in (
            ("mel_band_roformer", "a.ckpt", "a_config.yaml"),
            ("bs_roformer", "b.ckpt", "b_config.yaml"),
            ("mdx23c", "c.ckpt", "c_config.yaml"),
            ("scnet", "d.ckpt", "d_config.yaml"),
            ("bandit", "e.ckpt", "e_config.yaml"),
            ("bandit_v2", "f.ckpt", "f_config.yaml"),
            ("scnet_masked", "g.ckpt", "g_config.yaml"),
            ("scnet_tran", "h.ckpt", "h_config.yaml"),
        ):
            with self.subTest(model_type=model_type):
                raw = _entry(
                    model_type=model_type,
                    full_name=f"Label {model_type}",
                    ckpt=f"dir/{ckpt}",
                    cfg=f"dir/{cfg}",
                    entry_id=model_type,
                )
                converted = convert_mvsepless_catalog(raw)
                self.assertIn(f"Label {model_type}", converted["mdx_download_list"])
                files = converted["mdx_download_list"][f"Label {model_type}"]
                self.assertEqual(set(files), {ckpt, cfg})
                self.assertTrue(all(u.startswith("https://") for u in files.values()))

    def test_unsupported_collected_by_arch(self) -> None:
        raw = {}
        raw.update(
            _entry(
                model_type="vr",
                full_name="VR Sample",
                ckpt="vr/x.ckpt",
                cfg="vr/x_config.yaml",
                entry_id="vr1",
            )
        )
        raw.update(
            _entry(
                model_type="htdemucs",
                full_name="Demucs Sample",
                ckpt="htdemucs/y.ckpt",
                cfg="htdemucs/y_config.yaml",
                entry_id="ht1",
            )
        )
        raw.update(
            _entry(
                model_type="medley_vox",
                full_name="Medley Sample",
                ckpt="medley_vox/z.ckpt",
                cfg="medley_vox/z_config.yaml",
                entry_id="mv1",
            )
        )
        converted = convert_mvsepless_catalog(raw)
        self.assertEqual(converted["mdx_download_list"], {})
        unsupported = converted["unsupported"]
        self.assertTrue(any(label == "VR Sample" for label, _ in unsupported[VR_ARCH_TYPE]))
        self.assertTrue(any(label == "Demucs Sample" for label, _ in unsupported[DEMUCS_ARCH_TYPE]))
        self.assertTrue(any(label == "Medley Sample" for label, _ in unsupported[MDX_ARCH_TYPE]))

    def test_entry_files_rejects_path_traversal(self) -> None:
        self.assertIsNone(
            entry_files(
                {
                    "checkpoint_url": "https://x.example/../../evil.ckpt",
                    "config_url": "https://x.example/ok.yaml",
                }
            )
        )

    def test_supported_duplicate_names_keep_every_checkpoint(self) -> None:
        raw = {}
        raw.update(
            _entry(
                model_type="mel_band_roformer",
                full_name="Duplicate Friendly Name",
                ckpt="mel/first.ckpt",
                cfg="mel/first.yaml",
                entry_id="first_id",
            )
        )
        raw.update(
            _entry(
                model_type="mel_band_roformer",
                full_name="Duplicate Friendly Name",
                ckpt="mel/second.ckpt",
                cfg="mel/second.yaml",
                entry_id="second_id",
            )
        )

        converted = convert_mvsepless_catalog(raw)

        self.assertEqual(
            list(converted["mdx_download_list"]),
            [
                "Duplicate Friendly Name [first_id]",
                "Duplicate Friendly Name [second_id]",
            ],
        )
        self.assertEqual(
            converted["metadata"]["Duplicate Friendly Name [second_id]"]["entry_id"],
            "second_id",
        )

    def test_unsupported_duplicate_names_collapse_to_one_row(self) -> None:
        raw = {}
        for entry_id in ("demucs_a", "demucs_b"):
            raw.update(
                _entry(
                    model_type="htdemucs",
                    full_name="Same Unsupported Demucs",
                    ckpt=f"htdemucs/{entry_id}.ckpt",
                    cfg=f"htdemucs/{entry_id}.yaml",
                    entry_id=entry_id,
                )
            )

        converted = convert_mvsepless_catalog(raw)

        self.assertEqual(
            converted["unsupported"][DEMUCS_ARCH_TYPE],
            [("Same Unsupported Demucs", "MSST Demucs single-ckpt format not supported")],
        )

    def test_known_cross_arch_checkpoint_record_is_quarantined(self) -> None:
        raw = _entry(
            model_type="scnet",
            full_name="SCNet Mid-Side by Gilliaaan",
            ckpt="mdx23c/mdx23c_mid_side_gilliaaan.ckpt",
            cfg="scnet/scnet_mid_side_gilliaaan.yaml",
            entry_id="scnet_mid_side_gilliaaan",
        )

        converted = convert_mvsepless_catalog(raw)

        self.assertEqual(converted["mdx_download_list"], {})
        self.assertNotIn("SCNet Mid-Side by Gilliaaan", converted["metadata"])


class MergeTests(unittest.TestCase):
    def test_upstream_labels_win(self) -> None:
        converted = {
            "vr_download_list": {},
            "mdx_download_list": {
                "Shared": {"mine.ckpt": "https://x/mine.ckpt", "mine.yaml": "https://x/mine.yaml"}
            },
            "demucs_download_list": {},
            "unsupported": {},
            "unsupported_labels": {},
        }
        mdx = {"Shared": {"upstream.ckpt": "https://up/upstream.ckpt"}}
        _vr, merged, _demucs = merge_mvsepless_catalogues({}, mdx, {}, converted)
        self.assertEqual(merged["Shared"]["upstream.ckpt"], "https://up/upstream.ckpt")

    def test_new_labels_added(self) -> None:
        converted = {
            "vr_download_list": {},
            "mdx_download_list": {
                "New Mel": {"n.ckpt": "https://x/n.ckpt", "n.yaml": "https://x/n.yaml"}
            },
            "demucs_download_list": {},
            "unsupported": {},
            "unsupported_labels": {},
        }
        _vr, merged, _demucs = merge_mvsepless_catalogues({}, {}, {}, converted)
        self.assertIn("New Mel", merged)

    def test_unsupported_omits_existing_labels(self) -> None:
        converted = {
            "unsupported": {
                MDX_ARCH_TYPE: [
                    ("Keep Me", "reason"),
                    ("Already Upstream", "reason"),
                ]
            },
            "unsupported_labels": {
                "Keep Me": "reason",
                "Already Upstream": "reason",
            },
        }
        rows = unsupported_mvsepless_downloads(converted, existing_labels={"Already Upstream": {}})
        labels = [label for label, _ in rows.get(MDX_ARCH_TYPE, [])]
        self.assertEqual(labels, ["Keep Me"])


class DisableEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_mvsepless_cache()

    def tearDown(self) -> None:
        clear_mvsepless_cache()

    def test_disable_env_skips_load(self) -> None:
        with mock.patch.dict(os.environ, {"UVR_DISABLE_MVSEPLESS": "1"}):
            clear_mvsepless_cache()
            self.assertIsNone(mvsepless_catalog.load_mvsepless_models())


class DownloadManagerMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_mvsepless_cache()
        self.manager = DownloadManager()

    def tearDown(self) -> None:
        clear_mvsepless_cache()

    @mock.patch("core.catalog_sources.merge_mvsepless_catalogues")
    @mock.patch("core.downloads.unsupported_mvsepless_downloads")
    @mock.patch("core.catalog_sources.merge_extra_catalogues")
    @mock.patch("core.catalog_sources.load_politrees_links", return_value=None)
    def test_merge_calls_mvsepless(
        self,
        _politrees: typing.Any,
        mock_extra: typing.Any,
        mock_unsupported: typing.Any,
        mock_merge: typing.Any,
    ) -> None:
        mock_extra.side_effect = lambda vr, mdx, demucs: (dict(vr), dict(mdx), dict(demucs))
        mock_merge.side_effect = lambda vr, mdx, demucs, **_kwargs: (
            dict(vr),
            {**mdx, "Mvsepless Mel": {"a.ckpt": "https://x/a.ckpt"}},
            dict(demucs),
        )
        mock_unsupported.return_value = {MDX_ARCH_TYPE: [("Broken", "not ported")]}
        from core.catalog_sources import invalidate_catalogue_merge

        invalidate_catalogue_merge()
        self.manager.mdx_download_list = {}
        self.manager._merge_politrees_supplement(allow_network=False)
        mock_merge.assert_called_once()
        self.assertIn("Mvsepless Mel", self.manager.mdx_download_list)
        self.assertEqual(self.manager.unsupported_downloads()[MDX_ARCH_TYPE][0][0], "Broken")

    def test_resolve_blocks_unsupported_only(self) -> None:
        self.manager.mdx_download_list = {}
        with mock.patch(
            "core.downloads.unsupported_reason_for_label",
            return_value="Medley-Vox engine not ported",
        ):
            with self.assertRaises(ValueError) as ctx:
                self.manager.resolve("Medley Sample", MDX_ARCH_TYPE)
        self.assertIn("not downloadable", str(ctx.exception))

    def test_resolve_blocks_from_merged_unsupported_list(self) -> None:
        self.manager.mdx_download_list = {}
        self.manager.unsupported_download_list = {
            MDX_ARCH_TYPE: [("Medley Sample", "Medley-Vox engine not ported")]
        }
        with (
            mock.patch("core.mvsepless_catalog._urlopen") as opener,
            self.assertRaises(ValueError) as ctx,
        ):
            self.manager.resolve("Medley Sample", MDX_ARCH_TYPE)
        self.assertIn("not downloadable", str(ctx.exception))
        opener.assert_not_called()

    def test_resolve_prefers_real_catalogue_entry(self) -> None:
        self.manager.mdx_download_list = {
            "Shared Label": {
                "x.ckpt": "https://example.com/x.ckpt",
                "x.yaml": "https://example.com/x.yaml",
            }
        }
        with mock.patch(
            "core.downloads.unsupported_reason_for_label",
            return_value="would block if consulted first",
        ):
            jobs = self.manager.resolve("Shared Label", MDX_ARCH_TYPE)
        self.assertEqual(len(jobs), 2)


class DiskCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_mvsepless_cache()

    def tearDown(self) -> None:
        clear_mvsepless_cache()

    def test_fetch_failure_uses_disk_cache(self) -> None:
        payload = _entry(
            model_type="mel_band_roformer",
            full_name="Cached Mel",
            ckpt="mel/a.ckpt",
            cfg="mel/a_config.yaml",
            entry_id="cached",
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = os.path.join(tmp, "mvsepless_models.json")
            with open(cache_path, "w", encoding="utf-8") as handle:
                json.dump({"fetched_at": 1.0, "data": payload}, handle)
            with mock.patch.dict(os.environ, {"UVR_DISABLE_MVSEPLESS": "0"}, clear=False):
                with mock.patch("core.mvsepless_catalog._cache_path", return_value=cache_path):
                    with mock.patch(
                        "core.mvsepless_catalog._urlopen",
                        side_effect=OSError("offline"),
                    ):
                        clear_mvsepless_cache()
                        loaded = mvsepless_catalog.load_mvsepless_models(force=True)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertIn("cached", loaded)


class CategoryTranslationTests(unittest.TestCase):
    def test_known_categories_translate_with_intent(self) -> None:
        from core.model_stem_semantics import (
            INTENT_KARAOKE,
            INTENT_MULTI_STEM,
            INTENT_VOCALS,
        )
        from core.mvsepless_catalog import translate_category

        self.assertEqual(
            translate_category("\u0412\u043e\u043a\u0430\u043b"), ("Vocals", INTENT_VOCALS)
        )
        self.assertEqual(
            translate_category("\u041a\u0430\u0440\u0430\u043e\u043a\u0435"),
            ("Karaoke", INTENT_KARAOKE),
        )
        self.assertEqual(
            translate_category("4 \u0441\u0442\u0435\u043c\u0430"), ("4 stems", INTENT_MULTI_STEM)
        )

    def test_drums_and_bass_categories_are_specialty_extractors(self) -> None:
        from core.model_stem_semantics import INTENT_DRUM_BASS_SEP, INTENT_SPECIALTY_STEM
        from core.mvsepless_catalog import translate_category

        self.assertEqual(translate_category("Ударные"), ("Drums", INTENT_SPECIALTY_STEM))
        self.assertEqual(translate_category("Бас"), ("Bass", INTENT_SPECIALTY_STEM))
        self.assertEqual(translate_category("Басс"), ("Bass", INTENT_SPECIALTY_STEM))
        self.assertEqual(translate_category("DrumSep"), ("DrumSep", INTENT_DRUM_BASS_SEP))


class MetadataSidecarTests(unittest.TestCase):
    def test_supported_entry_keeps_stems_and_target(self) -> None:
        from core.model_stem_semantics import INTENT_VOCALS

        converted = convert_mvsepless_catalog(
            {
                "mbr_x": {
                    "model_type": "mel_band_roformer",
                    "category": "\u0412\u043e\u043a\u0430\u043b",
                    "full_name": "Mel-Band Roformer X by Someone",
                    "stems": ["Vocals", "other"],
                    "target_instrument": "Vocals",
                    "checkpoint_url": "https://example.invalid/a/mbr_x.ckpt",
                    "config_url": "https://example.invalid/a/mbr_x.yaml",
                }
            }
        )
        meta = converted["metadata"]["Mel-Band Roformer X by Someone"]
        self.assertEqual(meta["stems"], ["Vocals", "other"])
        self.assertEqual(meta["target_instrument"], "Vocals")
        self.assertEqual(meta["category_en"], "Vocals")
        self.assertEqual(meta["intent"], INTENT_VOCALS)
        self.assertEqual(meta["entry_id"], "mbr_x")

    def test_unsupported_entry_also_gets_metadata(self) -> None:
        converted = convert_mvsepless_catalog(
            {
                "mbr_wsa": {
                    "model_type": "mel_band_roformer",
                    "category": "\u0412\u043e\u043a\u0430\u043b",
                    "full_name": "WSA Mel-Band Roformer",
                    "stems": ["other", "vocals"],
                    "target_instrument": "vocals",
                    "checkpoint_url": "https://example.invalid/a/mbr_wsa.ckpt",
                    "config_url": "https://example.invalid/a/mbr_wsa.yaml",
                }
            }
        )
        self.assertIn("WSA Mel-Band Roformer", converted["metadata"])


if __name__ == "__main__":
    unittest.main()
