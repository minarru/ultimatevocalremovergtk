"""MDX export routing and complement helpers."""

import typing
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from bundled.constants import ALL_STEMS, INST_STEM, VOCAL_STEM
from core.stem_roles import StemRoleId
from core.stems import StemBucket, StemId, StemRoute, StemRouteKind
from engines.mdx_c import (
    derive_mdx_complement,
    derive_mdx_multi_complement,
    mdx_combined_secondary_key,
    mdx_export_routing_flags,
    mdx_selected_stems,
)
from engines.mdx_c_engine import SeperateMDXC


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


def _reviewed_native(native: str, role: str, *, label: str | None = None) -> StemRoute:
    return StemRoute(
        native=StemId(native),
        role=StemRoleId(role),
        label=label or f"Display {role}",
        filename_tag=f"File_{role}",
        kind=StemRouteKind.NATIVE,
    )


def _reviewed_derived(
    role: str,
    *,
    complement_of: str | None = None,
    derived_from: tuple[str, ...] = (),
) -> StemRoute:
    return StemRoute(
        native=None,
        role=StemRoleId(role),
        label=f"Display {role}",
        filename_tag=f"File_{role}",
        kind=StemRouteKind.DERIVED,
        complement_of=StemRoleId(complement_of) if complement_of is not None else None,
        derived_from=tuple(StemRoleId(item) for item in derived_from),
    )


