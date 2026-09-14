"""Small-array contracts for pure export phases and real cached engine passes."""

import unittest
from dataclasses import replace
from typing import Any
from unittest.mock import patch

import numpy as np

from bundled.constants import BASS_STEM, DRUM_STEM, INST_STEM, OTHER_STEM, VOCAL_STEM
from engines.demucs_export import DemucsExportRequest, DemucsNativeResult, plan_demucs_export
from engines.mdx_c_export import (
    MDXCExportRequest,
    MDXCNativeResult,
    plan_mdx_c_export,
    prepare_mdx_c_export,
    resolve_mdx_c_export,
    select_mdx_c_primary,
)
from engines.stem_writer import ExportPlan
from tests.test_mdx_export_routing import _derived, _mdxc_fake, _native


def identity_blend(source: Any, secondary: Any = None, **kwargs: Any) -> Any:
    return source


class DemucsExportPlanTests(unittest.TestCase):
    def setUp(self):
        self.source = np.stack([np.full((2, 8), float(i + 1)) for i in range(4)])
        self.source.setflags(write=False)
        self.mapping = {BASS_STEM: 0, DRUM_STEM: 1, OTHER_STEM: 2, VOCAL_STEM: 3}
        self.native = DemucsNativeResult(self.source, np.full((2, 8), 20.0), self.mapping)
        self.request = DemucsExportRequest(
            native=self.native,
            routes=(_native('vocals'), _derived(INST_STEM)),
            write_all_sources=False,
            blend=identity_blend,
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            write_secondary=True,
            exports_primary=True,
        )

    def test_instrumental_mix_sums_blended_non_vocal_sources_once(self):
        from core.stems import with_instrumental_mix
        from tests.stem_control_cases import manifest_routes

        routes = with_instrumental_mix(manifest_routes('demucs:htdemucs'))
        instrumental = next(r for r in routes if r.concept == 'mix.instrumental')
        blended = {name: self.source[index].T * 2 for name, index in self.mapping.items()}
        plan = plan_demucs_export(replace(
            self.request, routes=(instrumental,), available_routes=routes,
            write_all_sources=True, blended_sources=blended,
        ))
        self.assertEqual(list(plan.sources), ['mix.instrumental'])
        np.testing.assert_array_equal(plan.sources['mix.instrumental'], np.full((8, 2), 12.0))
        np.testing.assert_array_equal(self.source[0], np.full((2, 8), 1.0))

    def test_dual_subtraction_preserves_order_shape_split_and_aliases(self):
        plan = plan_demucs_export(self.request)
        self.assertIsInstance(plan, ExportPlan)
        self.assertEqual(list(plan.sources), [INST_STEM, VOCAL_STEM])
        np.testing.assert_array_equal(plan.sources[INST_STEM], np.full((8, 2), 16.0))
        np.testing.assert_array_equal(plan.sources[VOCAL_STEM], np.full((8, 2), 4.0))
        self.assertTrue(np.shares_memory(plan.sources[VOCAL_STEM], self.source))
        assert plan.split_sources is not None
        self.assertEqual(list(plan.split_sources), [VOCAL_STEM, INST_STEM])
        self.assertIsNone(plan.return_sources)

    def test_native_subset_and_secondary_return(self):
        request = replace(
            self.request,
            routes=(_native('BaSs'),),
            write_secondary=False,
            exports_primary=False,
            is_secondary_model=True,
        )
        plan = plan_demucs_export(request)
        self.assertEqual(list(plan.sources), [BASS_STEM])
        assert plan.return_sources is not None
        self.assertEqual(list(plan.return_sources), [BASS_STEM])
        self.assertTrue(np.shares_memory(plan.sources[BASS_STEM], self.source))

    def test_write_all_preserves_native_order_and_nested_complement(self):
        blended = {stem: self.source[index].T for stem, index in self.mapping.items()}
        plan = plan_demucs_export(
            replace(
                self.request,
                write_all_sources=True,
                blended_sources=blended,
                is_secondary_model=True,
            )
        )
        self.assertEqual(
            list(plan.sources), [BASS_STEM, DRUM_STEM, OTHER_STEM, VOCAL_STEM, INST_STEM]
        )
        np.testing.assert_array_equal(plan.sources[INST_STEM], np.full((8, 2), 6.0))
        self.assertIs(plan.return_sources, plan.sources)
        self.assertIs(plan.sources[VOCAL_STEM], blended[VOCAL_STEM])
        assert plan.split_sources is not None
        self.assertIs(plan.split_sources[VOCAL_STEM], blended[VOCAL_STEM])

    def test_folded_six_source_ensemble_does_not_double_count_extras(self):
        source = np.stack([np.full((2, 8), value) for value in (1.0, 2.0, 14.0, 4.0, 5.0, 6.0)])
        source.setflags(write=False)
        mapping = {**self.mapping, 'Guitar': 4, 'Piano': 5}
        native = DemucsNativeResult(source, None, mapping, True)
        plan = plan_demucs_export(
            replace(self.request, native=native, is_demucs_combine_stems=True)
        )
        np.testing.assert_array_equal(plan.sources[INST_STEM], np.full((8, 2), 17.0))

    def test_preprocess_sidecar_uses_instrumental_mix_and_existing_name(self):
        native = replace(self.native, inst_mix=np.full((2, 8), 12.0))
        plan = plan_demucs_export(
            replace(
                self.request,
                native=native,
                is_demucs_pre_proc_model_inst_mix=True,
                has_pre_proc_model=True,
            )
        )
        self.assertEqual(list(plan.extra_sources), ['Instrumental Instrumental'])
        np.testing.assert_array_equal(
            plan.extra_sources['Instrumental Instrumental'], np.full((8, 2), 8.0)
        )


