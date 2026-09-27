"""Tests for GPU / ONNX backend resolution."""

import typing
import unittest
from unittest import mock

from core.gpu_backend import onnx_cpu_fallback_warning, resolve_inference_backend


class GpuBackendTests(unittest.TestCase):
    def test_cpu_when_gpu_disabled(self):
        backend = resolve_inference_backend(use_gpu=False)
        self.assertEqual(backend.backend_name, "cpu")
        self.assertEqual(backend.torch_device, "cpu")
        self.assertEqual(backend.onnx_providers, ["CPUExecutionProvider"])

    @mock.patch("engines.amp_runtime.configure_cuda_inference")
    @mock.patch("core.gpu_backend.directml_available", return_value=False)
    @mock.patch("torch.cuda.is_available", return_value=True)
    @mock.patch("core.cuda_runtime_fix.preload_onnxruntime_gpu", return_value=[])
    def test_cuda_when_available(
        self, _preload: typing.Any, _cuda: typing.Any, _dml: typing.Any, configure: typing.Any
    ):
        backend = resolve_inference_backend(
            use_gpu=True,
            device_set="1",
            is_use_directml=False,
            is_macos=False,
        )
        self.assertEqual(backend.backend_name, "cuda")
        self.assertEqual(backend.torch_device, "cuda:1")
        self.assertIn("CUDAExecutionProvider", backend.onnx_providers)
        configure.assert_called_once_with("1")

    @mock.patch("core.gpu_backend._directml_torch_device", return_value="dml-device")
    @mock.patch("core.gpu_backend.directml_available", return_value=True)
    @mock.patch("torch.cuda.is_available", return_value=False)
    def test_directml_when_enabled(self, _cuda: typing.Any, _dml: typing.Any, _device: typing.Any):
        backend = resolve_inference_backend(
            use_gpu=True,
            is_use_directml=True,
            is_macos=False,
        )
        self.assertEqual(backend.backend_name, "directml")
        self.assertEqual(backend.torch_device, "dml-device")
        self.assertEqual(backend.onnx_providers, ["CPUExecutionProvider"])

    @mock.patch("torch.backends.mps.is_available", return_value=True)
    @mock.patch("torch.cuda.is_available", return_value=False)
    def test_mps_on_macos(self, _cuda: typing.Any, _mps: typing.Any):
        backend = resolve_inference_backend(
            use_gpu=True,
            is_macos=True,
        )
        self.assertEqual(backend.backend_name, "mps")
        self.assertEqual(backend.torch_device, "mps")


class OnnxCpuFallbackWarningTests(unittest.TestCase):
    def test_cpu_only_wheel_suggests_cuda_install(self):
        warning = onnx_cpu_fallback_warning(
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
            ["CPUExecutionProvider"],
            available=["AzureExecutionProvider", "CPUExecutionProvider"],
        )
        assert warning is not None
        self.assertIn("CPU", warning)
        self.assertIn("--cuda", warning)

    def test_installed_provider_that_failed_to_load_points_at_libraries(self):
        warning = onnx_cpu_fallback_warning(
            ["CUDAExecutionProvider", "CPUExecutionProvider"],
            ["CPUExecutionProvider"],
            available=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        assert warning is not None
        self.assertIn("CPU", warning)
        self.assertIn("libraries", warning)
        self.assertNotIn("--cuda", warning)

    def test_silent_when_cuda_is_active(self):
        self.assertIsNone(
            onnx_cpu_fallback_warning(
                ["CUDAExecutionProvider", "CPUExecutionProvider"],
                ["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
        )

    def test_silent_when_cpu_was_requested(self):
        self.assertIsNone(
            onnx_cpu_fallback_warning(["CPUExecutionProvider"], ["CPUExecutionProvider"])
        )

    def test_silent_for_empty_request(self):
        self.assertIsNone(onnx_cpu_fallback_warning([], ["CPUExecutionProvider"]))


if __name__ == "__main__":
    unittest.main()
