"""Audio decode boundary, real fixtures and subprocess failures."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import numpy as np
import soundfile as sf

from core.audio_decode import AudioDecodeError, load_audio, read_audio_metadata


class AudioDecodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "audio with spaces.wav"
        self.samples = np.stack(
            [np.linspace(-1.5, 1.5, 8000), np.linspace(0.2, 0.7, 8000)], axis=1
        ).astype(np.float32)
        sf.write(self.path, self.samples, 8000, subtype="FLOAT")

    def test_float_stereo_preserves_samples(self):
        data, rate = load_audio(self.path)
        self.assertEqual(rate, 8000)
        self.assertEqual(data.dtype, np.float32)
        np.testing.assert_array_equal(data, self.samples.T)

    def test_mono_flac_and_duration_before_resample(self):
        path = self.path.with_suffix('.flac')
        sf.write(path, self.samples[:, 1], 8000)
        data, rate = load_audio(path, duration=0.1, sr=16000)
        self.assertEqual((data.shape, rate), ((1600,), 16000))

    def test_stream_restored_and_not_closed(self):
        stream = io.BytesIO(self.path.read_bytes())
        stream.seek(7)
        data, rate = load_audio(stream)
        self.assertEqual(stream.tell(), 7)
        self.assertFalse(stream.closed)
        np.testing.assert_array_equal(data, self.samples.T)
        self.assertEqual(rate, 8000)

    def test_metadata_does_not_decode(self):
        with mock.patch('soundfile.SoundFile.read', side_effect=AssertionError('PCM read')):
            info = read_audio_metadata(self.path)
        self.assertEqual(
            (info.frames, info.channels, info.sample_rate, info.duration_seconds),
            (8000, 2, 8000, 1.0),
        )

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_forced_ffmpeg_preserves_float_and_stream(self):
        stream = io.BytesIO(self.path.read_bytes())
        stream.seek(5)
        data, rate = load_audio(stream, force_ffmpeg=True, duration=0.25)
        self.assertEqual(stream.tell(), 5)
        self.assertFalse(stream.closed)
        self.assertEqual(rate, 8000)
        np.testing.assert_array_equal(data, self.samples[:2000].T)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_aac_fallback_and_metadata(self):
        path = self.path.with_suffix('.m4a')
        subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(self.path), '-c:a', 'aac', str(path)],
            check=True,
        )
        data, rate = load_audio(path)
        self.assertEqual((data.shape[0], rate), (2, 8000))
        self.assertGreater(data.shape[1], 0)
        info = read_audio_metadata(path)
        self.assertAlmostEqual(info.duration_seconds or 0, 1, places=1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_six_channels_keep_order_and_native_rate(self):
        samples = np.tile(np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=np.float32), (480, 1))
        sf.write(self.path, samples, 48000, subtype="FLOAT")
        for forced in (False, True):
            with self.subTest(force_ffmpeg=forced):
                data, rate = load_audio(self.path, force_ffmpeg=forced)
                self.assertEqual(rate, 48000)
                np.testing.assert_array_equal(data, samples.T)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_corrupt_aac_packet_rejects_partial_decode(self):
        import json

        path = self.path.with_suffix(".m4a")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(self.path), "-c:a", "aac", str(path)],
            check=True,
        )
        packet_info = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_packets",
                "-show_entries",
                "packet=pos,size",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        # Establish that this executable can decode the unmodified fixture.
        clean, rate = load_audio(path, force_ffmpeg=True)
        self.assertEqual(rate, 8000)
        self.assertGreater(clean.shape[-1], 0)
        packets = json.loads(packet_info.stdout)["packets"]
        packet = packets[len(packets) // 2]
        with path.open("r+b") as audio:
            audio.seek(int(packet["pos"]))
            # Select a channel element with forbidden AAC-LC prediction so
            # the corrupt packet produces an unambiguous decoder diagnostic.
            audio.write(b"\x00" + b"\xff" * (int(packet["size"]) - 1))
        with self.assertRaises(AudioDecodeError):
            load_audio(path, force_ffmpeg=True)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_first_audio_stream_controls_rate_channels_and_pcm(self):
        second = self.path.with_name("second.wav")
        sf.write(second, np.zeros(16000, dtype=np.float32), 16000)
        container = self.path.with_suffix(".mkv")
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(self.path),
                "-i",
                str(second),
                "-map",
                "0:a:0",
                "-map",
                "1:a:0",
                "-c:a",
                "pcm_f32le",
                str(container),
            ],
            check=True,
        )
        data, rate = load_audio(container, force_ffmpeg=True)
        self.assertEqual(rate, 8000)
        np.testing.assert_array_equal(data, self.samples.T)

    def test_failure_restores_stream_and_chains_cause(self):
        stream = io.BytesIO(b'not audio')
        stream.seek(2)
        with mock.patch('core.audio_decode.resolve_ffprobe', return_value=None):
            with self.assertRaises(AudioDecodeError) as raised:
                load_audio(stream)
        self.assertIsNotNone(raised.exception.__cause__)
        self.assertEqual(stream.tell(), 2)
        self.assertFalse(stream.closed)


class SubprocessDecodeTests(unittest.TestCase):
    def test_rejects_invalid_metadata(self):
        from core.audio_decode import _ffprobe

        for payload in (
            b'{"streams":[]}',
            b'{"streams":[{"sample_rate":"0","channels":2}]}',
            b'bad json',
        ):
            with (
                self.subTest(payload=payload),
                mock.patch('core.audio_decode.resolve_ffprobe', return_value='ffprobe'),
                mock.patch('core.audio_decode._capture', return_value=payload),
            ):
                with self.assertRaises((ValueError, KeyError)):
                    _ffprobe('test')

    def test_rejects_empty_partial_pcm(self):
        from core.audio_decode import AudioMetadata

        for payload in (b'', b'123', b'1234'):
            with (
                self.subTest(payload=payload),
                mock.patch('core.audio_decode._ffprobe', return_value=AudioMetadata(48000, 2)),
                mock.patch('core.audio_decode.resolve_ffmpeg', return_value='ffmpeg'),
                mock.patch('core.audio_decode._capture', return_value=payload),
            ):
                with self.assertRaises(AudioDecodeError):
                    load_audio('test.wav', force_ffmpeg=True)

    def test_stderr_is_drained_and_bounded(self):
        import sys

        from core.audio_decode import _capture

        with self.assertRaises(RuntimeError) as raised:
            _capture(
                [
                    sys.executable,
                    '-c',
                    "import sys; sys.stderr.write('x'*100000+'THE END'); sys.exit(2)",
                ],
                timeout=2,
            )
        self.assertLess(len(str(raised.exception)), 17000)
        self.assertIn('THE END', str(raised.exception))

    def test_timeout_reaps_process_and_closes_pipes(self):
        import sys

        from core.audio_decode import _capture

        popen = subprocess.Popen
        children = []

        def start(*args: Any, **kwargs: Any):
            child = popen(*args, **kwargs)
            children.append(child)
            return child

        with mock.patch('core.audio_decode.subprocess.Popen', side_effect=start):
            with self.assertRaises(TimeoutError):
                _capture([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.05)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

    def test_stream_temporary_file_removed_after_failure(self):
        paths = []

        def fail(path: str):
            paths.append(path)
            self.assertTrue(Path(path).is_file())
            raise RuntimeError('probe failed')

        stream = io.BytesIO(b'bad audio')
        stream.seek(3)
        with mock.patch('core.audio_decode._ffprobe', side_effect=fail):
            with self.assertRaises(AudioDecodeError):
                load_audio(stream, force_ffmpeg=True)
        self.assertEqual(stream.tell(), 3)
        self.assertTrue(paths)
        self.assertFalse(Path(paths[0]).exists())

    def test_stdout_activity_resets_timeout(self):
        import sys

        from core.audio_decode import _capture

        data = _capture(
            [
                sys.executable,
                '-c',
                "import time,sys\nfor i in range(8):\n sys.stdout.buffer.write(b'1234'); sys.stdout.flush(); time.sleep(.04)",
            ],
            timeout=0.15,
        )
        self.assertEqual(data, b'1234' * 8)

    def test_metadata_has_total_timeout_even_with_output(self):
        import sys

        from core.audio_decode import _capture

        with self.assertRaises(TimeoutError):
            _capture(
                [
                    sys.executable,
                    '-c',
                    "import time,sys\nfor i in range(20):\n sys.stdout.write('x'); sys.stdout.flush(); time.sleep(.02)",
                ],
                timeout=0.12,
                total_timeout=True,
            )

    def test_unknown_duration_stays_unknown(self):
        from core.audio_decode import _ffprobe

        payload = b'{"streams":[{"sample_rate":"48000","channels":6}],"format":{"duration":"30"}}'
        with (
            mock.patch('core.audio_decode.resolve_ffprobe', return_value='ffprobe'),
            mock.patch('core.audio_decode._capture', return_value=payload),
        ):
            info = _ffprobe('audio')
        self.assertEqual(info.channels, 6)
        self.assertIsNone(info.duration_seconds)
        self.assertIsNone(info.frames)

    def test_valid_pcm_followed_by_failed_exit_is_rejected(self):
        import sys

        from core.audio_decode import _capture

        with self.assertRaisesRegex(RuntimeError, "status 2"):
            _capture(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'\\x00'*64); sys.stdout.flush(); sys.exit(2)",
                ],
                timeout=2,
            )

    def test_error_diagnostics_reject_pcm_despite_success_exit(self):
        import sys

        from core.audio_decode import _capture

        with self.assertRaisesRegex(RuntimeError, "corrupt packet"):
            _capture(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stdout.buffer.write(b'\\x00'*64); sys.stderr.write('corrupt packet')",
                ],
                timeout=2,
                reject_stderr=True,
            )
