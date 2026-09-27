"""Prevent-export-clipping only scales stems for formats that can clip."""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import numpy as np

from engines.stem_writer import _save_with_message


def _save(wav_type_set: str, source: np.ndarray) -> np.ndarray:
    written: list[np.ndarray] = []
    sep = SimpleNamespace(
        process_data=SimpleNamespace(report_phase=lambda _phase: None),
        capture_stems_only=False,
        is_ensemble_mode=False,
        is_vocal_split_model=False,
        is_save_all_outputs_ensemble=False,
        is_deverb_vocals=False,
        is_normalization=False,
        amplification_threshold=0,
        is_prevent_export_clipping=True,
        save_format="WAV",
        wav_type_set=wav_type_set,
        mp3_bit_set="320k",
        flac_bit_set="16-bit",
        opus_bit_set="192k",
        write_to_console=lambda *_args, **_kwargs: None,
    )

    def write(_path: str, data: Any, *_args: Any, **_kwargs: Any) -> None:
        written.append(np.asarray(data))

    with (
        patch("engines.stem_writer.sf.write", side_effect=write),
        patch("engines.stem_writer.save_format"),
    ):
        _save_with_message(
            sep,
            "vocals.wav",
            "Vocals",
            source,
            samplerate=44100,
            buffer_stem_name=None,
            is_not_ensemble=True,
        )
    return written[0]


class ExportClipGuardTests(unittest.TestCase):
    def test_float_wav_keeps_peaks_above_full_scale(self) -> None:
        source = np.array([[1.5, -0.5], [0.25, 0.1]], dtype=np.float32)
        for subtype in ("FLOAT", "DOUBLE"):
            with self.subTest(subtype=subtype):
                np.testing.assert_array_equal(_save(subtype, source), source)

    def test_pcm_wav_is_scaled_to_full_scale(self) -> None:
        source = np.array([[1.5, -0.5], [0.25, 0.1]], dtype=np.float32)
        written = _save("PCM_24", source)
        self.assertAlmostEqual(float(np.abs(written).max()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
