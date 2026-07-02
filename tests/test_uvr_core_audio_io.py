import unittest

from data.constants import WAV
from uvr_core.audio_io import resolve_wav_type_set
from uvr_core.settings import SettingsModel


class ResolveWavTypeSetTests(unittest.TestCase):
    def test_pcm_16_passthrough(self):
        settings = SettingsModel({"wav_type_set": "PCM_16", "save_format": WAV})
        self.assertEqual(resolve_wav_type_set(settings), "PCM_16")

    def test_64_bit_float_non_wav(self):
        settings = SettingsModel({"wav_type_set": "64-bit Float", "save_format": "FLAC"})
        self.assertEqual(resolve_wav_type_set(settings), "FLOAT")

    def test_64_bit_float_wav(self):
        settings = SettingsModel({"wav_type_set": "64-bit Float", "save_format": WAV})
        self.assertEqual(resolve_wav_type_set(settings), "DOUBLE")


if __name__ == "__main__":
    unittest.main()
