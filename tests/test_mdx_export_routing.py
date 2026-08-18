"""MDX export routing and complement helpers."""
import typing

import unittest
from unittest import mock

import numpy as np

from bundled.constants import ALL_STEMS, VOCAL_STEM
from core.stems import StemBucket, StemId, StemRoute, StemRouteKind
from engines.mdx_c import (
    derive_mdx_complement,
    derive_mdx_multi_complement,
    mdx_export_routing_flags,
    mdx_selected_stems,
)


def _native(name: str, concept: str | None = None) -> StemRoute:
    return StemRoute(
        native=StemId(name),
        concept=concept or name,
        label=name,
        filename_tag=name,
        kind=StemRouteKind.NATIVE,
    )


def _derived(concept: str, label: str | None = None) -> StemRoute:
    return StemRoute(
        native=None,
        concept=concept,
        label=label or concept,
        filename_tag=label or concept,
        kind=StemRouteKind.DERIVED,
    )


class MDXExportRoutingTests(unittest.TestCase):
    def _base_kwargs(self, **overrides: typing.Any):
        values = dict(
            stem_list=["Vocals", "Instrumental", "Drums", "Bass"],
            export_routes=(_native("Vocals", StemBucket.VOCALS.value),),
            mdxnet_stem_select="Vocals",
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_ensemble_master=False,
            is_4_stem_ensemble=False,
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
        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                export_routes=(_native("Bass", StemBucket.BASS.value),),
                mdxnet_stem_select="Bass",
            )
        )
        self.assertFalse(routing["is_complement_export"])
        self.assertTrue(routing["is_native_pick"])
        self.assertTrue(routing["multi_stem_export"])
        self.assertEqual(routing["export_stems"], ["Bass"])

    def test_vocals_native_is_not_complement_without_include(self) -> None:
        routing = mdx_export_routing_flags(**self._base_kwargs())
        self.assertFalse(routing["is_complement_export"])

    def test_derived_instrumental_is_not_include_complement(self) -> None:
        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                export_routes=(_derived(StemBucket.INSTRUMENTAL.value, "Instrumental"),),
                include_stem_complement=True,
            )
        )
        self.assertFalse(routing["is_complement_export"])
        self.assertFalse(routing["is_native_pick"])
        self.assertFalse(routing["multi_stem_export"])

    def test_vocals_native_matches_the_models_native_cased_stem_name(self) -> None:
        """Community MDX-C yamls commonly declare lowercase stem names
        (``training.instruments: [drums, bass, other, vocals]``). Route
        natives keep that yaml casing so export_stems match the source map."""
        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                stem_list=["drums", "bass", "other", "vocals"],
                export_routes=(_native("vocals", StemBucket.VOCALS.value),),
                mdxnet_stem_select="vocals",
            )
        )
        self.assertFalse(routing["is_complement_export"])
        self.assertTrue(routing["is_native_pick"])
        self.assertTrue(routing["multi_stem_export"])
        self.assertEqual(routing["export_stems"], ["vocals"])

    def test_stem_subset_routing(self) -> None:
        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                export_routes=(
                    _native("Vocals", StemBucket.VOCALS.value),
                    _native("Drums", StemBucket.DRUMS.value),
                ),
                mdxnet_stem_select=ALL_STEMS,
            )
        )
        self.assertTrue(routing["is_stem_subset"])
        self.assertEqual(routing["export_stems"], ["Vocals", "Drums"])

    def test_derive_mdx_complement_subtracts_native_from_mix(self) -> None:
        native = np.array([[1.0, 2.0], [3.0, 4.0]])
        mix = np.array([[10.0, 20.0], [30.0, 40.0]])
        with mock.patch("engines.mdx_c.spec_utils.to_shape", side_effect=lambda src, shape: src):
            complement = derive_mdx_complement(native, mix)
        expected = (-native.T + mix.T)
        np.testing.assert_array_equal(complement, expected)

    def test_multi_complement_recipe_follows_combine_stems(self) -> None:
        sources = {
            "vocals": np.array([[1.0, 2.0], [3.0, 4.0]]),
            "drums": np.array([[10.0, 20.0], [30.0, 40.0]]),
            "bass": np.array([[100.0, 200.0], [300.0, 400.0]]),
        }
        mix = sources["vocals"] + sources["drums"] + sources["bass"]
        with mock.patch("engines.mdx_c.spec_utils.to_shape", side_effect=lambda src, shape: src):
            summed = derive_mdx_multi_complement(
                sources, "Vocals", mix, combine_stems=True
            )
            subtracted = derive_mdx_multi_complement(
                sources, "Vocals", mix, combine_stems=False
            )
        expected = (sources["drums"] + sources["bass"]).T
        np.testing.assert_array_equal(summed, expected)
        np.testing.assert_array_equal(subtracted, expected)

    def test_working_sources_copy_preserves_cached_dict(self) -> None:
        cached = {"Vocals": np.array([1.0]), "Instrumental": np.array([2.0])}
        working = dict(cached)
        working.pop("Vocals")
        self.assertIn("Vocals", cached)
        self.assertNotIn("Vocals", working)


class MdxSelectedStemsTests(unittest.TestCase):
    """``mdxnet_stems_selected`` is persisted using canonical UVR labels
    (``Vocals``); ``stem_list`` carries a checkpoint's own yaml casing (often
    lowercase). A raw membership check between the two silently matches
    nothing for any model that doesn't spell its stems exactly like the UVR
    constants -- which most community MDX-C multi-stem yamls don't."""

    def test_matches_the_models_native_casing_against_a_canonical_selection(
        self,
    ) -> None:
        selected = mdx_selected_stems(
            ["drums", "bass", "other", "vocals"], ["Vocals"]
        )
        self.assertEqual(selected, ["vocals"])

    def test_matches_when_both_sides_already_agree(self) -> None:
        selected = mdx_selected_stems(
            ["Vocals", "Instrumental", "Drums", "Bass"], ["Vocals", "Drums"]
        )
        self.assertEqual(selected, ["Vocals", "Drums"])

    def test_empty_selection_matches_nothing(self) -> None:
        self.assertEqual(mdx_selected_stems(["vocals", "other"], []), [])
        self.assertEqual(mdx_selected_stems(["vocals", "other"], None), [])


if __name__ == "__main__":
    unittest.main()
