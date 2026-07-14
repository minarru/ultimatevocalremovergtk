"""MDX export routing and complement helpers."""

import unittest
from unittest import mock

import numpy as np

from bundled.constants import ALL_STEMS, VOCAL_STEM
from engines.mdx import derive_mdx_complement, mdx_export_routing_flags


class MDXExportRoutingTests(unittest.TestCase):
    def _base_kwargs(self, **overrides):
        values = dict(
            stem_list=["Vocals", "Instrumental", "Drums", "Bass"],
            selected_stems=["Vocals"],
            mdxnet_stem_select="Vocals",
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_ensemble_master=False,
            is_4_stem_ensemble=False,
            is_primary_stem_only=False,
            is_secondary_stem_only=False,
            include_stem_complement=False,
        )
        values.update(overrides)
        return values

    def test_complement_export_flag(self) -> None:
        routing = mdx_export_routing_flags(
            **self._base_kwargs(include_stem_complement=True)
        )
        self.assertTrue(routing["is_complement_export"])
        self.assertFalse(routing["is_native_pick"])
        self.assertFalse(routing["multi_stem_export"])

    def test_native_pick_when_complement_disabled(self) -> None:
        routing = mdx_export_routing_flags(**self._base_kwargs())
        self.assertFalse(routing["is_complement_export"])
        self.assertTrue(routing["is_native_pick"])
        self.assertTrue(routing["multi_stem_export"])
        self.assertEqual(routing["export_stems"], ["Vocals"])

    def test_vocals_quick_export_skips_complement(self) -> None:
        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                include_stem_complement=True,
                is_primary_stem_only=True,
            )
        )
        self.assertFalse(routing["is_complement_export"])

    def test_stem_subset_routing(self) -> None:
        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                selected_stems=["Vocals", "Drums"],
                mdxnet_stem_select=ALL_STEMS,
            )
        )
        self.assertTrue(routing["is_stem_subset"])
        self.assertEqual(routing["export_stems"], ["Vocals", "Drums"])

    def test_derive_mdx_complement_subtracts_native_from_mix(self) -> None:
        native = np.array([[1.0, 2.0], [3.0, 4.0]])
        mix = np.array([[10.0, 20.0], [30.0, 40.0]])
        with mock.patch("engines.mdx.spec_utils.to_shape", side_effect=lambda src, shape: src):
            complement = derive_mdx_complement(native, mix)
        expected = (-native.T + mix.T)
        np.testing.assert_array_equal(complement, expected)

    def test_working_sources_copy_preserves_cached_dict(self) -> None:
        cached = {"Vocals": np.array([1.0]), "Instrumental": np.array([2.0])}
        working = dict(cached)
        working.pop("Vocals")
        self.assertIn("Vocals", cached)
        self.assertNotIn("Vocals", working)


if __name__ == "__main__":
    unittest.main()
