"""_merged_for_display must be memoized and explicitly invalidatable.

Rebuilding it per call made format_tag_title ~9 ms, so populating one
secondary-model expander cost ~800 ms of main-thread time.
"""

from __future__ import annotations

import unittest
from unittest import mock

import core.model_display as md


class MergedForDisplayCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        md.clear_display_cache()

    def tearDown(self) -> None:
        md.clear_display_cache()

    def test_repeated_calls_reuse_one_merge(self) -> None:
        import core.catalog_sources as cs

        real = cs.merged_catalogues
        with mock.patch.object(cs, "merged_catalogues", side_effect=real) as spy:
            first = md._merged_for_display()
            second = md._merged_for_display()
        self.assertIs(first, second)
        self.assertEqual(spy.call_count, 1)

    def test_clear_display_cache_forces_rebuild(self) -> None:
        first = md._merged_for_display()
        md.clear_display_cache()
        second = md._merged_for_display()
        self.assertIsNot(first, second)

    def test_clear_politrees_cache_invalidates_display_cache(self) -> None:
        from core.politrees_catalog import clear_politrees_cache

        first = md._merged_for_display()
        clear_politrees_cache()
        second = md._merged_for_display()
        self.assertIsNot(
            first, second, "politrees feeds _display_base; its cache must invalidate"
        )


if __name__ == "__main__":
    unittest.main()
