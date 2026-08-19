"""MDX-C source dict keys must resolve across Title Case / yaml casing."""

import unittest

from core.model_data import _mdx_c_primary_for_select
from core.stems import resolve_in_sources


class ResolveStemDictKeyTests(unittest.TestCase):
    def test_exact_key(self) -> None:
        sources = {"vocals": 1, "other": 2}
        self.assertEqual(resolve_in_sources(sources, "vocals"), "vocals")

    def test_title_case_hits_lowercase_yaml(self) -> None:
        sources = {"drums": 0, "bass": 1, "other": 2, "vocals": 3}
        self.assertEqual(resolve_in_sources(sources, "Vocals"), "vocals")
        self.assertEqual(resolve_in_sources(sources, "Other"), "other")

    def test_missing_returns_none(self) -> None:
        self.assertIsNone(resolve_in_sources({"vocals": 1}, "drums"))

    def test_mdx_c_primary_for_select_matches_casefold(self) -> None:
        instruments = ["drums", "bass", "other", "vocals"]
        self.assertEqual(_mdx_c_primary_for_select(instruments, "Vocals"), "vocals")
        self.assertEqual(_mdx_c_primary_for_select(instruments, "Other"), "other")


if __name__ == "__main__":
    unittest.main()
