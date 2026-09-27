import os
import tempfile
import typing
import unittest
from pathlib import Path
from unittest.mock import patch

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


def _ffmpeg_has_libopus() -> bool:
    import subprocess

    from core.external_tools import resolve_ffmpeg

    path = resolve_ffmpeg()
    if not path:
        return False
    try:
        completed = subprocess.run(
            [path, "-hide_banner", "-encoders"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "libopus" in completed.stdout


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


def _ffmpeg_has_encoder(name: str) -> bool:
    import subprocess

    from core.external_tools import resolve_ffmpeg

    path = resolve_ffmpeg()
    if not path:
        return False
    try:
        completed = subprocess.run(
            [path, "-hide_banner", "-encoders"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return name in completed.stdout


def _write_wav(path: str, frames: int = 4410, channels: int = 2, subtype: str = "FLOAT"):
    import numpy as np
    import soundfile as sf

    rng = np.random.default_rng(0)
    data = (rng.standard_normal((frames, channels)) * 0.3).astype(np.float32)
    data[frames // 2, 0] = 1.25  # above full scale, as float stems can be
    data[frames // 3, -1] = -1.5
    sf.write(path, data if channels > 1 else data[:, 0], 44100, subtype=subtype)
    return data


class _FakeFfmpeg:
    """Stand-in for ``subprocess.run`` that records commands and writes outputs."""

    def __init__(self, returncodes: list[int] | None = None) -> None:
        self.commands: list[list[str]] = []
        self._returncodes = list(returncodes or [])

    def __call__(self, command: list[str], **_kwargs: typing.Any):
        import subprocess

        self.commands.append(list(command))
        code = self._returncodes.pop(0) if self._returncodes else 0
        Path(command[-1]).write_bytes(b"partial" if code else b"encoded")
        stderr = b"[libmp3lame] encoder not found\n" if code else b""
        return subprocess.CompletedProcess(command, code, b"", stderr)


class SaveFormatFlacTests(unittest.TestCase):
    def test_missing_wav_is_an_export_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = os.path.join(folder, "missing.wav")
            with self.assertRaisesRegex(RuntimeError, "missing"):
                save_format(missing, WAV, "320k")

    def test_streamed_flac_is_bit_identical_to_whole_file_conversion(self):
        import numpy as np
        import soundfile as sf

        for bit_set, channels in (("24-bit", 2), ("16-bit", 2), ("24-bit", 1)):
            with (
                self.subTest(bits=bit_set, channels=channels),
                tempfile.TemporaryDirectory() as folder,
            ):
                wav_path = os.path.join(folder, "stem.wav")
                _write_wav(wav_path, frames=150_000, channels=channels)
                # The previous implementation: read everything as float64, write FLAC.
                reference = os.path.join(folder, "reference.flac")
                data, rate = sf.read(wav_path, always_2d=False)
                sf.write(reference, data, rate, format="FLAC", subtype=flac_subtype(bit_set))

                output = save_format(wav_path, "FLAC", "320k", bit_set)

                self.assertEqual(output, os.path.join(folder, "stem.flac"))
                self.assertFalse(os.path.exists(wav_path))
                np.testing.assert_array_equal(
                    sf.read(output, dtype="int32")[0], sf.read(reference, dtype="int32")[0]
                )
                self.assertEqual(sorted(os.listdir(folder)), ["reference.flac", "stem.flac"])

    def test_streamed_flac_reads_in_bounded_blocks(self):
        import tracemalloc

        with tempfile.TemporaryDirectory() as folder:
            wav_path = os.path.join(folder, "stem.wav")
            data = _write_wav(wav_path, frames=1_000_000)
            tracemalloc.start()
            try:
                save_format(wav_path, "FLAC", "320k", "24-bit")
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
        # Whole-file float64 reading needed twice the float32 stem size.
        self.assertLess(peak, data.nbytes / 2)

    def test_uppercase_wav_suffix_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            wav_path = os.path.join(folder, "stem.WAV")
            _write_wav(wav_path)
            output = save_format(wav_path, "FLAC", "320k", "16-bit")
            self.assertEqual(output, os.path.join(folder, "stem.flac"))
            self.assertTrue(os.path.isfile(output))

    @patch("core.audio_io.resolve_ffmpeg", return_value="ffmpeg")
    def test_flac_falls_back_to_ffmpeg_with_sample_format(self, _resolve: typing.Any):
        fake = _FakeFfmpeg()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("core.audio_io._stream_flac", side_effect=RuntimeError("boom")),
            patch("core.audio_io.subprocess.run", side_effect=fake),
        ):
            wav_path = os.path.join(folder, "stem.wav")
            _write_wav(wav_path)
            output = save_format(wav_path, "FLAC", "320k", "24-bit")
            self.assertEqual(output, os.path.join(folder, "stem.flac"))
        self.assertEqual(len(fake.commands), 1)
        self.assertEqual(fake.commands[0][9:-1], ["-sample_fmt", "s24", "-f", "flac"])


class FfmpegExportTests(unittest.TestCase):
    def _export(self, save_format_sel: str, fake: _FakeFfmpeg, **kwargs: typing.Any):
        with tempfile.TemporaryDirectory() as folder:
            wav_path = os.path.join(folder, "stem.wav")
            _write_wav(wav_path)
            with (
                patch("core.audio_io.resolve_ffmpeg", return_value="ffmpeg"),
                patch("core.audio_io.subprocess.run", side_effect=fake),
            ):
                try:
                    output = save_format(wav_path, save_format_sel, "320k", **kwargs)
                except RuntimeError as exc:
                    output = exc
            return output, wav_path, sorted(os.listdir(folder))

    def test_mp3_encodes_the_wav_directly_in_pydub_argument_order(self):
        fake = _FakeFfmpeg()
        output, wav_path, files = self._export("MP3", fake)
        self.assertEqual(files, ["stem.mp3"])
        command = fake.commands[0]
        self.assertEqual(
            command[:-1],
            ["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "wav", "-i", wav_path]
            + ["-acodec", "libmp3lame", "-b:a", "320k", "-f", "mp3"],
        )
        self.assertEqual(os.path.dirname(command[-1]), os.path.dirname(wav_path))
        self.assertEqual(output, os.path.join(os.path.dirname(wav_path), "stem.mp3"))

    def test_mp3_falls_back_to_ffmpegs_default_encoder(self):
        fake = _FakeFfmpeg(returncodes=[1, 0])
        _output, _wav, files = self._export("MP3", fake)
        self.assertEqual(files, ["stem.mp3"])
        self.assertIn("libmp3lame", fake.commands[0])
        self.assertNotIn("-acodec", fake.commands[1])
        self.assertEqual(fake.commands[1][9:11], ["-b:a", "320k"])

    def test_failed_encode_keeps_the_wav_and_leaves_no_partial_output(self):
        output, _wav, files = self._export("MP3", _FakeFfmpeg(returncodes=[1, 1]))
        self.assertIsInstance(output, RuntimeError)
        self.assertIn("encoder not found", str(output))
        self.assertEqual(files, ["stem.wav"])

    def test_opus_uses_libopus_target_bitrate(self):
        fake = _FakeFfmpeg()
        _output, _wav, files = self._export("OPUS", fake, opus_bit_set="128k")
        self.assertEqual(files, ["stem.opus"])
        self.assertEqual(
            fake.commands[0][9:-1],
            ["-acodec", "libopus", "-b:a", "128k"]
            + ["-application", "audio", "-vbr", "on", "-ar", "48000", "-f", "opus"],
        )

    def test_opus_defaults_to_192k_target(self):
        fake = _FakeFfmpeg()
        self._export("OPUS", fake)
        self.assertEqual(fake.commands[0][12], "192k")

    def test_missing_ffmpeg_is_an_export_failure(self):
        for fmt in ("MP3", "OPUS"):
            with (
                self.subTest(fmt=fmt),
                tempfile.TemporaryDirectory() as folder,
                patch("core.audio_io.resolve_ffmpeg", return_value=None),
            ):
                wav_path = os.path.join(folder, "stem.wav")
                _write_wav(wav_path)
                with self.assertRaisesRegex(RuntimeError, "ffmpeg"):
                    save_format(wav_path, fmt, "320k")

    @unittest.skipUnless(_ffmpeg_has_encoder("libmp3lame"), "ffmpeg with libmp3lame is required")
    def test_real_mp3_export(self) -> None:
        import soundfile as sf

        with tempfile.TemporaryDirectory() as folder:
            wav_path = os.path.join(folder, "stem.wav")
            _write_wav(wav_path, frames=44100)
            output = save_format(wav_path, "MP3", "320k")
            self.assertEqual(os.listdir(folder), ["stem.mp3"])
            decoded, rate = sf.read(output)
            self.assertEqual(rate, 44100)
            self.assertAlmostEqual(len(decoded) / rate, 1.0, delta=0.1)

    @unittest.skipUnless(_ffmpeg_has_libopus(), "ffmpeg with libopus is required")
    def test_opus_export_writes_ogg_opus_container(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            wav_path = os.path.join(folder, "stem.wav")
            _write_wav(wav_path, frames=2205)
            output = save_format(wav_path, "OPUS", "320k", opus_bit_set="192k")
            self.assertEqual(output, os.path.join(folder, "stem.opus"))
            self.assertEqual(os.listdir(folder), ["stem.opus"])
            with open(output, "rb") as handle:
                self.assertEqual(handle.read(4), b"OggS")


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
