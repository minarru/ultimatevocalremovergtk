"""Tests for GPU / ONNX backend resolution."""

import unittest
from unittest import mock

from core.gpu_backend import InferenceBackend, resolve_inference_backend


class GpuBackendTests(unittest.TestCase):
    def test_cpu_when_gpu_disabled(self):
        backend = resolve_inference_backend(is_gpu_conversion=-1)
        self.assertEqual(backend.backend_name, "cpu")
        self.assertEqual(backend.torch_device, "cpu")
        self.assertEqual(backend.onnx_providers, ["CPUExecutionProvider"])

    @mock.patch("core.gpu_backend.directml_available", return_value=False)
    @mock.patch("torch.cuda.is_available", return_value=True)
    @mock.patch("core.cuda_runtime_fix.preload_onnxruntime_gpu", return_value=[])
    def test_cuda_when_available(self, _preload, _cuda, _dml):
        backend = resolve_inference_backend(
            is_gpu_conversion=0,
            device_set="1",
            is_use_directml=False,
            is_macos=False,
        )
        self.assertEqual(backend.backend_name, "cuda")
        self.assertEqual(backend.torch_device, "cuda:1")
        self.assertIn("CUDAExecutionProvider", backend.onnx_providers)

    @mock.patch("core.gpu_backend._directml_torch_device", return_value="dml-device")
    @mock.patch("core.gpu_backend.directml_available", return_value=True)
    @mock.patch("torch.cuda.is_available", return_value=False)
    def test_directml_when_enabled(self, _cuda, _dml, _device):
        backend = resolve_inference_backend(
            is_gpu_conversion=0,
            is_use_directml=True,
            is_macos=False,
        )
        self.assertEqual(backend.backend_name, "directml")
        self.assertEqual(backend.torch_device, "dml-device")
        self.assertEqual(backend.onnx_providers, ["CPUExecutionProvider"])

    @mock.patch("torch.backends.mps.is_available", return_value=True)
    @mock.patch("torch.cuda.is_available", return_value=False)
    def test_mps_on_macos(self, _cuda, _mps):
        backend = resolve_inference_backend(
            is_gpu_conversion=0,
            is_macos=True,
        )
        self.assertEqual(backend.backend_name, "mps")
        self.assertEqual(backend.torch_device, "mps")


if __name__ == "__main__":
    unittest.main()