class MDXCExportPlanTests(unittest.TestCase):
    def setUp(self):
        self.sources = {
            name: np.full((2, 8), value)
            for name, value in [('vocals', 1.0), ('drums', 2.0), ('bass', 3.0), ('other', 4.0)]
        }
        for array in self.sources.values():
            array.setflags(write=False)
        self.routes = tuple(_native(stem) for stem in self.sources)
        self.request = MDXCExportRequest(
            native=MDXCNativeResult(
                np.full((2, 8), 10.0), self.sources, 44100, tuple(self.sources)
            ),
            export_routes=self.routes,
            available_routes=self.routes,
            selected_stems=tuple(self.sources),
            source_keys={},
            mdxnet_stem_select='All Stems',
            primary_stem='vocals',
            secondary_stem='Instrumental',
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_ensemble_master=False,
            is_4_stem_ensemble=False,
            is_multi_stem_ensemble=False,
            is_mdx_include_stem_complement=False,
            is_mdx_combine_stems=False,
            is_invert_spec=False,
            exports_primary=True,
            exports_secondary=False,
            blend=identity_blend,
            match_frequency_pitch=lambda audio: audio,
        )

    def plan(self, request: MDXCExportRequest) -> ExportPlan:
        routing = prepare_mdx_c_export(request)
        selection = select_mdx_c_primary(request, routing)
        resolved = resolve_mdx_c_export(request, routing, selection)
        return plan_mdx_c_export(resolved)

    def test_instrumental_mix_materializes_one_combined_file(self):
        from core.stems import with_instrumental_mix
        from tests.stem_control_cases import manifest_routes

        routes = with_instrumental_mix(manifest_routes('mdx:SCNet-large_starrytong_fixed'))
        instrumental = next(r for r in routes if r.concept == 'mix.instrumental')
        plan = self.plan(replace(self.request, available_routes=routes,
                                export_routes=(instrumental,), exports_primary=False,
                                exports_secondary=True, selected_stems=()))
        self.assertEqual(list(plan.sources), ['mix.instrumental'])
        np.testing.assert_array_equal(plan.sources['mix.instrumental'], np.full((8, 2), 9.0))

    def test_native_and_subset_preserve_inventory_order_and_array_views(self):
        for routes in [self.routes, self.routes[1:3]]:
            with self.subTest(routes=routes):
                selected = tuple(route.native.raw for route in routes if route.native is not None)
                plan = self.plan(
                    replace(self.request, export_routes=routes, selected_stems=selected)
                )
                self.assertIsInstance(plan, ExportPlan)
                self.assertEqual(tuple(plan.sources), selected)
                for stem, audio in plan.sources.items():
                    self.assertEqual(audio.shape, (8, 2))
                    self.assertTrue(np.shares_memory(audio, self.sources[stem]))
                self.assertEqual(tuple(self.sources), ('vocals', 'drums', 'bass', 'other'))

    def test_complement_arrays_and_order(self):
        plan = self.plan(
            replace(
                self.request,
                export_routes=self.routes[:1],
                selected_stems=('vocals',),
                mdxnet_stem_select='vocals',
                is_mdx_include_stem_complement=True,
            )
        )
        self.assertEqual(list(plan.sources), ['vocals', 'Instrumental'])
        np.testing.assert_array_equal(plan.sources['Instrumental'], np.full((8, 2), 9.0))

    def test_secondary_pair_returns_sources_without_consuming_native_mapping(self):
        plan = self.plan(
            replace(
                self.request,
                export_routes=self.routes[:1],
                selected_stems=('vocals',),
                mdxnet_stem_select='vocals',
                is_secondary_model=True,
            )
        )
        assert plan.return_sources is not None
        self.assertIn('vocals', plan.return_sources)
        self.assertEqual(tuple(self.sources), ('vocals', 'drums', 'bass', 'other'))


