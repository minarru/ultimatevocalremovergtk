"""Cheap audio metadata probing without a PCM decode."""

from __future__ import annotations

import os
import tempfile
import unittest
import wave

from core.audio_probe import audio_duration_seconds


class AudioDurationSecondsTests(unittest.TestCase):
    def test_reads_wav_duration_without_pcm_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clip.wav")
            with wave.open(path, "w") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(44100)
                handle.writeframes(b"\x00\x00" * (44100 * 2))
            duration = audio_duration_seconds(path)
        self.assertIsNotNone(duration)
        self.assertAlmostEqual(duration or 0.0, 1.0, places=2)

    def test_missing_path_returns_none(self) -> None:
        missing = os.path.join(tempfile.gettempdir(), "uvr-no-such-duration.wav")
        self.assertFalse(os.path.isfile(missing))
        self.assertIsNone(audio_duration_seconds(missing))
