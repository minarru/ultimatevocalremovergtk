import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import generate_models_catalogue as catalogue  # noqa: E402


class UiNoteTests(unittest.TestCase):
    def test_vocals_other_note_only_for_two_stem_models(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="MelBand Roformer Kim | Inst v1 by Unwa",
            weight_file="model.ckpt",
            instruments=["other", "vocals"],
            stem_count=2,
        )
        self.assertIn("Vocals / Instrumental", catalogue._ui_note(entry))

    def test_four_stem_vocals_other_uses_subset_row_note(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="4-stems SCNet Large",
            weight_file="model.ckpt",
            instruments=["Drums", "Bass", "Other", "Vocals"],
            stem_count=4,
            name_intent="multi_stem",
        )
        self.assertEqual(catalogue._ui_note(entry), "UI: per-stem subset or focus row")

    def test_special_fx_best_result_and_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="VR Architecture",
            catalogue_label="UVR-DeNoise by FoxJoy",
            weight_file="UVR-DeNoise.pth",
            primary_stem="noise",
            name_intent="special_fx",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertIn("Noise", entry.best_result)
        self.assertTrue(entry.backend_focus.startswith("special_fx_primary:"))
        self.assertIn("complement", entry.ui_export_note)

    def test_karaoke_2_gets_karaoke_backend_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="MDX-Net ONNX",
            catalogue_label="MDX-Net Model: UVR-MDX-NET Karaoke 2",
            weight_file="UVR_MDXNET_KARA_2.onnx",
            primary_stem="Instrumental",
            name_intent="karaoke",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertTrue(entry.is_karaoke)
        self.assertEqual(entry.backend_focus, "karaoke_instrumental_primary")

    def test_specialty_stem_flags_old_vocals_mismatch(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="BandSplit Roformer | Male-Female by aufr33",
            weight_file="model.ckpt",
            instruments=["male", "female"],
            primary_stem="male",
            name_intent="vocals",
            backend_focus="two_stem",
            metadata_source="remote_yaml:test.yaml",
        )
        flags = catalogue._flag_mismatches(entry)
        self.assertTrue(any("specialty 2-stem" in flag for flag in flags))


class SourceForTests(unittest.TestCase):
    def test_mdx23c_download_list_counts_as_trvlvr(self) -> None:
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", None, trvlvr), "TRvlvr")

    def test_mdx23c_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_mdx23c_in_both_is_combined(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(
            catalogue._source_for("Some Model", politrees, trvlvr), "TRvlvr+Politrees"
        )

    def test_unknown_label_defaults_to_trvlvr(self) -> None:
        self.assertEqual(catalogue._source_for("Unknown Model", None, {}), "TRvlvr")


if __name__ == "__main__":
    unittest.main()