class CachedEnginePlanTests(unittest.TestCase):
    def test_demucs_engine_exports_only_instrumental_mix_from_cached_sources(self):
        from core.stems import with_instrumental_mix
        from engines.demucs_engine import SeperateDemucs
        from tests.stem_control_cases import manifest_routes
        from tests.test_demucs_secondary_slots import _StubSeperateDemucs

        stub: Any = _StubSeperateDemucs([None] * 4, [None] * 4)
        routes = with_instrumental_mix(manifest_routes('demucs:htdemucs'))
        stub.available_stem_routes = routes
        stub.selected_stem_routes = tuple(r for r in routes if r.concept == 'mix.instrumental')
        stub.selected_stem_routes_explicit = True
        stub.is_sec_bv_rebalance = False
        expected = np.sum(stub.primary_sources[:3], axis=0).T.copy()
        plan = SeperateDemucs.seperate(stub)
        self.assertEqual(list(plan.sources), ['mix.instrumental'])
        np.testing.assert_array_equal(plan.sources['mix.instrumental'], expected)

    def test_demucs_engine_preserves_cache_alias_level_and_secondary_order(self):
        from engines.demucs_engine import SeperateDemucs
        from tests.test_demucs_secondary_slots import _Model, _StubSeperateDemucs

        stub: Any = _StubSeperateDemucs([_Model('bass'), None, None, None], [0.5, None, None, None])
        stub.audio_file = "/tmp/fixture.wav"
        events = []
        cached = stub.primary_sources
        stub.is_match_mix_level = True

        def levels(sources: dict, mix: Any) -> None:
            events.append('levels')
            sources[BASS_STEM] = sources[BASS_STEM] * 2

        def nested(*args: Any, **kwargs: Any) -> dict:
            events.append('secondary')
            self.assertEqual(float(cached[0, 0, 0]), 2.0)
            return {BASS_STEM: 'secondary-bass'}

        stub.apply_export_stem_levels = levels
        stub.cache_source = lambda source: events.append('cache')
        with (
            patch('engines.demucs_engine.prepare_mix', return_value=np.zeros((2, 8))),
            patch('engines.demucs_engine.process_secondary_model', side_effect=nested),
        ):
            plan = SeperateDemucs.seperate(stub)
        self.assertIsInstance(plan, ExportPlan)
        self.assertEqual(events, ['cache', 'levels', 'secondary'])
        self.assertEqual(list(plan.sources), [BASS_STEM, DRUM_STEM, OTHER_STEM, VOCAL_STEM])
        self.assertTrue(np.shares_memory(plan.sources[BASS_STEM], cached))

    def test_mdxc_engine_returns_writer_facing_plan_and_preserves_level_cache_mutation(self):
        from engines.mdx_c_engine import SeperateMDXC

        sources = {
            name: np.full((2, 8), value)
            for name, value in [('lead', 1.0), ('backing', 2.0), ('instrument', 3.0)]
        }
        routes = tuple(_native(stem) for stem in sources)
        fake: Any = _mdxc_fake(
            sources=sources,
            mix=np.full((2, 8), 6.0),
            available_routes=routes,
            selected_routes=routes,
        )
        fake.mdxnet_stem_select = 'All Stems'
        events = []

        def levels(mapping: dict, mix: Any, **kwargs: Any) -> None:
            self.assertIs(mapping, sources)
            events.append('levels')
            mapping['lead'] = mapping['lead'] * 2

        fake.apply_export_stem_levels = levels
        plan = SeperateMDXC.seperate(fake)
        self.assertIsInstance(plan, ExportPlan)
        self.assertEqual(events, ['levels'])
        self.assertEqual(list(plan.sources), ['lead', 'backing', 'instrument'])
        self.assertTrue(np.shares_memory(plan.sources['lead'], sources['lead']))
        np.testing.assert_array_equal(plan.sources['lead'], np.full((8, 2), 2.0))
