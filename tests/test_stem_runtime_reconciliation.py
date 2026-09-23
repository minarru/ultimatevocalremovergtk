"""Reviewed roles survive compatible installed config variants."""

import unittest
from types import SimpleNamespace
from typing import Any

from core.job_diagnostics import stem_semantics_diagnostics
from core.job_plan_types import ModelDescriptor
from core.mdx_runtime_contract import load_bundled_mdx_runtime_contracts
from core.model_config.config import ModelConfig
from core.settings import Settings
from core.stem_roles import StemReviewStatus
from core.stems import model_stem_routes, run_export_routes, select_stem_routes

KIM = 'mdx:melband_roformer_inst_v2'
VIPER = 'mdx:model_mel_band_roformer_ep_3005_sdr_11.4360'


def runtime_model(
    model_id: str = KIM,
    natives: tuple[str, ...] = ('other',),
    target: str = 'other',
    digest: str | None = None,
) -> Any:
    contract = load_bundled_mdx_runtime_contracts().contracts.get(model_id)
    artifact = contract.artifact_evidence[0] if contract and contract.artifact_evidence else None
    return SimpleNamespace(
        canonical_id=model_id,
        model_hash=digest if digest is not None else artifact.uvr_md5 if artifact else '',
        mdx_hash_record_source=artifact.hash_record_source if artifact else '',
        mdx_config_yaml='alternate.yaml',
        mdx_config_sha256='alternate-content',
        mdx_c_configs=SimpleNamespace(
            training=SimpleNamespace(instruments=list(natives), target_instrument=target)
        ),
        mdx_model_stems=list(natives),
        primary_stem=natives[0],
        primary_stem_native=natives[0],
        secondary_stem='Vocals',
        is_mdx_c=True,
        is_target_instrument=bool(target),
        is_vocal_split_model=False,
        is_ensemble_mode=False,
        settings=Settings.defaults(),
        process_method='MDX-Net',
        mdxnet_stems_selected=[],
        mdxnet_stem_select='All Stems',
        mdx_stem_count=len(natives),
        demucs_source_list=[],
        demucs_stem_count=0,
    )


