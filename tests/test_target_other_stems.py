"""Target-instrument ``other`` models are Instrumental + Vocals."""

from __future__ import annotations

import unittest

from bundled.constants import INST_STEM, VOCAL_STEM
from core import Settings
from core.model_config import ModelConfig
from core.model_repository import ModelRepository
from core.stems import export_stem_label

_TARGET_OTHER_TAGS = (
    "mdx:model_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa",
    "mdx:mbr_inst2_unwa",
    "mdx:melband_roformer_inst_v1e_plus",
)


class TargetOtherStemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings()
        cls.repo = ModelRepository()

    def _dry(self, tag: str) -> ModelConfig | None:
        try:
            model = ModelConfig(self.settings, self.repo, tag, is_dry_check=True)
        except Exception:
            return None
        if not model.model_status:
            return None
        return model

    def test_installed_target_other_models_are_voc_inst(self) -> None:
        found = 0
        for tag in _TARGET_OTHER_TAGS:
            model = self._dry(tag)
            if model is None:
                continue
            found += 1
            with self.subTest(tag=tag):
                self.assertTrue(model.is_target_instrument)
                self.assertEqual(model.primary_stem, INST_STEM)
                self.assertEqual(model.secondary_stem, VOCAL_STEM)
                self.assertNotEqual(str(model.secondary_stem).casefold(), "no other")
                self.assertEqual(export_stem_label(model, "other", for_ensemble=True), INST_STEM)
                self.assertEqual(
                    export_stem_label(model, VOCAL_STEM, for_ensemble=True), VOCAL_STEM
                )
        if found == 0:
            self.skipTest("no target-other Unwa models installed")

    def test_target_other_eligible_for_vocal_pair_not_removed_pseudo_pair(self) -> None:
        eligible_vocal = set(
            self.repo.ensemble_model_list(self.settings, "pair.vocals_instrumental")
        )
        eligible_other = set(self.repo.ensemble_model_list(self.settings, "other"))
        found = 0
        for tag in _TARGET_OTHER_TAGS:
            model = self._dry(tag)
            if model is None:
                continue
            found += 1
            with self.subTest(tag=tag):
                self.assertIn(tag, eligible_vocal)
                self.assertNotIn(tag, eligible_other)
        if found == 0:
            self.skipTest("no target-other Unwa models installed")


if __name__ == "__main__":
    unittest.main()