def _mdxc_fake(
    *,
    sources: dict[str, np.ndarray],
    mix: np.ndarray,
    available_routes: tuple[StemRoute, ...],
    selected_routes: tuple[StemRoute, ...],
    primary_stem: str = "lead",
    secondary_stem: str = "mix.instrumental_with_backing_vocals",
    invert_spec: bool = False,
    match_frequency_pitch: typing.Callable[[np.ndarray], np.ndarray] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        mdx_c_configs=SimpleNamespace(
            training=SimpleNamespace(
                target_instrument="",
                instruments=["lead", "backing", "instrument"],
            ),
        ),
        is_roformer=True,
        primary_model_name="reviewed-fixture",
        model_basename="reviewed-fixture",
        model_cache_key="reviewed-fixture",
        primary_sources=(mix, sources),
        load_cached_sources=lambda: None,
        is_vocal_split_model=False,
        is_secondary_model=False,
        is_pre_proc_model=False,
        is_4_stem_ensemble=False,
        is_mdx_include_stem_complement=False,
        is_secondary_model_activated=False,
        secondary_model=None,
        mdxnet_stem_select=primary_stem,
        primary_stem=primary_stem,
        primary_stem_native=primary_stem,
        secondary_stem=secondary_stem,
        primary_source=None,
        secondary_source=None,
        secondary_source_primary=None,
        secondary_source_secondary=None,
        is_invert_spec=invert_spec,
        is_mdx_combine_stems=False,
        match_frequency_pitch=match_frequency_pitch or (lambda audio: audio),
        process_secondary_stem=lambda stem, secondary=None: stem,
        apply_export_stem_levels=lambda *args, **kwargs: None,
        process_data=SimpleNamespace(is_ensemble_master=False),
        selected_stem_routes=selected_routes,
        available_stem_routes=available_routes,
        is_ensemble_mode=False,
        is_multi_stem_ensemble=False,
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
        routing = mdx_export_routing_flags(**self._base_kwargs(include_stem_complement=True))
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

    def test_raw_derived_only_all_stems_is_not_a_full_native_selection(self) -> None:
        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                export_routes=(_derived(StemBucket.INSTRUMENTAL.value, "Instrumental"),),
                mdxnet_stem_select=ALL_STEMS,
            )
        )

        self.assertFalse(routing["multi_stem_export"])

    def test_multi_source_recipe_is_not_routed_as_complement(self) -> None:
        lead = _reviewed_native("lead", "vocal.lead")
        summed = _reviewed_derived(
            "mix.instrumental_with_backing_vocals",
            derived_from=("vocal.backing", "mix.instrumental"),
        )

        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                stem_list=["lead", "backing", "instrument"],
                export_routes=(lead, summed),
                mdxnet_stem_select="lead",
            )
        )

        self.assertFalse(routing["is_complement_export"])

    def test_one_stem_target_other_is_not_complement_export(self) -> None:
        """Single-target ``other`` Roformers return an ndarray, not a stem map.

        Their inventory is native ``other`` plus a derived vocals complement.
        Complement-export indexes ``sources[stem]`` as a dict, so 1-2 stem
        models must keep the pair-export path that already unwraps ndarrays.
        """
        routing = mdx_export_routing_flags(
            **self._base_kwargs(
                stem_list=["other"],
                export_routes=(
                    _native("other", StemBucket.INSTRUMENTAL.value),
                    _derived(StemBucket.VOCALS.value, VOCAL_STEM),
                ),
                mdxnet_stem_select="other",
            )
        )
        self.assertFalse(routing["is_complement_export"])
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
        expected = -native.T + mix.T
        np.testing.assert_array_equal(complement, expected)

    def test_multi_complement_recipe_follows_combine_stems(self) -> None:
        sources = {
            "vocals": np.array([[1.0, 2.0], [3.0, 4.0]]),
            "drums": np.array([[10.0, 20.0], [30.0, 40.0]]),
            "bass": np.array([[100.0, 200.0], [300.0, 400.0]]),
        }
        mix = sources["vocals"] + sources["drums"] + sources["bass"]
        with mock.patch("engines.mdx_c.spec_utils.to_shape", side_effect=lambda src, shape: src):
            summed = derive_mdx_multi_complement(sources, "Vocals", mix, combine_stems=True)
            subtracted = derive_mdx_multi_complement(sources, "Vocals", mix, combine_stems=False)
        expected = (sources["drums"] + sources["bass"]).T
        np.testing.assert_array_equal(summed, expected)
        np.testing.assert_array_equal(subtracted, expected)

    def test_multi_complement_rejects_plural_alias_for_singular_native_key(self) -> None:
        sources = {
            "vocals": np.ones((2, 4), dtype=np.float32),
            "other": np.zeros((2, 4), dtype=np.float32),
        }

        with self.assertRaisesRegex(KeyError, "stem 'vocal' not in sources"):
            derive_mdx_multi_complement(
                sources,
                "vocal",
                np.ones((2, 4), dtype=np.float32),
                combine_stems=True,
            )

    def test_combined_secondary_prefers_exact_native_not_semantic_alias(self) -> None:
        sources = {
            "vocals": np.ones((2, 4), dtype=np.float32),
            "other": np.zeros((2, 4), dtype=np.float32),
        }

        self.assertEqual(
            mdx_combined_secondary_key(sources, ["vocal", "other"], "vocal"),
            "other",
        )

    def test_working_sources_copy_preserves_cached_dict(self) -> None:
        cached = {"Vocals": np.array([1.0]), "Instrumental": np.array([2.0])}
        working = dict(cached)
        working.pop("Vocals")
        self.assertIn("Vocals", cached)
        self.assertNotIn("Vocals", working)


