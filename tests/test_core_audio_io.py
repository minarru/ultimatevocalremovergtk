import unittest
from unittest.mock import MagicMock, patch

from bundled.constants import WAV
from core.audio_io import flac_export_parameters, resolve_wav_type_set, save_format
from core.settings import SettingsModel


class FlacExportParametersTests(unittest.TestCase):
    def test_sixteen_bit(self):
        self.assertEqual(flac_export_parameters("16-bit"), ["-sample_fmt", "s16"])

    def test_twenty_four_bit(self):
        self.assertEqual(flac_export_parameters("24-bit"), ["-sample_fmt", "s24"])

    def test_unknown_defaults_to_sixteen(self):
        self.assertEqual(flac_export_parameters("unknown"), ["-sample_fmt", "s16"])


class SaveFormatFlacTests(unittest.TestCase):
    @patch("pydub.AudioSegment")
    def test_flac_export_uses_bit_depth_parameters(self, audio_segment_cls):
        segment = MagicMock()
        audio_segment_cls.from_wav.return_value = segment

        save_format("/tmp/stem.wav", "FLAC", "320k", "24-bit")

        segment.export.assert_called_once_with(
            "/tmp/stem.flac",
            format="flac",
            parameters=["-sample_fmt", "s24"],
        )


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
