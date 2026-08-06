"""The single merge path shared by Download Center and the runtime pickers."""

import os
import typing
import unittest
import unittest.mock

from core import catalog_sources

#: ``_supplemental_sources`` takes no arguments and returns supplements only,
#: so patching it leaves the real base merge under test.
_NO_SUPPLEMENTS = ({}, {}, {}, {})

# Merges still see curated Apollo YAML URLs; keep the stem-cache worker off
# unless a test is specifically about it (see test_catalog_stem_merge).
_STEM_CACHE_OFF = unittest.mock.patch.dict(
    os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}, clear=False
)


def _with_supplements(supplements: typing.Any) -> typing.Any:
    return unittest.mock.patch.object(
        catalog_sources, "_supplemental_sources", return_value=supplements
    )


@_STEM_CACHE_OFF
class MergeOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_upstream_label_is_never_overwritten(self) -> None:
        with _with_supplements(({}, {"Shared": {"other.ckpt": "u2"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"Shared": {"first.ckpt": "u1"}}, demucs={}
            )
        self.assertEqual(merged.mdx["Shared"], {"first.ckpt": "u1"})

    def test_supplemental_entries_are_added(self) -> None:
        with _with_supplements(({}, {"New": {"new.ckpt": "u2"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertIn("New", merged.mdx)

    def test_base_and_supplement_both_survive(self) -> None:
        with _with_supplements(({}, {"FromSupplement": {"b.ckpt": "u"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"FromBase": {"a.ckpt": "u"}}, demucs={}
            )
        self.assertEqual(set(merged.mdx), {"FromBase", "FromSupplement"})

    def test_vr_and_demucs_merge_independently(self) -> None:
        with _with_supplements(({"V": "v.pth"}, {}, {"D": {"d.yaml": "u"}}, {})):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertIn("V", merged.vr)
        self.assertIn("D", merged.demucs)


@_STEM_CACHE_OFF
class EntryMetaTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_meta_carries_canonical_display_and_checkpoint(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={},
                mdx={"Roformer Model: Mel-Band Roformer | Inst v2 by Unwa":
                     {"mbr_inst2_unwa.ckpt": "u", "mbr_inst2_unwa.yaml": "c"}},
                demucs={},
            )
        meta = merged.meta["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        self.assertEqual(meta.display, "MelBand Roformer — Inst v2 · Unwa")
        self.assertEqual(meta.checkpoint, "mbr_inst2_unwa.ckpt")
        self.assertEqual(meta.files["mbr_inst2_unwa.yaml"], "c")

    def test_mvsepless_metadata_reaches_meta(self) -> None:
        with _with_supplements(
            ({}, {"M": {"m.ckpt": "u", "m.yaml": "c"}}, {},
             {"M": {"stems": ["Vocals", "other"],
                    "target_instrument": "Vocals",
                    "intent": "vocals"}})
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, ["Vocals", "other"])
        self.assertEqual(meta.target_instrument, "Vocals")

    def test_entry_without_mvsepless_metadata_still_gets_meta(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"Plain": {"p.ckpt": "u"}}, demucs={}
            )
        meta = merged.meta["Plain"]
        self.assertEqual(meta.stems, [])
        self.assertIsNone(meta.target_instrument)

    def test_vr_plain_string_value_becomes_a_files_map(self) -> None:
        # VR catalogue entries are bare filenames, not {file: url} dicts.
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"}, mdx={}, demucs={}
            )
        meta = merged.meta["VR Arch Single Model v5: 1_HP-UVR"]
        self.assertEqual(meta.checkpoint, "1_HP-UVR.pth")

    def test_meta_covers_every_arch(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={"V": "v.pth"}, mdx={"M": {"m.ckpt": "u"}}, demucs={"D": {"d.yaml": "u"}}
            )
        for label in ("V", "M", "D"):
            with self.subTest(label=label):
                self.assertIn(label, merged.meta)


@_STEM_CACHE_OFF
class MergeCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_second_identical_merge_is_cached(self) -> None:
        supplements = ({}, {"New": {"new.ckpt": "https://x/new.ckpt"}}, {}, {})
        with _with_supplements(supplements):
            with unittest.mock.patch.object(
                catalog_sources, "dedupe_download_catalogue",
                wraps=catalog_sources.dedupe_download_catalogue,
            ) as dedupe:
                first = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
                calls_after_first = dedupe.call_count
                second = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertIs(first, second)
        self.assertGreater(calls_after_first, 0)
        self.assertEqual(dedupe.call_count, calls_after_first)

    def test_invalidate_forces_rebuild(self) -> None:
        supplements = ({}, {"New": {"new.ckpt": "https://x/new.ckpt"}}, {}, {})
        with _with_supplements(supplements):
            with unittest.mock.patch.object(
                catalog_sources, "dedupe_download_catalogue",
                wraps=catalog_sources.dedupe_download_catalogue,
            ) as dedupe:
                catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
                calls_after_first = dedupe.call_count
                catalog_sources.invalidate_catalogue_merge()
                catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertGreater(dedupe.call_count, calls_after_first)


@_STEM_CACHE_OFF
class MergePriorityDedupeTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_extras_hyperace_wins_over_mvsepless_same_etag(self) -> None:
        # Simulate post-supplement catalogue order: extras label first, then
        # mvsepless alias — content_ids make them collide.
        extras_label = (
            "Roformer Model: BandSplit Roformer | HyperACE v2 Instrumental by Unwa"
        )
        mv_label = (
            "BS Roformer Instrumental HyperACE v2 "
            "(finetuned anvuew vocal model) by Unwa"
        )
        mdx = {
            extras_label: {
                "bs_roformer_inst_hyperacev2.ckpt": "https://pcunwa/v2_inst.ckpt",
            },
            mv_label: {
                "bs_inst_hyperace2_unwa.ckpt": "https://mvsepless/hyperace2.ckpt",
            },
        }
        content_ids = {
            "https://pcunwa/v2_inst.ckpt": "same-etag",
            "https://mvsepless/hyperace2.ckpt": "same-etag",
        }
        with _with_supplements(_NO_SUPPLEMENTS):
            with unittest.mock.patch(
                "core.download_sizes.content_ids_from_cache",
                return_value=content_ids,
            ):
                merged = catalog_sources.merged_catalogues(vr={}, mdx=mdx, demucs={})
        self.assertIn(extras_label, merged.mdx)
        self.assertNotIn(mv_label, merged.mdx)
        # meta still names both for picker resolution
        self.assertIn(extras_label, merged.meta)
        self.assertIn(mv_label, merged.meta)


if __name__ == "__main__":
    unittest.main()
