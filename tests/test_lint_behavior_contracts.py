"""Behavior contracts protected while rewriting lint-sensitive code."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import torch

from bundled.constants import CHANGE_PITCH
from core.blocking_runner import RunResult
from core.job_callbacks import JobCallbacks
from core.settings import Settings


class DefaultOwnershipTests(unittest.TestCase):
    def test_scnet_default_dimensions_are_owned_per_instance(self) -> None:
        from ml.scnet import SCNet, SCNetMasked

        for model_type in (SCNet, SCNetMasked):
            with self.subTest(model=model_type.__name__), torch.device("meta"):
                first = model_type(num_dplayer=0)
                second = model_type(num_dplayer=0)
                self.assertEqual(first.dims, [4, 32, 64, 128])
                self.assertEqual(second.dims, first.dims)
                self.assertIsNot(first.dims, second.dims)

    def test_missing_spectrogram_parameters_fail_before_decoding(self) -> None:
        from ml.spec_utils import spectrogram_to_wave

        with patch("ml.spec_utils.librosa.istft") as decode:
            with self.assertRaisesRegex(ValueError, "model parameters"):
                spectrogram_to_wave(np.zeros((2, 3, 4)))
            decode.assert_not_called()


class CallbackBindingTests(unittest.TestCase):
    def test_audio_callbacks_retain_their_own_input_and_runner(self) -> None:
        from cli.audio import _run_audio

        starts: list[Callable[[JobCallbacks], None]] = []
        runners = [Mock(), Mock()]

        def capture(_runner: object, start: Callable[[JobCallbacks], None], **_kwargs: object) -> RunResult:
            starts.append(start)
            return RunResult(0.0, error=RuntimeError("test stop"))

        with tempfile.TemporaryDirectory() as output:
            plan = SimpleNamespace(
                tool=CHANGE_PITCH, output=output, settings=Settings.defaults(),
                units=tuple(SimpleNamespace(inputs=(name,), outputs=()) for name in ("a.wav", "b.wav")),
            )
            args = argparse.Namespace(on_exists="fail", quiet=True, fail_fast=False, report="human")
            with (
                patch("cli.audio.AudioToolRunner", side_effect=runners),
                patch("cli.audio.run_runner_cli", side_effect=capture),
            ):
                _run_audio(args, plan)
        callbacks = JobCallbacks()
        for start in starts:
            start(callbacks)
        for runner, name in zip(runners, ("a.wav", "b.wav"), strict=True):
            runner.start.assert_called_once_with(
                CHANGE_PITCH, [name], [], callbacks, apollo_params=None, output_name=None,
            )


class ApolloClosureTests(unittest.TestCase):
    def test_cached_and_uncached_model_execute_all_chunks(self) -> None:
        from ml.apollo_inference import restore_process

        signal = torch.linspace(-0.5, 0.5, 32).repeat(2, 1)
        for cached in (False, True):
            with self.subTest(cached=cached):
                model = torch.nn.Identity()
                cache = Mock()
                cache.get.return_value = SimpleNamespace(module=model) if cached else None
                with (
                    patch("ml.apollo_inference.load_audio", return_value=(signal, 8)),
                    patch("ml.apollo_inference.models.BaseModel.from_pretrain", return_value=model) as load,
                    patch("engines.model_weight_cache.get_weight_cache", return_value=cache),
                    patch("engines.model_weight_cache.materialize_module", return_value=model),
                ):
                    result = restore_process("unused.wav", "unused.ckpt", chunk_size=1, overlap=2, device="cpu")
                np.testing.assert_allclose(result, signal.numpy(), atol=1e-6)
                self.assertEqual(load.call_count, 0 if cached else 1)
