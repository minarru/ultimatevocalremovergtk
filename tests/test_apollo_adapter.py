"""Tiny CPU fixtures for Apollo's engine boundary; no checkpoints or decode IO."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

import numpy as np
import torch


class ApolloAdapterTests(unittest.TestCase):
    def test_nested_run_keeps_outer_progress_independent(self) -> None:
        # The old path is intentional: compatibility callers need the same repair.
        from ml import apollo_inference as legacy

        try:
            from engines import apollo as adapter
        except ImportError:
            adapter = legacy
        from engines.model_weight_cache import ModelWeightCache

        cache = ModelWeightCache()
        outer, inner = [], []

        def decode(path: str):
            return torch.ones((2, 40 if path == 'outer' else 16)), 8

        def progress(base: float, value: float) -> None:
            self.assertEqual(base, 0.1)
            outer.append(value)
            if len(outer) == 1:
                legacy.restore_process(
                    'inner',
                    'fake.ckpt',
                    overlap=0,
                    chunk_size=1,
                    set_progress_bar=lambda b, v: inner.append(v),
                )

        with (
            patch.object(adapter, 'load_audio', side_effect=decode),
            patch('engines.model_weight_cache.get_weight_cache', return_value=cache),
            patch('ml.apollo_model_data.BaseModel.from_pretrain', return_value=torch.nn.Identity()),
            patch(
                'ml.apollo_model_data.BaseModel.from_checkpoint',
                return_value=torch.nn.Identity(),
                create=True,
            ),
            patch('core.torch_checkpoint.load_torch_checkpoint', return_value={}),
        ):
            legacy.restore_process(
                'outer', 'fake.ckpt', overlap=0, chunk_size=1, set_progress_bar=progress
            )
        np.testing.assert_allclose(outer, [0.18, 0.36, 0.54, 0.72, 0.9])
        np.testing.assert_allclose(inner, [0.45, 0.9])

    def test_numerical_helper_preserves_short_and_single_chunk_literals(self) -> None:
        from ml.apollo_inference import restore_audio

        for values, expected in [
            ([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
            ([1.0] * 8, [1.0] * 7 + [0.0]),
        ]:
            with self.subTest(length=len(values)):
                result = restore_audio(
                    torch.tensor(values),
                    8,
                    overlap=0,
                    chunk_size=1,
                    infer_chunk=lambda chunk: chunk,
                )
                np.testing.assert_array_equal(result, [expected])

    def test_literal_padding_overlap_and_multichannel_outputs(self) -> None:
        from ml.apollo_inference import restore_audio

        for channels in (1, 2, 3):
            for length in (3, 6, 8, 10, 17, 40):
                for overlap in (0, 2):
                    with self.subTest(channels=channels, length=length, overlap=overlap):
                        samples = torch.arange(1, length + 1, dtype=torch.float32).repeat(
                            channels, 1
                        )
                        chunks = []

                        def infer(
                            chunk: torch.Tensor, chunks: list[torch.Tensor] = chunks
                        ) -> torch.Tensor:
                            chunks.append(chunk.clone())
                            return chunk * 2 + 0.25

                        result = restore_audio(
                            samples, 8, overlap=overlap, chunk_size=1, infer_chunk=infer
                        )
                        expected = samples.numpy() * 2 + 0.25
                        # Existing nonoverlapping fade windows have uncovered endpoints.
                        zero_indices = {
                            3: [],
                            6: [],
                            8: [7],
                            10: [7, 8],
                            17: [7, 8, 15, 16],
                            40: [7, 8, 15, 16, 23, 24, 31, 32],
                        }
                        if overlap == 0:
                            expected[:, zero_indices[length]] = 0
                        np.testing.assert_allclose(result, expected, rtol=1e-6)
                        if overlap == 0 and length == 3:
                            np.testing.assert_array_equal(chunks[0][0], [1, 2, 3, 0, 0, 0, 0, 0])
                        if overlap == 0 and length == 6:
                            np.testing.assert_array_equal(chunks[0][0], [1, 2, 3, 4, 5, 6, 5, 4])
                        if overlap == 2 and length == 17:
                            np.testing.assert_array_equal(chunks[0][0], [5, 4, 3, 2, 1, 2, 3, 4])

    def test_callback_exception_stops_chunks_and_skips_success_cleanup(self) -> None:
        from engines import apollo
        from engines.model_weight_cache import ModelWeightCache

        error = RuntimeError('cancel from callback')
        calls = []

        class Identity(torch.nn.Module):
            def forward(self, x: torch.Tensor) -> torch.Tensor:
                calls.append(x.clone())
                return x

        def cancel(base: float, value: float) -> None:
            raise error

        with (
            patch.object(apollo, 'load_audio', return_value=(torch.ones(2, 40), 8)),
            patch('engines.model_weight_cache.get_weight_cache', return_value=ModelWeightCache()),
            patch('core.torch_checkpoint.load_torch_checkpoint', return_value={}),
            patch('ml.apollo_model_data.BaseModel.from_checkpoint', return_value=Identity()),
            patch.object(apollo.gc, 'collect') as collect,
        ):
            with self.assertRaises(RuntimeError) as caught:
                apollo.restore_process(
                    'input', 'fake', overlap=0, chunk_size=1, set_progress_bar=cancel
                )
        self.assertIs(caught.exception, error)
        self.assertEqual(len(calls), 1)
        collect.assert_not_called()

    def test_cache_variants_materialization_and_decode_order(self) -> None:
        from engines import apollo
        from engines.model_weight_cache import ModelWeightCache

        cache = ModelWeightCache()
        events = []

        class Identity(torch.nn.Module):
            def to(self, *args: Any, **kwargs: Any):
                events.append('to')
                return self

            def eval(self):
                events.append('eval')
                return self

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                events.append('infer')
                return x

        def decode(path: str):
            events.append('decode')
            return torch.ones(2, 3), 8

        def load(*args: Any, **kwargs: Any):
            events.append('load')
            return {}

        with (
            patch.object(apollo, 'load_audio', side_effect=decode),
            patch('engines.model_weight_cache.get_weight_cache', return_value=cache),
            patch('core.torch_checkpoint.load_torch_checkpoint', side_effect=load),
            patch(
                'ml.apollo_model_data.BaseModel.from_checkpoint',
                side_effect=lambda *a, **k: Identity(),
            ),
            patch.object(apollo.gc, 'collect', side_effect=lambda: events.append('gc')),
        ):
            params = {'feature_dim': 4}
            for config in ['same', 'same', 'changed']:
                apollo.restore_process(
                    'input', 'fake', overlap=0, chunk_size=1, extracted_params=params, config=config
                )
            params['feature_dim'] = 8
            apollo.restore_process(
                'input', 'fake', overlap=0, chunk_size=1, extracted_params=params, config='changed'
            )
        miss = ['load', 'to', 'to', 'eval', 'decode', 'infer', 'gc']
        hit = ['to', 'eval', 'decode', 'infer', 'gc']
        self.assertEqual(events, miss + hit + miss + miss)

    def test_success_releases_decoded_input_before_collection(self) -> None:
        import weakref

        from engines import apollo
        from engines.model_weight_cache import ModelWeightCache

        references = []

        def decode(path: str):
            samples = torch.ones(2, 17)
            references.append(weakref.ref(samples))
            return samples, 8

        def collect() -> None:
            self.assertIsNone(references[0]())

        with (
            patch.object(apollo, 'load_audio', side_effect=decode),
            patch('engines.model_weight_cache.get_weight_cache', return_value=ModelWeightCache()),
            patch('core.torch_checkpoint.load_torch_checkpoint', return_value={}),
            patch(
                'ml.apollo_model_data.BaseModel.from_checkpoint', return_value=torch.nn.Identity()
            ),
            patch.object(apollo.gc, 'collect', side_effect=collect),
        ):
            result = apollo.restore_process('input', 'fake', overlap=2, chunk_size=1)
        np.testing.assert_allclose(result, np.ones((2, 17)))

    def test_audio_tools_uses_engine_output_and_preserves_export_order(self) -> None:
        from types import SimpleNamespace

        from core.audio_tools import AudioTools
        from core.settings import Settings

        settings = Settings.defaults()
        settings.process.testing_audio = False
        settings.process.export_path = '/tmp/task6-output'
        tool = AudioTools(settings, apollo_backend_name='restorer.ckpt')
        output = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32)
        events = []

        def restore(*args: Any, **kwargs: Any) -> np.ndarray:
            self.assertEqual(
                args[:4],
                (
                    'input.wav',
                    tool.apollo_model_location,
                    tool.apollo_overlap_val,
                    tool.apollo_chunk_val,
                ),
            )
            self.assertEqual(kwargs['device'], 'cpu')
            self.assertIs(kwargs['settings'], settings)
            events.append('restore')
            return output

        def write(path: str, data: np.ndarray, rate: int, *, subtype: str) -> None:
            self.assertEqual(path, '/tmp/task6-output/song restored.wav')
            np.testing.assert_array_equal(data, [[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]])
            self.assertEqual(rate, 44100)
            self.assertEqual(subtype, tool.wav_type_set)
            events.append('write')

        with (
            patch('engines.apollo.restore_process', side_effect=restore),
            patch(
                'core.gpu_backend.resolve_inference_backend',
                return_value=SimpleNamespace(torch_device='cpu', backend_name='cpu'),
            ),
            patch(
                'core.gpu_backend.clear_torch_cache', side_effect=lambda **k: events.append('clear')
            ),
            patch('soundfile.write', side_effect=write),
            patch.object(tool, '_save_format', side_effect=lambda *a: events.append('format')),
        ):
            tool.apollo_process('input.wav', 'song', {}, {}, lambda b, v: None)
        self.assertEqual(events, ['restore', 'clear', 'write', 'format'])

    def test_load_validation_checks_engine_dependencies(self) -> None:
        import builtins
        from unittest.mock import Mock

        from bundled.constants import APOLLO_RESTORE
        from core.audio_plan import AudioJobResolver, AudioJobSpec
        from core.job_plan import ValidationLevel
        from core.settings import Settings
        from tests.test_audio_plan_identity import _apollo_record, _resolved_stub

        settings = Settings.defaults()
        settings.audio_tools.apollo_model = 'apollo:restorer'
        record = _apollo_record()
        resolver = AudioJobResolver(Mock(inventory_generation=7))
        resolver.identities = Mock()
        resolver.identities.lookup.return_value = record
        descriptor = _resolved_stub(record, '/tmp/restorer.ckpt').model
        real_import = builtins.__import__

        def unavailable(name: str, *args: Any, **kwargs: Any):
            if name == 'engines.apollo':
                raise ImportError('Apollo decode dependency unavailable')
            return real_import(name, *args, **kwargs)

        with (
            patch.object(resolver, '_apollo_descriptor', return_value=descriptor),
            patch.object(resolver, '_runtime_diagnostics', return_value=[]),
            patch('builtins.__import__', side_effect=unavailable),
        ):
            plan = resolver.resolve(
                AudioJobSpec(APOLLO_RESTORE, settings, '/tmp/out', ('input.wav',)),
                ValidationLevel.LOAD,
            )
        self.assertTrue(
            any(
                d.code == 'audio.load' and 'decode dependency unavailable' in d.message
                for d in plan.diagnostics
            )
        )
