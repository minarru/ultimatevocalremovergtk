"""Runtime option ownership and per-pass overrides without inference or weights."""

import unittest
import weakref
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from core.separator_run import apply_segment_override
from tests.test_model_option_parity import partial_model
from tests.test_stem_writer import _copy_engine_attributes


class EngineRuntimeContextTests(unittest.TestCase):
    def test_legacy_flat_constructor_keeps_gpu_alias_and_optional_export_defaults(self):
        model = partial_model()

        class LegacyModel:
            def __getattr__(self, name: str) -> Any:
                if name in {
                    'use_gpu',
                    'opus_bit_set',
                    'is_match_mix_level',
                    'is_prevent_export_clipping',
                    'amplification_threshold',
                }:
                    raise AttributeError(name)
                return getattr(model, name)

        engine = _copy_engine_attributes(LegacyModel())
        self.assertFalse(engine.is_gpu_conversion)
        self.assertEqual(str(engine.device), 'cpu')
        self.assertEqual(engine.opus_bit_set, '192k')
        self.assertIs(engine.is_match_mix_level, False)
        self.assertIs(engine.is_prevent_export_clipping, False)
        self.assertEqual(engine.amplification_threshold, 0.0)

    def test_legacy_flat_optional_export_values_keep_normalization(self):
        from engines.runtime import EngineInvocation, EngineRunContext
        from engines.runtime_compat import EngineLegacyOptions

        for value, expected in ((None, 0.0), ('1.25', 1.25)):
            with self.subTest(value=value):
                flat: Any = SimpleNamespace(
                    is_gpu_conversion=False,
                    is_match_mix_level=1,
                    is_prevent_export_clipping='',
                    amplification_threshold=value,
                )
                engine = EngineLegacyOptions()
                engine.context = EngineRunContext(
                    flat, _copy_engine_attributes(partial_model()).process_data, EngineInvocation()
                )
                self.assertIs(engine.is_match_mix_level, True)
                self.assertIs(engine.is_prevent_export_clipping, False)
                self.assertEqual(engine.amplification_threshold, expected)
                self.assertIsInstance(engine.amplification_threshold, float)

    def test_cleanup_releases_constructor_audio_without_retaining_invocation_copies(self):
        import numpy as np

        from core.inference_cleanup import release_separator
        from engines.base import SeperateAttributes

        for caller_keeps_audio in (False, True):
            with self.subTest(caller_keeps_audio=caller_keeps_audio):
                model = partial_model()
                process = _copy_engine_attributes(model).process_data
                audio = np.ones((8, 2))
                reference = weakref.ref(audio)
                engine = SeperateAttributes(
                    model, process, master_inst_source=audio, master_vocal_source=audio
                )
                self.assertIs(engine.master_inst_source, audio)
                self.assertIs(engine.master_vocal_source, audio)
                if not caller_keeps_audio:
                    del audio
                with patch(
                    'engines.model_weight_cache.get_weight_cache',
                    return_value=SimpleNamespace(stash_separator=lambda separator: False),
                ):
                    release_separator(engine)
                self.assertIsNone(engine.state.master_inst_source)
                self.assertIsNone(engine.state.master_vocal_source)
                if caller_keeps_audio:
                    np.testing.assert_array_equal(reference(), np.ones((8, 2)))
                else:
                    self.assertIsNone(reference())

    def test_segment_override_reaches_live_engine_and_rebuilt_engine(self):
        model = partial_model()
        engine = _copy_engine_attributes(model)
        apply_segment_override(SimpleNamespace(_mdx_segment_override=96), model, engine)
        model.mdx_segment_size = 64
        self.assertEqual(engine.mdx_segment_size, 64)
        self.assertEqual(_copy_engine_attributes(model).mdx_segment_size, 64)
        self.assertIs(engine.context.identity, model.identity)
        self.assertIs(engine.context.mdx, model.mdx_options)

    def test_process_callbacks_are_read_from_the_run_payload(self):
        engine = _copy_engine_attributes(partial_model())
        calls = []
        engine.process_data.check_run_control = lambda: calls.append('checked')
        engine.check_run_control()
        self.assertEqual(calls, ['checked'])

    def test_per_pass_stem_rewrites_do_not_change_config(self):
        model = partial_model()
        model.primary_stem = 'vocals'
        engine = _copy_engine_attributes(model)
        engine.primary_stem = 'bass'
        self.assertEqual(model.primary_stem, 'vocals')
        self.assertEqual(engine.primary_stem, 'bass')

    def test_backend_is_resolved_once_before_cached_source_lookup(self):
        from core.gpu_backend import resolve_inference_backend

        model = partial_model()
        with patch(
            'engines.base.resolve_inference_backend', wraps=resolve_inference_backend
        ) as resolve:
            engine = _copy_engine_attributes(model)
            self.assertEqual(resolve.call_count, 1)
            self.assertEqual(str(engine.device), 'cpu')

    def test_cleanup_releases_materialized_handles_and_state_owned_audio(self):
        import numpy as np

        from core.inference_cleanup import release_separator

        engine = _copy_engine_attributes(partial_model())
        released = []
        module = SimpleNamespace(cpu=lambda: released.append('cpu'))
        engine._inference_model = module
        engine.primary_source = np.ones((8, 2))
        with patch(
            'engines.model_weight_cache.get_weight_cache',
            return_value=SimpleNamespace(
                stash_separator=lambda separator: False,
            ),
        ):
            release_separator(engine)
        self.assertEqual(released, ['cpu'])
        self.assertIsNone(engine.state.primary_source)
        self.assertIsNone(engine.state._inference_model)
