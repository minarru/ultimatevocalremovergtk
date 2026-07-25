"""Unit tests for recent backend inference / export guards."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import torch


class RoformerOlaWindowTests(unittest.TestCase):
    def test_final_flush_uses_finish_only_for_last_chunk(self) -> None:
        from engines.mdx import select_roformer_ola_window

        start_w, mid_w, finish_w = "start", "middle", "finish"
        C = 100
        mix_len = 250
        # Final flush may contain starts 100 and 200; only 200 reaches the end.
        self.assertIs(
            select_roformer_ola_window(0, C, mix_len, start_w, mid_w, finish_w),
            start_w,
        )
        self.assertIs(
            select_roformer_ola_window(100, C, mix_len, start_w, mid_w, finish_w),
            mid_w,
        )
        self.assertIs(
            select_roformer_ola_window(200, C, mix_len, start_w, mid_w, finish_w),
            finish_w,
        )


class VrMagPadTests(unittest.TestCase):
    def test_silent_input_does_not_nan(self) -> None:
        from engines.vr_utils import scale_mag_pad_inplace

        silent = np.zeros((2, 4, 8), dtype=np.float64)
        out = scale_mag_pad_inplace(silent)
        self.assertFalse(np.isnan(out).any())
        self.assertTrue(np.all(out == 0))

    def test_scales_to_unit_peak(self) -> None:
        from engines.vr_utils import scale_mag_pad_inplace

        mag = np.array([[[0.0, 2.0, 4.0]]], dtype=np.float64)
        scale_mag_pad_inplace(mag)
        self.assertAlmostEqual(float(mag.max()), 1.0)
        self.assertAlmostEqual(float(mag[0, 0, 1]), 0.5)


class VrDenoiserLoadingMixTests(unittest.TestCase):
    def test_uses_model_res_type_not_hardcoded_polyphase(self) -> None:
        """Regression: the denoiser/deverb loading_mix must defer to the
        model's configured res_type (matching engines.vr's own loading_mix
        and the pre-refactor behavior), not force 'polyphase' — the latter
        was an Intel-Mac-only quality regression.
        """
        import engines.vr_utils as vr_utils

        mp = mock.Mock()
        mp.param = {"band": {1: {}, 2: {}}}

        with mock.patch.object(
            vr_utils,
            "multiband_waves_to_spectrogram",
            return_value=(mock.Mock(), None, None),
        ) as mocked:
            vr_utils.loading_mix(mock.Mock(), mp)

        self.assertTrue(mocked.call_args.kwargs.get("use_model_res_type"))


class BanditSpectralTests(unittest.TestCase):
    def test_stft_istft_roundtrip_shape(self) -> None:
        from ml.bandit_spectral import SpectralComponent

        spectral = SpectralComponent(n_fft=512, win_length=512, hop_length=128)
        audio = torch.randn(2, 2, 4096)
        spec = spectral.stft(audio)
        self.assertEqual(spec.ndim, 4)
        self.assertTrue(torch.is_complex(spec))
        recon = spectral.istft(spec, length=audio.shape[-1])
        self.assertEqual(tuple(recon.shape), tuple(audio.shape))

    def test_mps_compatible_context_restores_device(self) -> None:
        from ml.bandit_spectral import mps_compatible_module_device
        from ml.stft_device import needs_cpu_stft

        module = torch.nn.Linear(4, 4)
        sample = torch.randn(2)
        # On CPU hosts the context is a no-op path.
        with mps_compatible_module_device(module, sample) as orig:
            self.assertEqual(orig.type, "cpu")
            self.assertFalse(needs_cpu_stft(orig))
        self.assertEqual(next(module.parameters()).device.type, "cpu")


class StftDevicePolicyTests(unittest.TestCase):
    def test_mps_and_xpu_need_bounce(self) -> None:
        from ml.stft_device import needs_cpu_stft

        self.assertTrue(needs_cpu_stft(torch.device("meta")))  # non cuda/cpu
        # Construct fake device types via string form used by helpers.
        self.assertTrue(needs_cpu_stft("mps"))
        self.assertTrue(needs_cpu_stft("xpu"))
        self.assertFalse(needs_cpu_stft("cpu"))
        self.assertFalse(needs_cpu_stft("cuda:0"))


class EnsembleArrayInputTests(unittest.TestCase):
    def test_average_audio_is_array(self) -> None:
        from ml.spec_utils import average_audio

        a = np.ones((2, 100), dtype=np.float32)
        b = np.full((2, 80), 3.0, dtype=np.float32)
        out = average_audio([a, b], is_array=True)
        self.assertEqual(out.shape, (2, 100))
        # Longer stem unchanged; shorter padded then averaged.
        self.assertTrue(np.allclose(out[:, :80], 2.0))

    def test_ensemble_inputs_writes_array_average(self) -> None:
        from ml.spec_utils import AVERAGE, ensemble_inputs

        a = np.ones((2, 64), dtype=np.float32)
        b = np.ones((2, 64), dtype=np.float32) * 3
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "out.wav")
            with mock.patch("ml.spec_utils.sf.write") as write:
                ensemble_inputs(
                    [a, b],
                    AVERAGE,
                    is_normalization=False,
                    wav_type_set="PCM_16",
                    save_path=path,
                    is_array=True,
                )
            write.assert_called_once()
            written = write.call_args[0][1]
            self.assertTrue(np.allclose(written, 2.0))


class CaptureEnsembleStemTests(unittest.TestCase):
    def test_capture_copies_buffers(self) -> None:
        from core.job_runner import _capture_separator_stem_arrays

        sep = mock.Mock()
        arr = np.arange(6, dtype=np.float32).reshape(2, 3)
        sep._ensemble_stem_buffers = {"Vocals": arr}
        captured = _capture_separator_stem_arrays(sep)
        self.assertIn("Vocals", captured)
        self.assertTrue(np.array_equal(captured["Vocals"], arr))
        captured["Vocals"][0, 0] = 99
        self.assertEqual(arr[0, 0], 0)  # copy, not view alias of buffer dict value

    def test_capture_empty_without_buffers(self) -> None:
        from core.job_runner import _capture_separator_stem_arrays

        sep = mock.Mock(spec=[])
        self.assertEqual(_capture_separator_stem_arrays(sep), {})


class DirectFlacExportTests(unittest.TestCase):
    def test_save_format_direct_flac_accepts_uppercase_wav(self) -> None:
        from core.audio_io import save_format

        with tempfile.TemporaryDirectory() as tmp:
            wav_path = str(Path(tmp) / "stem.WAV")
            Path(wav_path).write_bytes(b"placeholder")
            with mock.patch("soundfile.read", return_value=(np.zeros(8), 44100)):
                with mock.patch("soundfile.write") as write:
                    with mock.patch("os.remove") as remove:
                        # Force direct path by avoiding pydub fallback on success.
                        save_format(wav_path, "FLAC", "320k", "24-bit")
            write.assert_called_once()
            self.assertTrue(str(write.call_args[0][0]).endswith(".flac"))
            self.assertEqual(write.call_args.kwargs.get("subtype") or write.call_args[1].get("subtype"), "PCM_24")
            remove.assert_called_once_with(wav_path)


if __name__ == "__main__":
    unittest.main()
