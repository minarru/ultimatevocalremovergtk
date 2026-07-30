"""Band recombination must not leak uninitialized memory into the waveform.

``cmb_spectrogram_to_wave`` builds a per-band buffer and fills only the band's
``[crop_start, crop_stop)`` slice. Bins outside that range are silent by intent,
but the top band's ``[crop_stop, n_fft // 2 + 1)`` range is not covered by the
high-pass filter — that filter zeroes the *low* end and multiplies the high end
by 1. Allocating the buffer uninitialized therefore passed heap contents through
the iSTFT: identical input produced different audio on every call (measured at
5.7% of peak on 4band_44100 and 48% on 3band_44100 before the fix).
"""

from __future__ import annotations

import gc
import os
import unittest
from typing import Any

import numpy as np

from core.paths import VR_PARAM_DIR
from ml import spec_utils
from ml.vr_network.model_param_init import ModelParameters

# Exercised in production by engines/vr.py and by vr_denoiser in
# engines/vr_utils.py (which MDX's denoise option calls), neither of which
# always supplies the high-end ``extra_bins`` that would overwrite the gap.
_PARAM_FILES = (
    "4band_v3.json",              # vr_denoiser: 98 of 481 top-band bins unwritten
    "4band_44100.json",
    "3band_44100.json",
    "2band_48000.json",
    "1band_sr44100_hl512_cut.json",
)


def _poison_heap() -> None:
    """Dirty the allocator so a fresh uninitialized buffer is unlikely to be zero.

    Without this the test can pass against buggy code purely because the OS
    handed back freshly-zeroed pages.
    """
    junk = [np.full(4_000_000, 1e30, dtype=np.float64) for _ in range(6)]
    del junk
    gc.collect()


def _make_spec(mp: Any, frames: int, seed: int = 0) -> np.ndarray:
    """Build a spec_m laid out the way ``combine_spectrograms`` produces it."""
    bands_n = len(mp.param["band"])
    width = sum(
        mp.param["band"][d]["crop_stop"] - mp.param["band"][d]["crop_start"]
        for d in range(1, bands_n + 1)
    )
    rng = np.random.default_rng(seed)
    real = rng.standard_normal((2, width, frames))
    imag = rng.standard_normal((2, width, frames))
    return (real + 1j * imag).astype(complex)


class CmbSpectrogramToWaveDeterminismTests(unittest.TestCase):
    def _assert_deterministic(self, name: str, is_v51_model: bool) -> None:
        path = os.path.join(VR_PARAM_DIR, name)
        if not os.path.isfile(path):
            self.skipTest(f"{name} not present")
        mp = ModelParameters(path)
        spec = _make_spec(mp, frames=48)

        runs: list[np.ndarray] = []
        for _ in range(4):
            _poison_heap()
            runs.append(
                spec_utils.cmb_spectrogram_to_wave(
                    spec.copy(), mp, is_v51_model=is_v51_model
                ).copy()
            )

        n = min(r.shape[-1] for r in runs)
        for i, other in enumerate(runs[1:], start=1):
            drift = float(np.abs(runs[0][..., :n] - other[..., :n]).max())
            self.assertEqual(
                drift,
                0.0,
                f"{name} (is_v51_model={is_v51_model}) run 0 vs run {i} differ by "
                f"{drift:.3e} — uninitialized memory reached the waveform",
            )

    def test_output_is_deterministic(self) -> None:
        """Same input must give byte-identical audio, both filter paths."""
        for name in _PARAM_FILES:
            for is_v51_model in (False, True):
                with self.subTest(params=name, v51=is_v51_model):
                    self._assert_deterministic(name, is_v51_model)

    def test_output_is_finite(self) -> None:
        """Garbage that happened to be NaN/Inf survived `* 0` in the filters."""
        for name in _PARAM_FILES:
            path = os.path.join(VR_PARAM_DIR, name)
            if not os.path.isfile(path):
                continue
            with self.subTest(params=name):
                mp = ModelParameters(path)
                _poison_heap()
                wave = spec_utils.cmb_spectrogram_to_wave(
                    _make_spec(mp, frames=48), mp, is_v51_model=True
                )
                self.assertTrue(np.isfinite(wave).all(), f"{name} produced non-finite audio")


if __name__ == "__main__":
    unittest.main()
