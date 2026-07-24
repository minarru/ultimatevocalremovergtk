"""Tests for optional autocast + ORT runner helpers."""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np
import torch

from engines.amp_runtime import (
    autocast_enabled,
    build_ort_runner,
    env_flag,
    maybe_autocast,
    recommend_autocast,
)


class AmpRuntimeTests(unittest.TestCase):
    def test_env_flag(self) -> None:
        with mock.patch.dict("os.environ", {"UVR_AUTOCAST": "1"}, clear=False):
            self.assertTrue(env_flag("UVR_AUTOCAST"))
            self.assertTrue(autocast_enabled())
        with mock.patch.dict("os.environ", {"UVR_AUTOCAST": "0"}, clear=False):
            self.assertFalse(autocast_enabled())

    def test_autocast_enabled_env_overrides_settings(self) -> None:
        settings = mock.MagicMock()
        settings.get.return_value = True
        with mock.patch.dict("os.environ", {"UVR_AUTOCAST": "0"}, clear=False):
            self.assertFalse(autocast_enabled(settings))
        with mock.patch.dict("os.environ", {"UVR_AUTOCAST": "1"}, clear=False):
            self.assertTrue(autocast_enabled(settings))
            settings.get.assert_not_called()

    def test_autocast_enabled_uses_settings_when_env_absent(self) -> None:
        settings = mock.MagicMock()
        settings.get.return_value = True
        env = {k: v for k, v in __import__("os").environ.items() if k != "UVR_AUTOCAST"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertTrue(autocast_enabled(settings))
            settings.get.assert_called_with("is_autocast")
            settings.get.return_value = False
            self.assertFalse(autocast_enabled(settings))
            self.assertFalse(autocast_enabled(None))

    def test_recommend_autocast_matrix(self) -> None:
        with mock.patch("engines.amp_runtime.torch.cuda.is_available", return_value=False):
            self.assertFalse(recommend_autocast())

        with mock.patch("engines.amp_runtime.torch.cuda.is_available", return_value=True), mock.patch(
            "engines.amp_runtime.torch.cuda.device_count", return_value=1
        ), mock.patch(
            "engines.amp_runtime.torch.cuda.get_device_capability", return_value=(7, 5)
        ):
            self.assertFalse(recommend_autocast())

        with mock.patch("engines.amp_runtime.torch.cuda.is_available", return_value=True), mock.patch(
            "engines.amp_runtime.torch.cuda.device_count", return_value=1
        ), mock.patch(
            "engines.amp_runtime.torch.cuda.get_device_capability", return_value=(8, 0)
        ) as get_cap:
            self.assertTrue(recommend_autocast())
            get_cap.assert_called_with(0)

        with mock.patch("engines.amp_runtime.torch.cuda.is_available", return_value=True), mock.patch(
            "engines.amp_runtime.torch.cuda.device_count", return_value=2
        ), mock.patch(
            "engines.amp_runtime.torch.cuda.get_device_capability", return_value=(8, 9)
        ) as get_cap:
            self.assertTrue(recommend_autocast("CUDA:1"))
            get_cap.assert_called_with(1)

    def test_maybe_autocast_default_is_noop(self) -> None:
        env = {k: v for k, v in __import__("os").environ.items() if k != "UVR_AUTOCAST"}
        with mock.patch.dict("os.environ", env, clear=True):
            with maybe_autocast("cuda:0"):
                pass  # should not raise when CUDA unavailable either

    def test_ort_numpy_runner_returns_device_tensor(self) -> None:
        session = mock.MagicMock()
        session.get_inputs.return_value = [mock.MagicMock(name="input")]
        session.get_inputs.return_value[0].name = "input"
        session.get_outputs.return_value = [mock.MagicMock(name="output")]
        session.get_outputs.return_value[0].name = "output"
        session.get_providers.return_value = ["CPUExecutionProvider"]
        session.run.return_value = [np.ones((1, 4, 8, 8), dtype=np.float32)]

        runner = build_ort_runner(session, torch.device("cpu"))
        spek = torch.zeros((1, 4, 8, 8), dtype=torch.float32)
        out = runner(spek)
        self.assertTrue(torch.is_tensor(out))
        self.assertEqual(tuple(out.shape), (1, 4, 8, 8))
        session.run.assert_called_once()
        fed = session.run.call_args[0][1]["input"]
        self.assertEqual(fed.dtype, np.float32)
        self.assertTrue(fed.flags["C_CONTIGUOUS"])

    def _cuda_iobind_session(self):
        session = mock.MagicMock()
        session.get_inputs.return_value = [mock.MagicMock(name="input")]
        session.get_inputs.return_value[0].name = "input"
        session.get_outputs.return_value = [mock.MagicMock(name="output")]
        session.get_outputs.return_value[0].name = "output"
        session.get_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]

        ort_out = mock.MagicMock()
        ort_out.numpy.return_value = np.ones((1, 2, 4, 4), dtype=np.float32)
        ort_out.to_dlpack.side_effect = RuntimeError("no dlpack")
        binding = mock.MagicMock()
        binding.get_outputs.return_value = [ort_out]
        session.io_binding.return_value = binding
        return session, binding

    def test_ort_cuda_iobind_path_uses_binding(self) -> None:
        if not torch.cuda.is_available():
            self.skipTest("CUDA required")

        session, binding = self._cuda_iobind_session()
        runner = build_ort_runner(session, torch.device("cuda:0"))
        spek = torch.zeros((1, 2, 4, 4), dtype=torch.float32, device="cuda:0")
        out = runner(spek)
        session.run_with_iobinding.assert_called_once_with(binding)
        binding.bind_input.assert_called_once()
        binding.bind_output.assert_called_once()
        self.assertEqual(out.device.type, "cuda")
        self.assertEqual(out.dtype, torch.float32)

    def test_ort_cuda_skips_sync_when_already_on_device(self) -> None:
        if not torch.cuda.is_available():
            self.skipTest("CUDA required")

        session, _binding = self._cuda_iobind_session()
        runner = build_ort_runner(session, torch.device("cuda:0"))
        spek = torch.zeros((1, 2, 4, 4), dtype=torch.float32, device="cuda:0")
        with mock.patch("engines.amp_runtime.torch.cuda.synchronize") as sync:
            runner(spek)
        sync.assert_not_called()

    def test_ort_cuda_syncs_after_host_to_device_copy(self) -> None:
        if not torch.cuda.is_available():
            self.skipTest("CUDA required")

        session, _binding = self._cuda_iobind_session()
        runner = build_ort_runner(session, torch.device("cuda:0"))
        spek = torch.zeros((1, 2, 4, 4), dtype=torch.float32, device="cpu")
        with mock.patch("engines.amp_runtime.torch.cuda.synchronize") as sync:
            runner(spek)
        sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
