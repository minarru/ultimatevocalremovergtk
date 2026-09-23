"""Native Demucs subset persistence, planning and export contracts."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

from bundled.constants import ALL_STEMS, DEMUCS_ARCH_TYPE, ENSEMBLE_MODE
from core import ModelConfig, Settings
from core.job_diagnostics import stem_focus_diagnostics
from core.job_plan_types import ModelDescriptor
from core.job_projection import select_output_routes
from core.job_route_observations import collect_output_route_evidence
from core.model_identity import DemucsSpec, ModelArtifacts, ModelRecord
from core.settings.job_resolution import SettingsLayer, SettingsResolver
from core.stem_selection import StemSelectionState, SubsetView, apply_stem_selection
from core.types import ProcessMethod


def model_for(settings: Settings, *, six_stem: bool = False, ensemble: bool = False, **kwargs: Any):
    basename = 'htdemucs_6s' if six_stem else 'htdemucs'
    record = ModelRecord(
        f'demucs:{basename}',
        'demucs',
        'htdemucs',
        'HT Demucs',
        'htdemucs',
        ModelArtifacts('htdemucs.yaml'),
        True,
        demucs=DemucsSpec('v4', '6_stem' if six_stem else '4_stem'),
    )
    return ModelConfig(
        settings,
        MagicMock(),
        record.id,
        ENSEMBLE_MODE if ensemble else DEMUCS_ARCH_TYPE,
        identity=record,
        is_dry_check=True,
        **kwargs,
    )


def descriptor_for(model: ModelConfig):
    return ModelDescriptor(
        'demucs:htdemucs',
        'demucs',
        'htdemucs',
        'HT Demucs',
        routes=model.available_stem_routes,
        primary_stem=model.primary_stem,
        secondary_stem=model.secondary_stem,
    )


class DemucsSubsetTests(unittest.TestCase):
    def settings_for(self, selected: list[str]):
        settings = Settings.defaults()
        settings.demucs.stems_selected = selected
        return settings

    def test_subset_write_persists_native_keys_and_clears_scalar_focus(self):
        settings = Settings.defaults()
        settings.process.stem_focus = 'vocal.vocals'
        model = model_for(settings)
        state = StemSelectionState()
        state.mode = 'demucs'
        state.routes = model.available_stem_routes
        state.subset_stems = list(model.demucs_source_list)
        state.write(settings, SubsetView('custom', {'Bass', 'Drums'}, False))
        self.assertEqual(getattr(settings.demucs, 'stems_selected', []), ['drums', 'bass'])
        self.assertEqual(settings.demucs.stems, ALL_STEMS)
        self.assertEqual(settings.process.stem_focus, '')
        restored = Settings.from_json_dict(settings.to_json_dict())
        self.assertEqual(restored.demucs.stems_selected, ['drums', 'bass'])
        self.assertIsInstance(state.read(restored), SubsetView)

    def test_actual_model_and_projection_agree_after_settings_roundtrip(self):
        settings = Settings.from_json_dict(self.settings_for(['drums', 'bass']).to_json_dict())
        model = model_for(settings)
        self.assertEqual(
            [r.native.raw for r in model.selected_stem_routes if r.native is not None],
            ['drums', 'bass'],
        )
        descriptors = [descriptor_for(model)]
        evidence = collect_output_route_evidence(settings, descriptors, command='separate')
        result = select_output_routes(settings, descriptors, command='separate', evidence=evidence)
        self.assertEqual(result.routes, model.selected_stem_routes)

    def test_explicit_cli_all_clears_inherited_subset(self):
        settings = self.settings_for(['Bass'])
        apply_stem_selection(settings, 'both')
        self.assertEqual(settings.demucs.stems_selected, [])
        base = self.settings_for(['Bass'])
        settings, _ = SettingsResolver().resolve(
            base,
            layers=[
                SettingsLayer(
                    'cli',
                    (
                        ('process.stem_focus', ''),
                        ('demucs.stems', ALL_STEMS),
                    ),
                )
            ],
        )
        self.assertEqual(settings.demucs.stems_selected, [])
        self.assertEqual(base.demucs.stems_selected, ['Bass'])

    def test_scalar_focus_overrides_subset(self):
        settings = self.settings_for(['drums', 'bass'])
        settings.process.stem_focus = 'vocal.vocals'
        model = model_for(settings)
        self.assertEqual(
            [r.concept for r in model.selected_stem_routes if r.native is not None],
            ['vocal.vocals'],
        )

    def test_nested_models_ignore_primary_subset(self):
        settings = self.settings_for(['drums', 'bass'])
        for flags in ({'is_secondary_model': True}, {'is_pre_proc_model': True}):
            with self.subTest(flags=flags):
                model = model_for(settings, **flags)
                self.assertEqual(len(model.selected_stem_routes), 4)

    def test_invalid_native_alias_warns_and_uses_all_routes(self):
        settings = self.settings_for(['Instrumental'])
        model = model_for(settings)
        diagnostics = stem_focus_diagnostics(settings, [model], [descriptor_for(model)])
        self.assertEqual([d.path for d in diagnostics], ['demucs.stems_selected'])
        self.assertEqual(diagnostics[0].severity, 'warning')
        self.assertEqual(len(model.selected_stem_routes), 4)

    def test_six_stem_subset_preserves_guitar_and_piano_routes(self):
        settings = self.settings_for(['guitar', 'piano'])
        model = model_for(settings, six_stem=True)
        self.assertEqual(
            {r.native.raw for r in model.selected_stem_routes if r.native}, {'guitar', 'piano'}
        )

    def test_ensemble_members_and_final_projection_ignore_primary_subset(self):
        from core.stems import run_export_routes

        settings = self.settings_for(['bass'])
        settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        settings.ensemble.main_stem = 'mode.four_stem'
        model = model_for(settings, ensemble=True)
        self.assertEqual(len(run_export_routes(model)), 4)
        descriptors = [descriptor_for(model), descriptor_for(model)]
        evidence = collect_output_route_evidence(settings, descriptors, command='ensemble')
        result = select_output_routes(settings, descriptors, command='ensemble', evidence=evidence)
        self.assertEqual(len(result.routes), 4)

    def test_invalid_case_partial_subset_and_cli_severity(self):
        settings = self.settings_for(['bass', 'Drums'])
        model = model_for(settings)
        self.assertEqual(len(model.selected_stem_routes), 4)
        diagnostics = stem_focus_diagnostics(
            settings, [model], [descriptor_for(model)], {'demucs.stems_selected': 'cli'}
        )
        self.assertEqual(diagnostics[0].severity, 'error')

    def test_malformed_sidecar_reports_invalid_without_iterating_mapping_keys(self):
        for payload in (7, {"bass": True}, [None], [["bass"]]):
            with self.subTest(payload=payload):
                data = Settings.defaults().to_json_dict()
                data["demucs"]["stems_selected"] = payload
                settings = Settings.from_json_dict(data)
                model = model_for(settings)
                self.assertEqual(len(model.selected_stem_routes), 4)
                diagnostics = stem_focus_diagnostics(settings, [model], [descriptor_for(model)])
                self.assertEqual(diagnostics[0].path, "demucs.stems_selected")

    def test_subset_engine_keeps_native_levels_and_per_stem_blends_before_writer(self):
        from engines.demucs_engine import SeperateDemucs
        from engines.demucs_export import DemucsNativeResult
        from engines.stem_writer import export_source_map

        settings = self.settings_for(['drums', 'bass'])
        model = model_for(Settings.from_json_dict(settings.to_json_dict()))
        mapping = {'Bass': 0, 'Drums': 1, 'Other': 2, 'Vocals': 3}
        source = np.stack([np.full((2, 8), i + 1.0) for i in range(4)])
        mix = np.full((2, 8), 10.0)
        slot = SimpleNamespace(demucs_stem_count=4)
        written = {}

        def levels(stems: dict[str, Any], mixture: Any):
            for key in stems:
                stems[key] = stems[key] * 0.5

        def blend(source: Any, secondary_model_source: Any = None, model_scale: Any = None):
            return source if secondary_model_source is None else source + secondary_model_source

        sep: Any = SimpleNamespace(
            available_stem_routes=model.available_stem_routes,
            selected_stem_routes=model.selected_stem_routes,
            demucs_source_map=mapping,
            demucs_stems=ALL_STEMS,
            process_data=SimpleNamespace(is_ensemble_master=False),
            is_4_stem_ensemble=False,
            is_return_dual=True,
            is_match_mix_level=True,
            is_prevent_export_clipping=True,
            apply_export_stem_levels=levels,
            is_secondary_model_activated=True,
            secondary_model_4_stem=[slot, None, None, None],
            secondary_model_4_stem_scale=[0.5, None, None, None],
            process_secondary_stem=blend,
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_sec_bv_rebalance=False,
            secondary_model=None,
            secondary_stem='Secondary',
            primary_stem='Primary',
            is_demucs_combine_stems=True,
            is_invert_spec=False,
            is_demucs_pre_proc_model_inst_mix=False,
            pre_proc_model=None,
            begin_save_phase=lambda count: None,
            stem_export_wav_path=lambda name, **kwargs: name,
            write_audio=lambda path, array, sr, **kwargs: written.setdefault(path, array),
        )
        native = DemucsNativeResult(source, mix, mapping)
        with (
            patch('engines.demucs_engine.infer_demucs_native', return_value=native),
            patch(
                'engines.demucs_engine.process_secondary_model',
                return_value={'Bass': np.full((8, 2), 7.0)},
            ),
        ):
            plan = SeperateDemucs.seperate(sep)
        export_source_map(sep, plan.sources, plan.samplerate)
        self.assertEqual(set(written), {'Bass', 'Drums'})
        np.testing.assert_array_equal(written['Bass'], np.full((8, 2), 7.5))
        np.testing.assert_array_equal(written['Drums'], np.full((8, 2), 1.0))


if __name__ == '__main__':
    unittest.main()
