"""Runtime option ownership and per-pass overrides without inference or weights."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.separator_run import apply_segment_override
from tests.test_model_option_parity import partial_model
from tests.test_stem_writer import _copy_engine_attributes


class EngineRuntimeContextTests(unittest.TestCase):
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
