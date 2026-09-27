"""Numerical contracts retained across the librosa 0.11 -> 1.0 upgrade.

The checked-in reference is produced with 0.11, never regenerated during tests.
See fixtures/audio_compatibility/README.md for provenance and tolerances.
"""

import unittest
import warnings
from pathlib import Path

import librosa
import numpy as np

REFERENCE = Path(__file__).parent / 'fixtures/audio_compatibility/librosa_0_11.npz'
RESAMPLERS = (
    'soxr_hq',
    'polyphase',
    'kaiser_best',
    'kaiser_fast',
    'sinc_best',
    'sinc_medium',
    'sinc_fastest',
)


def _signal(length: int) -> np.ndarray:
    """Stereo, unequal channels, DC, high frequencies and endpoint transients."""
    t = np.arange(length, dtype=np.float64)
    left = 0.3 * np.sin(t * 0.13) + 0.11 * np.cos(t * 1.7) + 0.02
    right = 0.23 * np.cos(t * 0.37) - 0.07 * np.sin(t * 2.8)
    left[0] += 0.4
    right[-1] -= 0.3
    return np.stack((left, right)).astype(np.float32)


def _spectra(length: int) -> dict[str, np.ndarray]:
    signal = _signal(length)
    with warnings.catch_warnings():
        # Centered STFT intentionally covers signals shorter than its FFT window.
        warnings.filterwarnings('ignore', message='n_fft=.*is too large')
        spectrum = librosa.stft(signal, n_fft=256, hop_length=64)
    return {
        f'stft_{length}': spectrum,
        f'istft_{length}': librosa.istft(spectrum, hop_length=64, length=length),
    }


def _resamples() -> dict[str, np.ndarray]:
    signal = _signal(257)
    result = {}
    for mode in RESAMPLERS:
        for orig_sr, target_sr in ((44100, 16000), (32000, 44100)):
            result[f'{mode}_{orig_sr}_{target_sr}'] = librosa.resample(
                signal, orig_sr=orig_sr, target_sr=target_sr, res_type=mode, axis=1
            )
    # MDX-C calls omit res_type, so also preserve the default's behavior.
    result['default_48000_44100'] = librosa.resample(signal, orig_sr=48000, target_sr=44100, axis=1)
    return result


def _mel() -> dict[str, np.ndarray]:
    # ml/mel_band_roformer.py constructor defaults, including implicit Slaney norm.
    return {'mel': librosa.filters.mel(sr=44100, n_fft=2048, n_mels=60)}


def _pitch() -> dict[str, np.ndarray]:
    # Bandit uses fractional MIDI points to divide the spectrum into musical bands.
    low_midi = max(0.0, float(librosa.hz_to_midi(20.0)))
    high_midi = librosa.hz_to_midi(22050.0)
    midi = np.linspace(low_midi, high_midi, 61)
    return {
        'hz_to_midi': librosa.hz_to_midi(np.array([20.0, 55.0, 440.0, 1000.0, 22050.0])),
        'midi_to_hz': librosa.midi_to_hz(midi),
    }


def _measurements() -> dict[str, np.ndarray]:
    return _spectra(31) | _spectra(1003) | _resamples() | _mel() | _pitch()


class LibrosaCompatibilityTests(unittest.TestCase):
    def assert_reference(self, outputs: dict[str, np.ndarray]) -> None:
        with np.load(REFERENCE, allow_pickle=False) as reference:
            for name, actual in outputs.items():
                with self.subTest(operation=name):
                    expected = reference[name]
                    self.assertEqual(actual.shape, expected.shape)
                    self.assertEqual(actual.dtype, expected.dtype)
                    # Float32 FFT/resampler roundoff; absolute tolerance covers zeros.
                    np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6)

    def test_short_centered_stereo_stft_and_istft(self):
        self.assert_reference(_spectra(31))

    def test_non_hop_aligned_stereo_stft_and_istft(self):
        outputs = _spectra(1003)
        self.assert_reference(outputs)
        np.testing.assert_allclose(outputs['istft_1003'], _signal(1003), rtol=1e-5, atol=1e-6)

    def test_engine_and_vr_resampling_modes(self):
        self.assert_reference(_resamples())

    def test_mel_band_roformer_filter_defaults(self):
        self.assert_reference(_mel())

    def test_bandit_fractional_pitch_conversions(self):
        self.assert_reference(_pitch())


if __name__ == '__main__':
    unittest.main()