class TargetOtherNdarrayExportTests(unittest.TestCase):
    def test_single_target_other_ndarray_exports_vocals_and_instrumental(self) -> None:
        """Leap-XE-style ``target_instrument: other`` demix returns an ndarray.

        Default inventory is native other (Instrumental) plus derived Vocals.
        That used to take complement-export and IndexError on sources['other'].
        """
        mix = np.ones((2, 8), dtype=np.float32)
        native = np.full((2, 8), 0.25, dtype=np.float32)
        from core.stems import model_stem_routes

        semantic_model = SimpleNamespace(
            canonical_id="mdx:mbr_inst2_unwa",
            mdx_model_stems=["other"],
            demucs_source_list=[],
            primary_stem_native="other",
            primary_stem=INST_STEM,
            secondary_stem=VOCAL_STEM,
            target_instrument="other",
            is_vocal_split_model=False,
            is_karaoke=False,
            is_bv_model=False,
            mdx_stem_count=1,
            mdxnet_stems_selected=[],
        )
        routes = model_stem_routes(semantic_model)
        fake = SimpleNamespace(
            mdx_c_configs=SimpleNamespace(
                training=SimpleNamespace(
                    target_instrument="other",
                    instruments=["vocals", "other"],
                ),
            ),
            is_roformer=True,
            primary_model_name="bs_leap_xe_inst_unwa",
            model_basename="bs_leap_xe_inst_unwa",
            model_cache_key="bs_leap_xe_inst_unwa",
            primary_sources=(mix, native),
            load_cached_sources=lambda: None,
            is_vocal_split_model=False,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_4_stem_ensemble=False,
            is_mdx_include_stem_complement=False,
            is_secondary_model_activated=False,
            secondary_model=None,
            mdxnet_stem_select="other",
            primary_stem=INST_STEM,
            primary_stem_native="other",
            secondary_stem=VOCAL_STEM,
            primary_source=None,
            secondary_source=None,
            secondary_source_primary=None,
            secondary_source_secondary=None,
            is_invert_spec=False,
            is_mdx_combine_stems=False,
            match_frequency_pitch=lambda audio: audio,
            process_secondary_stem=lambda stem, secondary=None: stem,
            process_vocal_split_chain=lambda sources: None,
            process_data=SimpleNamespace(is_ensemble_master=False),
            selected_stem_routes=routes,
            available_stem_routes=routes,
            is_ensemble_mode=False,
            is_multi_stem_ensemble=False,
        )
        from engines.stem_writer import ExportPlan

        plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        self.assertIsInstance(plan, ExportPlan)
        self.assertEqual(plan.samplerate, 44100)
        self.assertIn("other", plan.sources)
        self.assertIn("vocal.vocals", plan.sources)
        np.testing.assert_array_equal(plan.sources["other"], native.T)
        np.testing.assert_array_equal(plan.sources["vocal.vocals"], (mix - native).T)

    def test_logical_primary_does_not_flip_backend_target_polarity(self) -> None:
        """Backend target ``other`` remains the direct model array.

        The reviewed logical primary orders Instrumental first, but must not
        turn the derived vocals complement into the model output.
        """
        from core.stem_roles import StemRoleId

        mix = np.full((2, 8), 1.0, dtype=np.float32)
        backend_target = np.full((2, 8), 0.25, dtype=np.float32)
        instrumental_route = StemRoute(
            native=StemId("other"),
            role=StemRoleId("mix.instrumental"),
            label="Instrumental",
            filename_tag="Instrumental",
            kind=StemRouteKind.NATIVE,
            logical_primary=True,
        )
        vocal_route = StemRoute(
            native=None,
            role=StemRoleId("vocal.vocals"),
            label="Vocals",
            filename_tag="Vocals",
            kind=StemRouteKind.DERIVED,
            complement_of=StemRoleId("mix.instrumental"),
        )
        fake = SimpleNamespace(
            mdx_c_configs=SimpleNamespace(
                training=SimpleNamespace(
                    target_instrument="other",
                    instruments=["vocals", "other"],
                ),
            ),
            is_roformer=True,
            primary_model_name="bs_leap_xe_inst_unwa",
            model_basename="bs_leap_xe_inst_unwa",
            model_cache_key="bs_leap_xe_inst_unwa",
            primary_sources=(mix, backend_target),
            load_cached_sources=lambda: None,
            is_vocal_split_model=False,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_4_stem_ensemble=False,
            is_mdx_include_stem_complement=False,
            is_secondary_model_activated=False,
            secondary_model=None,
            mdxnet_stem_select="other",
            primary_stem=INST_STEM,
            primary_stem_native="other",
            secondary_stem=VOCAL_STEM,
            primary_source=None,
            secondary_source=None,
            secondary_source_primary=None,
            secondary_source_secondary=None,
            is_invert_spec=False,
            is_mdx_combine_stems=False,
            match_frequency_pitch=lambda audio: audio,
            process_secondary_stem=lambda stem, secondary=None: stem,
            process_data=SimpleNamespace(is_ensemble_master=False),
            selected_stem_routes=(instrumental_route, vocal_route),
            available_stem_routes=(instrumental_route, vocal_route),
            is_ensemble_mode=False,
            is_multi_stem_ensemble=False,
        )

        plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        np.testing.assert_array_equal(plan.sources["other"], backend_target.T)
        np.testing.assert_array_equal(plan.sources["vocal.vocals"], (mix - backend_target).T)

    def test_target_bass_uses_dependency_not_removed_label_to_derive_complement(self) -> None:
        from core.stems import model_stem_routes

        mix = np.full((2, 8), 1.0, dtype=np.float32)
        bass = np.full((2, 8), 0.2, dtype=np.float32)
        semantic_model = SimpleNamespace(
            canonical_id="mdx:bs_bass_xlancer",
            mdx_model_stems=["bass"],
            demucs_source_list=[],
            primary_stem_native="bass",
            primary_stem="bass",
            secondary_stem="not-a-source-key",
            target_instrument="bass",
            is_vocal_split_model=False,
            is_karaoke=False,
            is_bv_model=False,
            mdx_stem_count=1,
            mdxnet_stems_selected=[],
        )
        routes = model_stem_routes(semantic_model)
        fake = SimpleNamespace(
            mdx_c_configs=SimpleNamespace(
                training=SimpleNamespace(target_instrument="bass", instruments=["bass", "other"]),
            ),
            is_roformer=True,
            primary_model_name="bs_bass_xlancer",
            model_basename="bs_bass_xlancer",
            model_cache_key="bs_bass_xlancer",
            primary_sources=(mix, bass),
            load_cached_sources=lambda: None,
            is_vocal_split_model=False,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_4_stem_ensemble=False,
            is_mdx_include_stem_complement=False,
            is_secondary_model_activated=False,
            secondary_model=None,
            mdxnet_stem_select="bass",
            primary_stem="bass",
            primary_stem_native="bass",
            secondary_stem="not-a-source-key",
            primary_source=None,
            secondary_source=None,
            secondary_source_primary=None,
            secondary_source_secondary=None,
            is_invert_spec=False,
            is_mdx_combine_stems=False,
            match_frequency_pitch=lambda audio: audio,
            process_secondary_stem=lambda stem, secondary=None: stem,
            process_data=SimpleNamespace(is_ensemble_master=False),
            selected_stem_routes=routes,
            available_stem_routes=routes,
            is_ensemble_mode=False,
            is_multi_stem_ensemble=False,
        )

        plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        self.assertEqual(list(plan.sources), ["bass", "instrument.bass.removed"])
        np.testing.assert_array_equal(plan.sources["bass"], bass.T)
        np.testing.assert_array_equal(
            plan.sources["instrument.bass.removed"],
            (mix - bass).T,
        )


class ReviewedRecipeMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lead_route = _reviewed_native("lead", "vocal.lead", label="Lead Display")
        self.backing_route = _reviewed_native("BACKING", "vocal.backing", label="Backing Display")
        self.instrument_route = _reviewed_native(
            "instrument", "mix.instrumental", label="Instrument Display"
        )
        self.sum_route = _reviewed_derived(
            "mix.instrumental_with_backing_vocals",
            derived_from=("vocal.backing", "mix.instrumental"),
        )
        self.routes = (
            self.lead_route,
            self.backing_route,
            self.instrument_route,
            self.sum_route,
        )
        self.mix = np.full((2, 5), 20.0, dtype=np.float32)
        self.lead = np.full((2, 5), 2.0, dtype=np.float32)
        self.backing = np.full((2, 4), 3.0, dtype=np.float32)
        self.instrument = np.full((2, 5), 7.0, dtype=np.float32)

    def test_multi_source_recipe_sums_exact_reviewed_dependencies(self) -> None:
        fake = _mdxc_fake(
            sources={
                "lead": self.lead,
                "backing": self.backing,
                "INSTRUMENT": self.instrument,
            },
            mix=self.mix,
            available_routes=self.routes,
            selected_routes=(self.sum_route,),
            primary_stem="not-a-native-source",
        )

        plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        expected = np.vstack(
            (
                np.full((4, 2), 10.0, dtype=np.float32),
                np.full((1, 2), 7.0, dtype=np.float32),
            )
        )
        self.assertEqual(list(plan.sources), [self.sum_route.concept])
        np.testing.assert_array_equal(plan.sources[self.sum_route.concept], expected)
        self.assertFalse(
            np.array_equal(plan.sources[self.sum_route.concept], (self.mix - self.lead).T)
        )

    def test_raw_derived_only_focus_still_exports_the_legacy_complement(self) -> None:
        instrumental_route = _derived(StemBucket.INSTRUMENTAL.value, "Instrumental")
        fake = _mdxc_fake(
            sources={
                "lead": self.lead,
                "backing": self.backing,
                "instrument": self.instrument,
            },
            mix=self.mix,
            available_routes=(instrumental_route,),
            selected_routes=(instrumental_route,),
            primary_stem="lead",
            secondary_stem=StemBucket.INSTRUMENTAL.value,
        )
        fake.mdxnet_stem_select = ALL_STEMS

        plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        self.assertEqual(list(plan.sources), [StemBucket.INSTRUMENTAL.value])
        np.testing.assert_array_equal(
            plan.sources[StemBucket.INSTRUMENTAL.value],
            (self.mix - self.lead).T,
        )

    def test_sum_recipe_materializes_after_native_level_routing(self) -> None:
        sources = {
            "lead": self.lead.copy(),
            "backing": self.backing.copy(),
            "instrument": self.instrument.copy(),
        }
        fake = _mdxc_fake(
            sources=sources,
            mix=self.mix,
            available_routes=self.routes,
            selected_routes=self.routes,
        )
        fake.mdxnet_stem_select = ALL_STEMS

        def apply_levels(
            routed_sources: dict[str, np.ndarray],
            _mix: np.ndarray,
            *,
            stem_keys: typing.Sequence[str],
            **_kwargs: typing.Any,
        ) -> None:
            self.assertEqual(tuple(stem_keys), ("lead", "backing", "instrument"))
            routed_sources["backing"] = np.full((2, 4), 4.0, dtype=np.float32)
            routed_sources["instrument"] = np.full((2, 5), 8.0, dtype=np.float32)

        fake.apply_export_stem_levels = apply_levels

        plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        expected = np.vstack(
            (
                np.full((4, 2), 12.0, dtype=np.float32),
                np.full((1, 2), 8.0, dtype=np.float32),
            )
        )
        self.assertEqual(
            tuple(plan.sources),
            ("lead", "backing", "instrument", self.sum_route.concept),
        )
        np.testing.assert_array_equal(plan.sources[self.sum_route.concept], expected)

    def test_dependency_lookup_never_uses_labels_or_filename_tags(self) -> None:
        fake = _mdxc_fake(
            sources={
                "lead": self.lead,
                self.backing_route.label: self.backing,
                self.instrument_route.filename_tag: self.instrument,
            },
            mix=self.mix,
            available_routes=self.routes,
            selected_routes=(self.sum_route,),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            r"mix\.instrumental_with_backing_vocals.*vocal\.backing.*mix\.instrumental.*available",
        ):
            SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

    def test_missing_scheduled_dependency_fails_actionably(self) -> None:
        fake = _mdxc_fake(
            sources={"lead": self.lead, "backing": self.backing},
            mix=self.mix,
            available_routes=self.routes,
            selected_routes=(self.sum_route,),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            r"mix\.instrumental_with_backing_vocals.*mix\.instrumental.*available.*backing.*lead",
        ):
            SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

    def test_unselected_derived_route_is_not_synthesized(self) -> None:
        fake = _mdxc_fake(
            sources={
                "lead": self.lead,
                "backing": self.backing,
                "instrument": self.instrument,
            },
            mix=self.mix,
            available_routes=self.routes,
            selected_routes=(self.lead_route,),
        )

        plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        self.assertEqual(list(plan.sources), ["lead"])
        np.testing.assert_array_equal(plan.sources["lead"], self.lead.T)

    def test_one_dependency_sum_recipe_is_rejected_not_treated_as_complement(self) -> None:
        invalid_sum = _reviewed_derived(
            "mix.instrumental_with_backing_vocals",
            derived_from=("vocal.backing",),
        )
        fake = _mdxc_fake(
            sources={"backing": self.backing},
            mix=self.mix,
            available_routes=(self.backing_route, invalid_sum),
            selected_routes=(invalid_sum,),
        )

        with self.assertRaisesRegex(RuntimeError, r"derived_from.*at least two"):
            SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

    def test_complement_recipe_preserves_match_and_invert_dsp(self) -> None:
        native_route = _reviewed_native("target", "instrument.bass")
        complement_route = _reviewed_derived(
            "instrument.bass.removed", complement_of="instrument.bass"
        )
        native = np.full((2, 5), 4.0, dtype=np.float32)
        matched_mix = np.full((2, 5), 30.0, dtype=np.float32)
        match_calls: list[np.ndarray] = []

        def match_frequency(audio: np.ndarray) -> np.ndarray:
            match_calls.append(audio)
            return matched_mix

        fake = _mdxc_fake(
            sources={"target": native},
            mix=self.mix,
            available_routes=(native_route, complement_route),
            selected_routes=(complement_route,),
            primary_stem="target",
            secondary_stem=complement_route.concept,
            invert_spec=True,
            match_frequency_pitch=match_frequency,
        )
        fake.mdx_c_configs.training.instruments = ["target"]
        fake.mdx_c_configs.training.target_instrument = "target"

        inverted = np.full((5, 2), 91.0, dtype=np.float32)
        with mock.patch("engines.mdx_c.spec_utils.invert_stem", return_value=inverted) as invert:
            plan = SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        self.assertEqual(match_calls, [self.mix])
        invert.assert_called_once()
        np.testing.assert_array_equal(plan.sources[complement_route.concept], inverted)


