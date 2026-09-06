"""Injected scientific checkpoint paths retain trusted envelope semantics."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import torch


class CheckpointBoundaryTests(unittest.TestCase):
    def test_scientific_imports_do_not_load_core_policy(self) -> None:
        for module in ['ml.apollo_model_data.base_model', 'ml.mdxnet', 'vendor.demucs.states']:
            code = f'''import sys
import tests
from importlib.abc import MetaPathFinder
class BlockCore(MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname == 'core' or fullname.startswith('core.'):
   raise ImportError('scientific code imported application policy')
sys.meta_path.insert(0, BlockCore())
import {module}
'''
            result = subprocess.run(
                [sys.executable, '-c', code], capture_output=True, text=True, timeout=60
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_mixer_injected_loader_restores_linear_weights(self) -> None:
        from ml.mdxnet import Mixer

        state = {'linear.weight': torch.arange(80, dtype=torch.float32).reshape(8, 10)}
        calls = []

        def loader(path: str, *, map_location: str):
            calls.append((path, map_location))
            return state

        mixer = Mixer('cpu', 'tiny.th', checkpoint_loader=loader)
        self.assertEqual(calls, [('tiny.th', 'cpu')])
        torch.testing.assert_close(mixer.state_dict()['linear.weight'], state['linear.weight'])

    def test_demucs_package_and_local_checksum_loader(self) -> None:
        from vendor.demucs.pretrained import get_model
        from vendor.demucs.states import load_model

        model = torch.nn.Linear(2, 2)

        def package():
            return {
                'klass': torch.nn.Linear,
                'args': [2, 2],
                'kwargs': {},
                'state': model.state_dict(),
            }

        direct = load_model(package())
        torch.testing.assert_close(direct.weight, model.weight)
        calls = []

        def loader(path: Path, *, map_location: str):
            calls.append((path.name, map_location))
            return package()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            checksum = hashlib.sha256(b'tiny').hexdigest()[:8]
            path = root / f'test-{checksum}.th'
            path.write_bytes(b'tiny')
            output = io.StringIO()
            with redirect_stdout(output):
                loaded = get_model('test', repo=root, checkpoint_loader=loader)
            self.assertEqual(output.getvalue(), 'name_or_sig:  test\n')
            torch.testing.assert_close(loaded.weight, model.weight)
            self.assertFalse(loaded.training)
            self.assertEqual(calls, [(path.name, 'cpu')])
            path.write_bytes(b'corrupt')
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(RuntimeError):
                get_model('test', repo=root, checkpoint_loader=loader)
            self.assertEqual(output.getvalue(), 'name_or_sig:  test\n')
            self.assertEqual(len(calls), 1)

    def test_apollo_package_constructor_and_legacy_default(self) -> None:
        from ml.apollo_model_data.base_model import BaseModel
        from tests.test_apollo_pretrain import _TinyApollo

        model = _TinyApollo()
        package = {'model_name': 'TinyApollo', 'state_dict': model.state_dict()}
        with patch('ml.apollo_model_data.get', return_value=_TinyApollo):
            loaded = BaseModel.from_checkpoint(package)
            with patch(
                'core.torch_checkpoint.load_torch_checkpoint', return_value=package
            ) as loader:
                legacy = BaseModel.from_pretrain('tiny.ckpt')
        torch.testing.assert_close(
            loaded.state_dict()["lin.weight"], legacy.state_dict()["lin.weight"]
        )
        loader.assert_called_once_with('tiny.ckpt', map_location='cpu')

    def test_demucs_bag_propagates_loader_and_preserves_strictness(self) -> None:
        from vendor.demucs.pretrained import get_model
        from vendor.demucs.states import load_model

        model = _TinyDemucs()

        def package():
            return {'klass': _TinyDemucs, 'args': [], 'kwargs': {}, 'state': model.state_dict()}

        calls = []

        def loader(path: Path, *, map_location: str):
            calls.append((path.name, map_location))
            return package()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'first.th').write_bytes(b'first')
            (root / 'second.th').write_bytes(b'second')
            (root / 'bag.yaml').write_text('models: [first, second]\nsegment: 7\n')
            output = io.StringIO()
            with redirect_stdout(output), self.assertWarnsRegex(ResourceWarning, r"unclosed file.*bag\.yaml"):
                bag = get_model('bag', repo=root, checkpoint_loader=loader)
            self.assertEqual(output.getvalue(), 'name_or_sig:  bag\n')
        self.assertEqual(calls, [('first.th', 'cpu'), ('second.th', 'cpu')])
        from vendor.demucs.apply import BagOfModels

        assert isinstance(bag, BagOfModels)
        self.assertEqual(len(bag.models), 2)
        for member in bag.models:
            assert isinstance(member, _TinyDemucs)
            torch.testing.assert_close(member.weight, model.weight)
            self.assertFalse(member.training)
            self.assertEqual(member.segment, 7)
        supplied = package()
        supplied['kwargs']['unknown'] = 1
        with self.assertWarnsRegex(UserWarning, 'Dropping inexistant parameter unknown'):
            load_model(supplied)
        self.assertEqual(supplied['kwargs'], {})
        supplied['kwargs']['unknown'] = 1
        with self.assertRaises(TypeError):
            load_model(supplied, strict=True)
        self.assertEqual(supplied['kwargs'], {'unknown': 1})

    def test_injected_and_package_paths_work_when_core_imports_are_denied(self) -> None:
        code = '''import sys
import tests
import torch
from importlib.abc import MetaPathFinder
from unittest.mock import patch
from ml.apollo_model_data.base_model import BaseModel
from ml.mdxnet import Mixer
from vendor.demucs.states import load_model
class BlockCore(MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname == 'core' or fullname.startswith('core.'):
   raise ImportError('application policy forbidden')
sys.meta_path.insert(0, BlockCore())
class Tiny(BaseModel):
 def __init__(self):
  super().__init__(8)
  self.linear = torch.nn.Linear(2, 2)
model = Tiny()
with patch('ml.apollo_model_data.get', return_value=Tiny):
 loaded = BaseModel.from_checkpoint({'model_name': 'Tiny', 'state_dict': model.state_dict()})
 torch.testing.assert_close(loaded.linear.weight, model.linear.weight)
state = {'linear.weight': torch.ones(8, 10)}
mixer = Mixer('cpu', 'unused', checkpoint_loader=lambda *a, **k: state)
torch.testing.assert_close(mixer.linear.weight, state['linear.weight'])
package = {'klass': Tiny, 'args': [], 'kwargs': {}, 'state': model.state_dict()}
loaded = load_model('unused', checkpoint_loader=lambda *a, **k: package)
torch.testing.assert_close(loaded.linear.weight, model.linear.weight)
assert 'core.torch_checkpoint' not in sys.modules
'''
        result = subprocess.run(
            [sys.executable, '-c', code], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class _TinyDemucs(torch.nn.Linear):
    def __init__(self) -> None:
        super().__init__(2, 2)
        self.sources = ['vocals']
        self.samplerate = 8
        self.audio_channels = 2
        self.segment = 1
