"""Tests for MPS-aware STFT bounce helpers."""

import unittest

import torch

from ml.stft_device import needs_cpu_stft, torch_istft, torch_stft


class StftDeviceTests(unittest.TestCase):
    def test_cpu_does_not_need_bounce(self) -> None:
        self.assertFalse(needs_cpu_stft(torch.device("cpu")))

    def test_stft_istft_roundtrip_shape(self) -> None:
        x = torch.randn(1, 8192)
        window = torch.hann_window(1024)
        spec = torch_stft(
            x,
            n_fft=1024,
            hop_length=256,
            window=window,
            return_complex=True,
        )
        y = torch_istft(
            spec,
            n_fft=1024,
            hop_length=256,
            window=window,
            length=x.shape[-1],
        )
        self.assertEqual(tuple(y.shape), tuple(x.shape))

    def test_complex_stft_stays_on_cpu_when_forced(self) -> None:
        # Simulate bounce path: helper returns complex on CPU without forcing
        # a destination device when needs_cpu_stft would apply. On CPU hosts
        # this is a no-op path; still validates complex dtype handling.
        x = torch.randn(2, 4096)
        window = torch.hann_window(512)
        spec = torch_stft(
            x,
            n_fft=512,
            hop_length=128,
            window=window,
            return_complex=True,
        )
        self.assertTrue(torch.is_complex(spec))
        self.assertEqual(spec.device.type, "cpu")


if __name__ == "__main__":
    unittest.main()