class MdxSelectedStemsTests(unittest.TestCase):
    """``mdxnet_stems_selected`` is persisted using canonical UVR labels
    (``Vocals``); ``stem_list`` carries a checkpoint's own yaml casing (often
    lowercase). A raw membership check between the two silently matches
    nothing for any model that doesn't spell its stems exactly like the UVR
    constants -- which most community MDX-C multi-stem yamls don't."""

    def test_matches_the_models_native_casing_against_a_canonical_selection(
        self,
    ) -> None:
        selected = mdx_selected_stems(["drums", "bass", "other", "vocals"], ["Vocals"])
        self.assertEqual(selected, ["vocals"])

    def test_matches_when_both_sides_already_agree(self) -> None:
        selected = mdx_selected_stems(
            ["Vocals", "Instrumental", "Drums", "Bass"], ["Vocals", "Drums"]
        )
        self.assertEqual(selected, ["Vocals", "Drums"])

    def test_singular_native_does_not_match_plural_selection_alias(self) -> None:
        self.assertEqual(mdx_selected_stems(["vocal"], ["vocals"]), [])

    def test_empty_selection_matches_nothing(self) -> None:
        self.assertEqual(mdx_selected_stems(["vocals", "other"], []), [])
        self.assertEqual(mdx_selected_stems(["vocals", "other"], None), [])


if __name__ == "__main__":
    unittest.main()
