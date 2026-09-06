"""Loader/cache contracts using tiny fake modules; never loads model weights."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from bundled.constants import DEMUCS_V1, DEMUCS_V2, DEMUCS_V3, DEMUCS_V4
from engines.demucs_runtime import DemucsAcquisitionRequest, acquire_demucs_model
from engines.mdx_c_runtime import MDXCAcquisitionRequest, acquire_mdx_c_model
from tests.test_model_option_parity import partial_model
from tests.test_stem_writer import _copy_engine_attributes


class FakeModule:
    def __init__(self, events: list, name: str = 'module') -> None:
        self.events = events
        self.name = name

    def to(self, device: Any) -> 'FakeModule':
        self.events.append(('to', str(device)))
        return self

    def eval(self) -> 'FakeModule':
        self.events.append(('eval',))
        return self

    def load_state_dict(self, state: Any) -> None:
        self.events.append(('state', state))


class AcquisitionTests(unittest.TestCase):
    def test_flat_demucs_v2_acquisition_uses_public_source_reference(self):
        from engines.runtime import EngineInvocation, EngineRunContext
        from engines.runtime_compat import EngineLegacyOptions

        sources = ['bass', 'drums', 'other', 'vocals']
        flat: Any = SimpleNamespace(
            model_path='/tmp/fixture.th',
            demucs_version=DEMUCS_V2,
            demucs_source_list=sources,
        )
        context = EngineRunContext(
            flat, _copy_engine_attributes(partial_model()).process_data, EngineInvocation()
        )
        engine = EngineLegacyOptions()
        engine.context = context
        engine.segment = 'Default'
        request = DemucsAcquisitionRequest.from_separator(engine)
        module = FakeModule([])
        with (
            patch('engines.demucs_runtime.auto_load_demucs_model_v2', return_value=module) as load,
            patch('engines.demucs_runtime.load_torch_checkpoint', return_value={}),
        ):
            result = acquire_demucs_model(
                request, 'cpu', weight_cache=SimpleNamespace(get=lambda key: None), cache_key=()
            )
        self.assertIs(result, module)
        self.assertIs(load.call_args.args[0], sources)
        self.assertEqual(load.call_args.args[1], '/tmp/fixture.th')

    def test_cached_mdx_and_demucs_materialize_without_loading(self):
        for acquire, request in [
            (acquire_demucs_model, DemucsAcquisitionRequest('/tmp/fixture.th', DEMUCS_V2)),
            (acquire_mdx_c_model, MDXCAcquisitionRequest('/tmp/fixture.ckpt', None, False, ())),
            (acquire_mdx_c_model, MDXCAcquisitionRequest('/tmp/fixture.ckpt', None, True, ())),
        ]:
            with self.subTest(request=request, acquire=acquire):
                events = []
                module = FakeModule(events)
                key = ('expected-cache-key',)

                def cached(
                    requested: Any,
                    *,
                    key: tuple = key,
                    events: list = events,
                    module: FakeModule = module,
                ) -> Any:
                    self.assertEqual(requested, key)
                    events.append(('cache', requested))
                    return SimpleNamespace(module=module)

                result = acquire(
                    request,
                    'cpu',
                    weight_cache=SimpleNamespace(get=cached),
                    cache_key=key,
                )
                self.assertIs(result, module)
                self.assertEqual(events, [('cache', key), ('to', 'cpu'), ('eval',)])

    def test_demucs_loader_branches_preserve_order_and_source_inventory(self):
        engine = _copy_engine_attributes(partial_model())
        context = engine.context
        context.identity.model_path = '/tmp/fixture-model.th'
        context.demucs.segment = 'Default'
        legacy_sources = ['bass', 'drums', 'other', 'vocals']
        context.model.demucs_source_list = legacy_sources
        for version in (DEMUCS_V1, DEMUCS_V2, DEMUCS_V3, DEMUCS_V4):
            with self.subTest(version=version):
                events = []
                module = FakeModule(events)
                context.demucs.demucs_version = version

                def checkpoint(
                    path: Any,
                    *,
                    events: list = events,
                    version: str = version,
                    module: FakeModule = module,
                ) -> Any:
                    events.append(('checkpoint', path))
                    if version == DEMUCS_V1:
                        return (lambda: module), (), {}, {'weight': 1}
                    return {'weight': 1}

                def v2(
                    sources: Any, path: str, *, events: list = events, module: FakeModule = module
                ) -> FakeModule:
                    self.assertIs(sources, legacy_sources)
                    events.append(('v2', path))
                    return module

                def newer(
                    *, name: str, repo: Any, checkpoint_loader: Any, events: list = events, module: FakeModule = module
                ) -> FakeModule:
                    from engines import demucs_runtime
                    self.assertIs(checkpoint_loader, demucs_runtime.load_torch_checkpoint)
                    events.append(('newer', name, str(repo)))
                    return module

                def segment(
                    value: Any, loaded: Any, *, events: list = events, module: FakeModule = module
                ) -> Any:
                    events.append(('segment', value))
                    self.assertIs(loaded, module)
                    return loaded

                with (
                    patch('engines.demucs_runtime.load_torch_checkpoint', side_effect=checkpoint),
                    patch('engines.demucs_runtime.auto_load_demucs_model_v2', side_effect=v2),
                    patch('engines.demucs_runtime._gm', side_effect=newer),
                    patch('engines.demucs_runtime.demucs_segments', side_effect=segment),
                ):
                    result = acquire_demucs_model(
                        DemucsAcquisitionRequest.from_separator(engine),
                        'cpu',
                        weight_cache=SimpleNamespace(get=lambda key: None),
                        cache_key=('key',),
                    )
                self.assertIs(result, module)
                if version == DEMUCS_V1:
                    self.assertEqual(
                        events,
                        [
                            ('checkpoint', '/tmp/fixture-model.th'),
                            ('to', 'cpu'),
                            ('state', {'weight': 1}),
                            ('eval',),
                        ],
                    )
                elif version == DEMUCS_V2:
                    self.assertEqual(
                        events,
                        [
                            ('v2', '/tmp/fixture-model.th'),
                            ('to', 'cpu'),
                            ('checkpoint', '/tmp/fixture-model.th'),
                            ('state', {'weight': 1}),
                            ('eval',),
                        ],
                    )
                else:
                    self.assertEqual(
                        events,
                        [
                            ('newer', 'fixture-model', '/tmp'),
                            ('segment', 'Default'),
                            ('to', 'cpu'),
                            ('eval',),
                        ],
                    )

    def test_mdx_roformer_loads_checkpoint_before_architecture_selection(self):
        context = _copy_engine_attributes(partial_model()).context
        context.identity.model_path = '/tmp/fixture.ckpt'
        context.mdx.mdx_c_configs = SimpleNamespace(marker='config')
        events = []
        module = FakeModule(events)

        def checkpoint(path: str) -> dict:
            events.append(('checkpoint', path))
            return {'hyperace.layer': 1}

        def build(config: Any, state_dict_keys: list[str]) -> FakeModule:
            self.assertIs(config, context.mdx.mdx_c_configs)
            events.append(('build', state_dict_keys))
            return module

        with (
            patch('engines.mdx_c_runtime._load_torch_checkpoint', side_effect=checkpoint),
            patch('engines.mdx_c_runtime.build_mdx_c_model', side_effect=build),
        ):
            result = acquire_mdx_c_model(
                MDXCAcquisitionRequest('/tmp/fixture.ckpt', context.mdx.mdx_c_configs, True, ()),
                'cpu',
                weight_cache=SimpleNamespace(get=lambda key: None),
                cache_key=('key',),
            )
        self.assertIs(result, module)
        self.assertEqual(
            events,
            [
                ('checkpoint', '/tmp/fixture.ckpt'),
                ('build', ['hyperace.layer']),
                ('state', {'hyperace.layer': 1}),
                ('to', 'cpu'),
                ('eval',),
            ],
        )


class AcquisitionKeyIntegrationTests(unittest.TestCase):
    def test_demucs_effective_overrides_drive_loader_and_key_without_changing_model(self):
        import numpy as np

        from engines.demucs_engine import SeperateDemucs
        from engines.demucs_runtime import infer_demucs_native

        for version in (DEMUCS_V2, DEMUCS_V4):
            with self.subTest(version=version):
                model = partial_model()
                model.model_path = '/tmp/task2-configured.th'
                model.demucs_version = DEMUCS_V1
                model.segment = 'Default'
                model.demucs_stem_count = 4
                engine = SeperateDemucs(model, _copy_engine_attributes(model).process_data)
                engine.model_path = '/tmp/task2-override.th'
                engine.demucs_version = version
                engine.segment = '8'
                sources = ['bass', 'drums', 'other', 'vocals']
                engine.demucs_source_list = sources
                engine.demix_demucs = lambda mix: np.zeros((4, 2, 8))
                module = FakeModule([])
                keys = []

                def cached(key: Any, *, keys: list = keys) -> None:
                    keys.append(key)

                with (
                    patch(
                        'engines.model_weight_cache.get_weight_cache',
                        return_value=SimpleNamespace(get=cached),
                    ),
                    patch(
                        'engines.demucs_runtime.auto_load_demucs_model_v2', return_value=module
                    ) as v2,
                    patch(
                        'engines.demucs_runtime.load_torch_checkpoint', return_value={}
                    ) as checkpoint,
                    patch('engines.demucs_runtime._gm', return_value=module) as newer,
                    patch('engines.demucs_runtime.demucs_segments', return_value=module) as segment,
                ):
                    infer_demucs_native(
                        engine,
                        prepare_mix=lambda audio: np.zeros((2, 8)),
                        process_secondary_model=lambda *args, **kwargs: None,
                    )
                self.assertEqual(
                    keys, [('demucs', ('/tmp/task2-override.th', 0, 0), 'cpu', (version, '8'))]
                )
                self.assertEqual(engine._weight_cache_key, keys[0])
                if version == DEMUCS_V2:
                    self.assertIs(v2.call_args.args[0], sources)
                    self.assertEqual(v2.call_args.args[1], '/tmp/task2-override.th')
                    checkpoint.assert_called_once_with('/tmp/task2-override.th')
                    newer.assert_not_called()
                else:
                    self.assertEqual(newer.call_args.kwargs['name'], 'task2-override')
                    self.assertEqual(str(newer.call_args.kwargs['repo']), '/tmp')
                    segment.assert_called_once_with('8', module)
                    v2.assert_not_called()
                    checkpoint.assert_not_called()
                self.assertEqual(model.model_path, '/tmp/task2-configured.th')
                self.assertEqual(model.demucs_version, DEMUCS_V1)
                self.assertEqual(model.segment, 'Default')
                self.assertIsNot(model.demucs_source_list, sources)

    def test_classic_and_roformer_demix_keep_cache_variants_and_small_array_output(self):
        import numpy as np

        from engines.mdx_c_engine import SeperateMDXC

        class IdentityModule(FakeModule):
            num_target_instruments = 1

            def __call__(self, batch: Any) -> Any:
                return batch.clone()

        for roformer, override in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(roformer=roformer, override=override):
                model = partial_model()
                model.model_path = '/tmp/task2-configured.ckpt'
                model.is_mdx_c = True
                model.is_roformer = roformer
                model.mdx_c_configs = SimpleNamespace(
                    inference=SimpleNamespace(dim_t=33, batch_size=2),
                    audio=SimpleNamespace(hop_length=4),
                    training=SimpleNamespace(target_instrument='bass', instruments=['bass']),
                )
                model.overlap_mdx23 = 2
                model.is_mdx_c_seg_def = True
                model.mdx_batch_size = 2
                process = _copy_engine_attributes(model).process_data
                engine = SeperateMDXC(model, process)
                engine.is_vocal_main_target = False
                configured = model.mdx_c_configs
                if override:
                    engine.model_path = '/tmp/task2-override.ckpt'
                    engine.mdx_c_configs = SimpleNamespace(
                        inference=SimpleNamespace(dim_t=65, batch_size=2),
                        audio=SimpleNamespace(hop_length=4),
                        training=configured.training,
                    )
                    engine.roformer_config = SimpleNamespace(
                        inference=engine.mdx_c_configs.inference,
                        audio=SimpleNamespace(hop_length=2),
                        training=configured.training,
                    )
                keys = []
                module = IdentityModule([])

                def cached(key: Any, *, keys: list = keys) -> None:
                    keys.append(key)

                cache = SimpleNamespace(get=cached)
                mix = np.arange(512, dtype=np.float32).reshape(2, 256) / 512
                with (
                    patch('engines.model_weight_cache.get_weight_cache', return_value=cache),
                    patch('engines.mdx_c_runtime._load_torch_checkpoint', return_value={}) as load,
                    patch('engines.mdx_c_runtime.TFC_TDF_net', return_value=module) as classic,
                    patch('engines.mdx_c_runtime.build_mdx_c_model', return_value=module) as build,
                ):
                    output = engine.demix(mix)
                kind = 'mdx_roformer' if roformer else 'mdx_c'
                dim_t = 65 if override else 33
                variants = (True, dim_t) if roformer else (dim_t,)
                path = '/tmp/task2-override.ckpt' if override else '/tmp/task2-configured.ckpt'
                self.assertEqual(keys, [(kind, (path, 0, 0), 'cpu', variants)])
                load.assert_called_once_with(path)
                architecture = build if roformer else classic
                config = engine.roformer_config if roformer else engine.mdx_c_configs
                self.assertIs(architecture.call_args.args[0], config)
                self.assertEqual(model.model_path, '/tmp/task2-configured.ckpt')
                self.assertIs(model.mdx_c_configs, configured)
                self.assertEqual(model.mdx_c_configs.inference.dim_t, 33)
                self.assertEqual(engine._weight_cache_key, keys[0])
                self.assertIs(engine._inference_model, module)
                assert isinstance(output, np.ndarray)
                np.testing.assert_allclose(output, mix, rtol=1e-6, atol=1e-7)

    def test_demucs_native_miss_keeps_cache_key_and_callback_order(self):
        import numpy as np

        from engines.demucs_engine import SeperateDemucs
        from engines.demucs_runtime import infer_demucs_native

        model = partial_model()
        model.model_path = '/tmp/missing-task2-demucs-key.yaml'
        model.demucs_version = DEMUCS_V4
        model.segment = 'Default'
        model.demucs_stem_count = 4
        process = _copy_engine_attributes(model).process_data
        engine = SeperateDemucs(model, process)
        events = []
        module = FakeModule(events)
        native_sources = np.zeros((4, 2, 8))
        engine.demix_demucs = lambda mix: native_sources
        engine.start_inference_console_write = lambda: events.append(('start',))
        engine.running_inference_console_write = lambda is_no_write=False: events.append(
            ('running',)
        )
        engine.write_to_console = lambda *args, **kwargs: events.append(('console',))
        engine.cache_source = lambda secondary_sources: events.append(('cache_sources',))

        def decode(audio: Any) -> Any:
            events.append(('decode',))
            return np.zeros((2, 8))

        keys = []

        def cached(key: Any) -> Any:
            keys.append(key)
            events.append(('weights',))
            return SimpleNamespace(module=module)

        with patch(
            'engines.model_weight_cache.get_weight_cache', return_value=SimpleNamespace(get=cached)
        ):
            result = infer_demucs_native(
                engine, prepare_mix=decode, process_secondary_model=lambda *args, **kwargs: None
            )
        self.assertIs(result.sources, native_sources)
        self.assertEqual(
            keys,
            [
                (
                    'demucs',
                    ('/tmp/missing-task2-demucs-key.yaml', 0, 0),
                    'cpu',
                    (DEMUCS_V4, 'Default'),
                )
            ],
        )
        self.assertEqual(
            events,
            [
                ('start',),
                ('decode',),
                ('console',),
                ('weights',),
                ('to', 'cpu'),
                ('eval',),
                ('running',),
                ('console',),
                ('cache_sources',),
            ],
        )
