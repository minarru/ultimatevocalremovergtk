import os
import tempfile
import typing
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bundled.constants import WAV
from core.audio_io import (
    flac_export_parameters,
    flac_subtype,
    replace_audio_suffix,
    resolve_wav_type_set,
    save_format,
)
from core.settings import Settings

_REPO = Path(__file__).resolve().parents[1]


class SaveFormatHomeTests(unittest.TestCase):
    def test_run_loop_imports_audio_io_save_format(self) -> None:
        source = (_REPO / "core" / "run_loop.py").read_text(encoding="utf-8")
        self.assertRegex(source, r"from core\.audio_io import [^\n]*\bsave_format\b")
        self.assertNotIn("engines.separate", source)
        self.assertNotIn("engines.export", source)

    def test_ensembler_imports_audio_io_save_format(self) -> None:
        source = (_REPO / "core" / "ensembler.py").read_text(encoding="utf-8")
        self.assertIn("from core.audio_io import save_format", source)
        self.assertNotIn("engines.separate", source)
        self.assertNotIn("engines.export", source)


class FlacExportParametersTests(unittest.TestCase):
    def test_sixteen_bit(self):
        self.assertEqual(flac_export_parameters("16-bit"), ["-sample_fmt", "s16"])

    def test_twenty_four_bit(self):
        self.assertEqual(flac_export_parameters("24-bit"), ["-sample_fmt", "s24"])

    def test_unknown_defaults_to_sixteen(self):
        self.assertEqual(flac_export_parameters("unknown"), ["-sample_fmt", "s16"])

    def test_flac_subtype_and_suffix_helpers(self):
        self.assertEqual(flac_subtype("24-bit"), "PCM_24")
        self.assertEqual(replace_audio_suffix("/tmp/a.WAV", ".flac"), "/tmp/a.flac")


class SaveFormatFlacTests(unittest.TestCase):
    def test_missing_wav_is_an_export_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = os.path.join(folder, "missing.wav")
            with self.assertRaisesRegex(RuntimeError, "missing"):
                save_format(missing, WAV, "320k")

    @patch("soundfile.write")
    @patch("soundfile.read", return_value=(MagicMock(), 44100))
    @patch("os.remove")
    @patch("os.path.isfile", return_value=True)
    def test_direct_flac_rewrite_skips_pydub(
        self,
        _isfile: typing.Any,
        remove: typing.Any,
        _read: typing.Any,
        write: typing.Any,
    ):
        output = save_format("/tmp/stem.wav", "FLAC", "320k", "24-bit")
        write.assert_called_once()
        self.assertEqual(write.call_args[0][0], "/tmp/stem.flac")
        self.assertEqual(write.call_args.kwargs["subtype"], "PCM_24")
        remove.assert_called_once_with("/tmp/stem.wav")
        self.assertEqual(output, "/tmp/stem.flac")

    @patch("pydub.AudioSegment")
    @patch("soundfile.read", side_effect=RuntimeError("boom"))
    @patch("os.path.isfile", return_value=True)
    def test_flac_export_falls_back_to_pydub_parameters(
        self,
        _isfile: typing.Any,
        _read: typing.Any,
        audio_segment_cls: typing.Any,
    ):
        segment = MagicMock()
        audio_segment_cls.from_wav.return_value = segment

        with patch("os.remove"):
            output = save_format("/tmp/stem.wav", "FLAC", "320k", "24-bit")

        segment.export.assert_called_once_with(
            "/tmp/stem.flac",
            format="flac",
            parameters=["-sample_fmt", "s24"],
        )
        self.assertEqual(output, "/tmp/stem.flac")

    @patch("core.external_tools.configure_pydub_ffmpeg", return_value=None)
    @patch("os.path.isfile", return_value=True)
    def test_missing_mp3_encoder_is_an_export_failure(
        self, _isfile: typing.Any, _configure: typing.Any
    ):
        with self.assertRaisesRegex(RuntimeError, "ffmpeg"):
            save_format("/tmp/stem.wav", "MP3", "320k")


class ResolveWavTypeSetTests(unittest.TestCase):
    def test_pcm_16_passthrough(self):
        settings = Settings.from_flat({"wav_type_set": "PCM_16", "save_format": WAV})
        self.assertEqual(resolve_wav_type_set(settings), "PCM_16")

    def test_64_bit_float_non_wav(self):
        settings = Settings.from_flat({"wav_type_set": "64-bit Float", "save_format": "FLAC"})
        self.assertEqual(resolve_wav_type_set(settings), "FLOAT")

    def test_64_bit_float_wav(self):
        settings = Settings.from_flat({"wav_type_set": "64-bit Float", "save_format": WAV})
        self.assertEqual(resolve_wav_type_set(settings), "DOUBLE")


if __name__ == "__main__":
    unittest.main()
