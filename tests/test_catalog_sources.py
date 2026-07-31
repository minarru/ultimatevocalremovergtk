"""The single merge path shared by Download Center and the runtime pickers."""

import typing
import unittest
import unittest.mock

from core import catalog_sources

#: ``_supplemental_sources`` takes no arguments and returns supplements only,
#: so patching it leaves the real base merge under test.
_NO_SUPPLEMENTS = ({}, {}, {}, {})


def _with_supplements(supplements: typing.Any) -> typing.Any:
    return unittest.mock.patch.object(
        catalog_sources, "_supplemental_sources", return_value=supplements
    )


class MergeOrderTests(unittest.TestCase):
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


class EntryMetaTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
