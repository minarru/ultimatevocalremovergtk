"""Complement-stem naming for 2-stem MDX-C models outside the vocals/inst pair."""

from __future__ import annotations

import unittest

import numpy as np

from bundled.constants import MDX_ARCH_TYPE
from core import Settings
from core.model_data import _mdx_c_secondary_for_pair
from core.model_identity import ModelIdentityService
from core.model_repository import ModelRepository
from engines.mdx_c import mdx_combined_secondary_key

_MID_SIDE_ID = "mdx:mdx23c_mid_side2e_gilliaaan"


class MDXCSecondaryPairTests(unittest.TestCase):
    def test_non_pair_stems_use_the_models_other_instrument(self) -> None:
        self.assertEqual(
            _mdx_c_secondary_for_pair(["center", "wide"], "center", "No center"),
            "wide",
        )

    def test_voc_inst_pair_keeps_title_case_label(self) -> None:
        self.assertEqual(
            _mdx_c_secondary_for_pair(["vocals", "instrumental"], "vocals", "Instrumental"),
            "Instrumental",
        )

    def test_real_pair_label_is_never_second_guessed(self) -> None:
        # ``Instrumental`` is a genuine pair label, not a synthetic ``No <stem>``
        # complement, so it stands even when no instrument matches it.
        self.assertEqual(
            _mdx_c_secondary_for_pair(["vocals", "other"], "vocals", "Instrumental"),
            "Instrumental",
        )

    def test_no_stem_label_kept_when_the_model_really_emits_it(self) -> None:
        self.assertEqual(
            _mdx_c_secondary_for_pair(["Bass", "No Bass"], "Bass", "No Bass"),
            "No Bass",
        )


class MDXCombinedSecondaryKeyTests(unittest.TestCase):
    def _sources(self, *names: str) -> dict[str, np.ndarray]:
        return {name: np.zeros((2, 4), dtype=np.float32) for name in names}

    def test_falls_back_to_the_other_stem_when_label_matches_nothing(self) -> None:
        sources = self._sources("center", "wide")
        key = mdx_combined_secondary_key(sources, ["center", "wide"], "No center")
        self.assertEqual(key, "wide")

    def test_label_match_wins_and_is_case_insensitive(self) -> None:
        sources = self._sources("vocals", "instrumental")
        key = mdx_combined_secondary_key(sources, ["vocals", "instrumental"], "Instrumental")
        self.assertEqual(key, "instrumental")

    def test_missing_stem_reports_the_available_keys(self) -> None:
        sources = self._sources("center")
        with self.assertRaises(KeyError) as ctx:
            mdx_combined_secondary_key(sources, ["center", "wide"], "No center")
        self.assertIn("center", str(ctx.exception))


class MDXCInstalledModelStemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings()
        cls.repo = ModelRepository()

    def test_mid_side_model_complement_is_the_wide_stem(self) -> None:
        try:
            record = ModelIdentityService(self.repo).lookup(_MID_SIDE_ID)
        except ValueError:
            self.skipTest("mid-side MDX23C model not installed")
        if not record.installed:
            self.skipTest("mid-side MDX23C model not installed")

        model = self.repo.resolve_model_dry(self.settings, MDX_ARCH_TYPE, record.id)
        self.assertIsNotNone(
            model,
            f"installed model {record.id!r} did not resolve through the repository",
        )
        assert model is not None
        self.assertTrue(model.model_status, f"installed model {record.id!r} is invalid")
        self.assertEqual(list(model.mdx_model_stems), ["center", "wide"])
        self.assertEqual(model.primary_stem, "center")
        self.assertEqual(model.secondary_stem, "wide")


if __name__ == "__main__":
    unittest.main()