class RuntimeStemReconciliationTests(unittest.TestCase):
    def test_verified_target_variant_keeps_native_key_and_declared_complement(self):
        model = runtime_model()
        routes = model_stem_routes(model)
        self.assertEqual([r.label for r in routes], ['Instrumental', 'Vocals'])
        assert routes[0].native is not None
        self.assertEqual(routes[0].native.raw, 'other')
        self.assertIsNone(routes[1].native)
        self.assertEqual(routes[1].complement_of, routes[0].role)
        self.assertEqual(model.stem_semantics.status, StemReviewStatus.REVIEWED)
        self.assertFalse(model.stem_semantics.runtime_error)

    def test_viper_config_filename_does_not_remove_vocals_complement(self):
        model = runtime_model(VIPER, ('vocals',), 'vocals')
        routes = model_stem_routes(model)
        self.assertEqual([r.label for r in routes], ['Vocals', 'Instrumental'])
        assert routes[0].native is not None
        self.assertEqual(routes[0].native.raw, 'vocals')

    def test_unknown_model_and_missing_context_stay_raw(self):
        for model in (runtime_model('mdx:unknown'), runtime_model()):
            if model.canonical_id == KIM:
                model.is_vocal_split_model = True
            with self.subTest(model=model.canonical_id):
                routes = model_stem_routes(model)
                self.assertEqual([r.label for r in routes], ['other'])
                self.assertEqual(model.stem_semantics.status, StemReviewStatus.RAW)

    def test_bad_digest_or_ambiguous_layout_preserves_review_and_blocks_execution(self):
        for model in (
            runtime_model(digest='0' * 32),
            runtime_model(natives=('one', 'two'), target=''),
        ):
            with self.subTest(digest=model.model_hash, natives=model.mdx_model_stems):
                routes = model_stem_routes(model)
                self.assertEqual([r.label for r in routes], ['Instrumental', 'Vocals'])
                self.assertTrue(model.stem_semantics.runtime_error)
                descriptor = ModelDescriptor(
                    KIM,
                    'mdx',
                    KIM.split(':')[1],
                    'Kim',
                    stem_semantics=model.stem_semantics,
                    routes=routes,
                )
                diagnostics = stem_semantics_diagnostics([descriptor])
                self.assertTrue(any(d.severity == 'error' for d in diagnostics))
                model.available_stem_routes = routes
                with self.assertRaisesRegex(ValueError, 'configuration'):
                    run_export_routes(model)

    def test_reordered_multistem_keys_match_by_name_not_position(self):
        model = runtime_model('mdx:MDX23C-8KFFT-InstVoc_HQ', ('instrumental', 'vocals'), '')
        model.mdx_c_configs.training.instruments = ["Vocals", "Instrumental"]
        routes = model_stem_routes(model)
        self.assertEqual(
            {r.native.raw: r.concept for r in routes if r.native},
            {'instrumental': 'mix.instrumental', 'vocals': 'vocal.vocals'},
        )
        self.assertFalse(model.stem_semantics.runtime_error)

    def test_reviewed_selection_reaches_export_using_actual_native_key(self):
        model = runtime_model()
        model.settings.process.stem_focus = 'mix.instrumental'
        ModelConfig._apply_stem_focus(model)
        self.assertEqual([r.native.raw for r in run_export_routes(model) if r.native], ['other'])
        model.settings.process.stem_focus = 'vocal.vocals'
        ModelConfig._apply_stem_focus(model)
        self.assertEqual([r.label for r in run_export_routes(model)], ['Vocals'])

    def test_existing_scoped_raw_selection_maps_only_for_same_model_signature(self):
        from core.model_stem_manifest import StemSemanticsRegistry, resolve_model_stem_semantics
        from core.stems import _semantic_routes, persisted_stem_focus

        old = resolve_model_stem_semantics(
            KIM, native_stems=['other'], registry=StemSemanticsRegistry.empty()
        )
        focus = persisted_stem_focus(_semantic_routes(old)[0])
        routes = model_stem_routes(runtime_model())
        self.assertEqual(
            [r.label for r in select_stem_routes(routes, focus).routes], ['Instrumental']
        )
        self.assertFalse(select_stem_routes(routes, focus.replace(KIM, 'unknown') + 'wrong').routes)
        self.assertFalse(select_stem_routes(routes, 'raw:other').routes)

    def test_controller_blocks_conflict_but_retains_reviewed_choices(self):
        from core.stem_selection import StemSelectionState
        from ui.stem_controls import StemControls

        model = runtime_model(digest='0' * 32)
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem='other',
            secondary_stem='Vocals',
            primary_key='is_primary_stem_only',
            secondary_key='is_secondary_stem_only',
        )
        state.routes = model_stem_routes(model)
        state.runtime_error = model.stem_semantics.runtime_error
        controls = StemControls(state, KIM)
        controls.sync_from_settings(model.settings)
        snapshot = controls.snapshot()
        self.assertEqual([c.route.label for c in snapshot.choices], ['Instrumental', 'Vocals'])
        self.assertTrue(all(not c.enabled for c in snapshot.choices))
        self.assertEqual(snapshot.main_count, 0)
        for ident, _ in snapshot.presets:
            self.assertFalse(controls.choose_preset(ident))
        self.assertIn('configuration', snapshot.summary)

    def test_engine_plan_emits_both_reviewed_outputs_from_alternate_target(self):
        from tests.test_stem_control_contract import mdxc_plan, scheduled_routes

        model = runtime_model()
        ModelConfig._apply_stem_focus(model)
        plan = mdxc_plan(model)
        self.assertEqual(
            [r.label for r in scheduled_routes(model, plan)], ['Instrumental', 'Vocals']
        )

    def test_live_raw_selection_refresh_keeps_its_reviewed_target(self):
        from core.model_stem_manifest import StemSemanticsRegistry, resolve_model_stem_semantics
        from core.stem_selection import StemSelectionState
        from core.stems import _semantic_routes, persisted_stem_focus
        from ui.stem_controls import StemControls

        model = runtime_model()
        old = resolve_model_stem_semantics(
            KIM, native_stems=['other'], registry=StemSemanticsRegistry.empty()
        )
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem='other',
            secondary_stem='',
            primary_key='is_primary_stem_only',
            secondary_key='is_secondary_stem_only',
        )
        state.routes = _semantic_routes(old)
        model.settings.process.stem_focus = persisted_stem_focus(state.routes[0])
        controls = StemControls(state, KIM)
        controls.sync_from_settings(model.settings)
        state.routes = model_stem_routes(model)
        controls.configure(KIM, state)
        controls.sync_from_settings(model.settings)
        self.assertFalse(controls.snapshot().review_required)
        self.assertEqual(controls.snapshot().summary, 'Instrumental')

    def test_reconciliation_cache_observes_changed_target_and_identity(self):
        model = runtime_model()
        model_stem_routes(model)
        model.mdx_c_configs.training.target_instrument = ''
        model_stem_routes(model)
        self.assertTrue(model.stem_semantics.runtime_error)
        model.mdx_c_configs.training.target_instrument = 'other'
        model_stem_routes(model)
        self.assertFalse(model.stem_semantics.runtime_error)
        model.model_hash = '0' * 32
        model_stem_routes(model)
        self.assertTrue(model.stem_semantics.runtime_error)

    def test_engine_construction_rejects_conflict_before_runtime_initialization(self):
        from engines.base import SeperateAttributes

        model = runtime_model(digest='0' * 32)
        model_stem_routes(model)
        with self.assertRaisesRegex(ValueError, 'configuration'):
            SeperateAttributes(model, SimpleNamespace())  # type: ignore[arg-type]

    def test_catalogue_keeps_reviewed_roles_when_config_evidence_disagrees(self):
        from core.model_stem_semantics import resolve_catalogue_stem_semantics

        for stems, warning in ((['other'], ''), (['Instrumental'], 'config checksum differs')):
            with self.subTest(stems=stems, warning=warning):
                semantics = resolve_catalogue_stem_semantics(
                    KIM, native_stems=stems, runtime_warning=warning
                )
                self.assertEqual(semantics.status, StemReviewStatus.REVIEWED)
                self.assertEqual(
                    {str(o.role) for o in semantics.outputs}, {'mix.instrumental', 'vocal.vocals'}
                )
                self.assertTrue(semantics.warning)

    def test_classic_checkpoint_with_reversed_primary_is_a_conflict(self):
        model = runtime_model('mdx:Kim_Inst', ('Instrumental', 'Vocals'), '')
        model.mdx_c_configs = None
        model.is_mdx_c = False
        model.primary_stem_native = 'Vocals'
        model.primary_stem = 'Vocals'
        model_stem_routes(model)
        self.assertTrue(model.stem_semantics.runtime_error)

    def test_roformer_single_target_uses_target_key_not_training_list_order(self):
        from types import MethodType
        from unittest.mock import patch

        import numpy as np
        import torch

        from engines.mdx_c_engine import SeperateMDXC

        config = SimpleNamespace(
            training=SimpleNamespace(
                target_instrument='vocals', instruments=['instrumental', 'vocals']
            ),
            inference=SimpleNamespace(dim_t=33, batch_size=1),
            audio=SimpleNamespace(hop_length=1),
        )
        separator = SimpleNamespace(
            model_display_label='test',
            is_pitch_change=False,
            device=torch.device('cpu'),
            mdx_c_configs=config,
            roformer_config=config,
            is_mdx_c_seg_def=True,
            overlap_mdx23=2,
            settings=Settings.defaults(),
            is_vocal_main_target=True,
            running_inference_console_write=lambda: None,
            running_inference_progress_bar=lambda *args: None,
            check_run_control=lambda: None,
        )
        separator.overlap_add = MethodType(SeperateMDXC.overlap_add, separator)
        request = SimpleNamespace(cache_key=lambda device: ('test',))
        mix = np.ones((2, 80), dtype=np.float32)
        with (
            patch(
                'engines.mdx_c_engine.MDXCAcquisitionRequest.from_separator', return_value=request
            ),
            patch(
                'engines.mdx_c_engine.acquire_mdx_c_model',
                return_value=lambda batch: batch[:, None] * 0.25,
            ),
        ):
            sources = SeperateMDXC.demix_roformer(separator, mix)  # type: ignore[arg-type]
        self.assertIn('vocals', sources)
        np.testing.assert_allclose(sources['vocals'], mix * 0.25)
        np.testing.assert_allclose(sources['Instrumental'], mix * 0.75)

    def test_multisource_training_order_drift_is_not_a_dictionary_reorder(self):
        model = runtime_model('mdx:MDX23C-8KFFT-InstVoc_HQ', ('Vocals', 'Instrumental'), '')
        model.mdx_c_configs.training.instruments = ['Instrumental', 'Vocals']
        model_stem_routes(model)
        self.assertTrue(model.stem_semantics.runtime_error)
