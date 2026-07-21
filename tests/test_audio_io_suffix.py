"""Tests for audio path suffix helpers."""

import unittest

from core.audio_io import flac_subtype, replace_audio_suffix


class AudioSuffixTests(unittest.TestCase):
    def test_replace_wav_case_insensitive(self) -> None:
        self.assertEqual(replace_audio_suffix("/tmp/a.wav", ".flac"), "/tmp/a.flac")
        self.assertEqual(replace_audio_suffix("/tmp/a.WAV", ".flac"), "/tmp/a.flac")
        self.assertEqual(replace_audio_suffix("/tmp/a.Wav", ".mp3"), "/tmp/a.mp3")

    def test_replace_non_wav_appends(self) -> None:
        self.assertEqual(replace_audio_suffix("/tmp/a", ".flac"), "/tmp/a.flac")

    def test_flac_subtype(self) -> None:
        self.assertEqual(flac_subtype("24-bit"), "PCM_24")
        self.assertEqual(flac_subtype("16-bit"), "PCM_16")


if __name__ == "__main__":
    unittest.main()
