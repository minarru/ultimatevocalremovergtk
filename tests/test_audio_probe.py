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


class AudioProbeFallbackTests(unittest.TestCase):
    def test_ffmpeg_readability_checks_only_three_seconds(self):
        from unittest import mock

        from core.audio_decode import AudioMetadata
        from core.audio_probe import probe_audio

        with tempfile.NamedTemporaryFile() as source:
            with (
                mock.patch('soundfile.info', side_effect=RuntimeError('unsupported')),
                mock.patch(
                    'core.audio_probe.read_audio_metadata', return_value=AudioMetadata(48000, 6)
                ),
                mock.patch('core.audio_probe.load_audio') as decode,
            ):
                result = probe_audio(source.name)
        self.assertTrue(result.readable)
        self.assertIsNone(result.duration_seconds)
        self.assertEqual(result.channels, 6)
        decode.assert_called_once_with(source.name, duration=3)

    def test_duration_never_falls_back_to_pcm(self):
        from unittest import mock

        from core.audio_probe import audio_duration_seconds

        with tempfile.NamedTemporaryFile() as source:
            with (
                mock.patch(
                    'core.audio_probe.read_audio_metadata', side_effect=RuntimeError('bad metadata')
                ),
                mock.patch('core.audio_probe.load_audio', side_effect=AssertionError('PCM read')),
            ):
                self.assertIsNone(audio_duration_seconds(source.name))

    def test_invalid_soundfile_metadata_is_not_readable(self):
        from types import SimpleNamespace
        from unittest import mock

        from core.audio_probe import probe_audio

        with (
            tempfile.NamedTemporaryFile() as source,
            mock.patch(
                "soundfile.info",
                return_value=SimpleNamespace(samplerate=0, channels=0, frames=10, format="WAV"),
            ),
            mock.patch("core.audio_decode.resolve_ffprobe", return_value=None),
        ):
            result = probe_audio(source.name)
        self.assertFalse(result.readable)
