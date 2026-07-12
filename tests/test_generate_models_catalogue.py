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


if __name__ == "__main__":
    unittest.main()
