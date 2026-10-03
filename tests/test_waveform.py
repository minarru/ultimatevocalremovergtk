"""Waveform peaks: absolute amplitude, channel folding, streaming and fallback."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
import soundfile as sf

from core.audio_decode import AudioDecodeError, load_audio
from core.waveform import (
    Peaks,
    WaveformCancelled,
    compute_peaks,
    offer_peaks,
    peaks_from_array,
    set_peak_sink,
)

_RATE = 8000


def _sine(seconds: float, amplitude: float) -> np.ndarray:
    t = np.arange(int(_RATE * seconds)) / _RATE
    # 1 kHz at 8 kHz hits the crest exactly (every 8th sample).
    return (amplitude * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)


class ComputePeaksTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def _write(self, name: str, data: np.ndarray, subtype: str = "PCM_16") -> str:
        path = os.path.join(self.dir, name)
        sf.write(path, data, _RATE, subtype=subtype)
        return path

    def test_sine_keeps_absolute_amplitude(self) -> None:
        path = self._write("half.wav", _sine(1.0, 0.5))
        peaks = compute_peaks(path, buckets=100)
        self.assertEqual(len(peaks.mins), 100)
        self.assertEqual(len(peaks.maxs), 100)
        self.assertAlmostEqual(peaks.duration, 1.0)
        np.testing.assert_allclose(peaks.maxs, 0.5, atol=0.01)
        np.testing.assert_allclose(peaks.mins, -0.5, atol=0.01)

    def test_silence_is_zero(self) -> None:
        path = self._write("silence.wav", np.zeros(_RATE, dtype=np.float32))
        peaks = compute_peaks(path, buckets=50)
        np.testing.assert_array_equal(peaks.mins, 0.0)
        np.testing.assert_array_equal(peaks.maxs, 0.0)

    def test_stereo_folds_to_louder_channel(self) -> None:
        stereo = np.stack([np.zeros(_RATE, dtype=np.float32), _sine(1.0, 0.8)], axis=1)
        path = self._write("stereo.wav", stereo)
        peaks = compute_peaks(path, buckets=40)
        np.testing.assert_allclose(peaks.maxs, 0.8, atol=0.01)
        np.testing.assert_allclose(peaks.mins, -0.8, atol=0.01)

    def test_bucket_count_clamps_to_frames(self) -> None:
        path = self._write("tiny.wav", _sine(50 / _RATE, 0.3))
        peaks = compute_peaks(path, buckets=2048)
        self.assertEqual(len(peaks.mins), 50)

    def test_values_are_clipped_to_full_scale(self) -> None:
        loud = np.full(_RATE, 1.5, dtype=np.float32)
        path = self._write("loud.wav", loud, subtype="FLOAT")
        peaks = compute_peaks(path, buckets=10)
        np.testing.assert_array_equal(peaks.maxs, 1.0)

    def test_cancel_event_raises(self) -> None:
        path = self._write("cancel.wav", _sine(1.0, 0.5))
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(WaveformCancelled):
            compute_peaks(path, cancel=cancel)

    def test_corrupt_file_raises_decode_error(self) -> None:
        path = os.path.join(self.dir, "broken.wav")
        with open(path, "wb") as handle:
            handle.write(b"not audio at all")
        with self.assertRaises(AudioDecodeError):
            compute_peaks(path)

    def test_streamed_blocks_match_whole_file_reduction(self) -> None:
        rng = np.random.default_rng(7)
        data = (rng.random(10_000, dtype=np.float32) * 1.6 - 0.8).astype(np.float32)
        path = self._write("noise.wav", data, subtype="FLOAT")
        buckets = 7  # 10 000 / 7 frames per bucket: every bucket straddles a block edge
        with mock.patch("core.waveform._BLOCK_FRAMES", 1000):
            peaks = compute_peaks(path, buckets=buckets)
        index = (np.arange(data.size) * buckets) // data.size
        expected_min = np.array([data[index == b].min() for b in range(buckets)])
        expected_max = np.array([data[index == b].max() for b in range(buckets)])
        np.testing.assert_array_equal(peaks.mins, expected_min)
        np.testing.assert_array_equal(peaks.maxs, expected_max)

    def test_fallback_mono_array_reduces(self) -> None:
        mono = _sine(2.0, 0.25)
        with (
            mock.patch("soundfile.SoundFile", side_effect=RuntimeError("unsupported")),
            mock.patch("core.waveform.load_audio", return_value=(mono, _RATE)) as load,
        ):
            peaks = compute_peaks("/music/song.m4a", buckets=16)
        load.assert_called_once_with("/music/song.m4a")
        self.assertAlmostEqual(peaks.duration, 2.0)
        self.assertEqual(len(peaks.maxs), 16)
        np.testing.assert_allclose(peaks.maxs, 0.25, atol=0.01)

    def test_fallback_multichannel_array_reduces(self) -> None:
        channels = np.stack([_sine(1.0, 0.1), _sine(1.0, 0.6)])  # (channels, samples)
        with (
            mock.patch("soundfile.SoundFile", side_effect=RuntimeError("unsupported")),
            mock.patch("core.waveform.load_audio", return_value=(channels, _RATE)),
        ):
            peaks = compute_peaks("/music/song.aac", buckets=8)
        np.testing.assert_allclose(peaks.maxs, 0.6, atol=0.01)


class _RecordingSink:
    """A ``PeakSink`` that remembers every seed, keyed on the path it was given."""

    def __init__(self) -> None:
        self.seeded: dict[str, Peaks] = {}

    def get(self, path: str) -> Peaks | None:
        return self.seeded.get(path)

    def put(self, path: str, peaks: Peaks) -> None:
        self.seeded[path] = peaks


class PeakSeedingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.addCleanup(set_peak_sink, None)

    def _write(self, name: str, data: np.ndarray, rate: int = _RATE) -> str:
        path = os.path.join(self.dir, name)
        sf.write(path, data, rate, subtype="FLOAT")
        return path

    def _install(self) -> _RecordingSink:
        sink = _RecordingSink()
        set_peak_sink(sink)
        return sink

    def assert_same_peaks(self, actual: Peaks, expected: Peaks) -> None:
        self.assertAlmostEqual(actual.duration, expected.duration)
        np.testing.assert_array_equal(actual.mins, expected.mins)
        np.testing.assert_array_equal(actual.maxs, expected.maxs)

    def test_array_peaks_match_file_peaks(self) -> None:
        rng = np.random.default_rng(3)
        stereo = (rng.random((10_000, 2), dtype=np.float32) * 1.6 - 0.8).astype(np.float32)
        path = self._write("noise.wav", stereo)
        with mock.patch("core.waveform._BLOCK_FRAMES", 1000):
            from_array = peaks_from_array(stereo.T, _RATE, buckets=7)
            from_mono = peaks_from_array(stereo[:, 1], _RATE, buckets=7)
        self.assert_same_peaks(from_array, compute_peaks(path, buckets=7))
        index = (np.arange(10_000) * 7) // 10_000
        expected = [stereo[index == b, 1].max() for b in range(7)]
        np.testing.assert_array_equal(from_mono.maxs, expected)

    def test_empty_array_is_a_decode_error(self) -> None:
        with self.assertRaises(AudioDecodeError):
            peaks_from_array(np.zeros((2, 0), dtype=np.float32), _RATE)

    def test_offer_without_sink_never_computes(self) -> None:
        compute = mock.Mock()
        offer_peaks("/music/a.wav", compute)
        compute.assert_not_called()

    def test_offer_hands_peaks_to_sink(self) -> None:
        sink = self._install()
        peaks = Peaks(1.0, np.zeros(2, dtype=np.float32), np.zeros(2, dtype=np.float32))
        offer_peaks("/music/a.wav", lambda: peaks)
        self.assertIs(sink.seeded["/music/a.wav"], peaks)

    def test_offer_skips_paths_the_sink_already_has(self) -> None:
        sink = self._install()
        peaks = Peaks(1.0, np.zeros(2, dtype=np.float32), np.zeros(2, dtype=np.float32))
        sink.put("/music/a.wav", peaks)
        compute = mock.Mock()
        offer_peaks("/music/a.wav", compute)
        compute.assert_not_called()

    def test_offer_swallows_compute_and_sink_errors(self) -> None:
        sink = self._install()
        offer_peaks("/music/a.wav", mock.Mock(side_effect=RuntimeError("boom")))
        self.assertEqual(sink.seeded, {})
        failing = mock.Mock(get=mock.Mock(return_value=None), put=mock.Mock(side_effect=OSError))
        set_peak_sink(failing)
        peaks = Peaks(1.0, np.zeros(2, dtype=np.float32), np.zeros(2, dtype=np.float32))
        offer_peaks("/music/a.wav", lambda: peaks)
        failing.put.assert_called_once_with("/music/a.wav", peaks)

    def test_full_decode_seeds_native_rate_peaks(self) -> None:
        path = self._write("song.wav", np.stack([_sine(1.0, 0.2), _sine(1.0, 0.7)], axis=1))
        sink = self._install()
        load_audio(path, sr=_RATE * 2)  # resampling must not change the seeded envelope
        self.assert_same_peaks(sink.seeded[path], compute_peaks(path))

    def test_partial_and_stream_decodes_do_not_seed(self) -> None:
        path = self._write("song.wav", _sine(1.0, 0.5))
        sink = self._install()
        load_audio(path, duration=0.5)
        with open(path, "rb") as handle:
            load_audio(handle)
        self.assertEqual(sink.seeded, {})


if __name__ == "__main__":
    unittest.main()
