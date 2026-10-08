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


class OffsetDecodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ramp.wav"
        self.ramp = np.linspace(-1.0, 1.0, 16000).astype(np.float32)
        sf.write(self.path, self.ramp, 8000, subtype="FLOAT")

    def test_offset_reads_from_the_offset(self):
        data, rate = load_audio(self.path, offset=0.5, duration=1.0)
        self.assertEqual(rate, 8000)
        np.testing.assert_array_equal(data, self.ramp[4000:12000])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_offset_through_ffmpeg(self):
        data, _rate = load_audio(self.path, offset=0.5, duration=1.0, force_ffmpeg=True)
        self.assertEqual(len(data), 8000)
        np.testing.assert_allclose(data, self.ramp[4000:12000], atol=1e-6)

    def test_tiny_offset_is_written_without_an_exponent(self):
        from types import SimpleNamespace
        from typing import cast

        from core.audio_decode import AudioMetadata, _pcm_command

        info = cast(AudioMetadata, SimpleNamespace(sample_rate=8000, channels=1))
        command = _pcm_command("ffmpeg", "/x.wav", info, None, strict=True, offset=1e-05)
        self.assertEqual(command[command.index("-ss") + 1], "0.000010")

    def test_negative_offset_is_rejected(self):
        with self.assertRaises(AudioDecodeError):
            load_audio(self.path, offset=-1.0)

    def test_offset_does_not_seed_whole_file_peaks(self):
        with mock.patch("core.audio_decode._seed_peaks") as seed:
            load_audio(self.path, offset=0.5)
        seed.assert_not_called()


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
    def test_single_damaged_packet_is_filled_with_silence_and_keeps_timing(self):
        import json

        rng = np.random.default_rng(0)
        source = Path(self.tmp.name) / "long.wav"
        sf.write(source, (rng.standard_normal((30 * 8000, 2)) * 0.1).astype(np.float32), 8000)
        path = source.with_suffix(".m4a")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-c:a", "aac", str(path)],
            check=True,
        )
        clean, _rate = load_audio(path, force_ffmpeg=True)
        packets = json.loads(
            subprocess.run(
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
            ).stdout
        )["packets"]
        packet = packets[len(packets) // 2]
        with path.open("r+b") as audio:
            audio.seek(int(packet["pos"]))
            audio.write(b"\x00" + b"\xff" * (int(packet["size"]) - 1))

        notices: list[str] = []
        repaired, rate = load_audio(path, force_ffmpeg=True, on_warning=notices.append)

        self.assertEqual(rate, 8000)
        # The unreadable packet is replaced by silence, not dropped, so the
        # length and everything after the damage stay aligned with the source.
        self.assertEqual(repaired.shape, clean.shape)
        np.testing.assert_allclose(repaired[:, -8000:], clean[:, -8000:], atol=1e-3)
        self.assertEqual(len(notices), 1)
        self.assertIn("silence", notices[0])

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

    def test_ffmpeg_pcm_is_wrapped_without_copying(self):
        from core.audio_decode import AudioMetadata

        interleaved = np.arange(12, dtype='<f4')  # 6 stereo frames, L/R interleaved
        captured = bytearray(interleaved.tobytes())
        with (
            mock.patch('core.audio_decode._ffprobe', return_value=AudioMetadata(48000, 2)),
            mock.patch('core.audio_decode.resolve_ffmpeg', return_value='ffmpeg'),
            mock.patch('core.audio_decode._capture', return_value=captured),
        ):
            data, rate = load_audio('test.m4a', force_ffmpeg=True)

        self.assertEqual(rate, 48000)
        self.assertEqual(data.dtype, np.float32)
        np.testing.assert_array_equal(data, interleaved.reshape(-1, 2).T)
        # A copy of a full track doubles peak memory; the samples must be a
        # writable view over the buffer the subprocess output was read into.
        self.assertTrue(np.shares_memory(data, np.frombuffer(captured, dtype=np.uint8)))
        self.assertTrue(data.flags.writeable)

    def test_ffmpeg_mono_is_a_writable_view(self):
        from core.audio_decode import AudioMetadata

        captured = bytearray(np.arange(4, dtype='<f4').tobytes())
        with (
            mock.patch('core.audio_decode._ffprobe', return_value=AudioMetadata(48000, 1)),
            mock.patch('core.audio_decode.resolve_ffmpeg', return_value='ffmpeg'),
            mock.patch('core.audio_decode._capture', return_value=captured),
        ):
            data, _rate = load_audio('test.m4a', force_ffmpeg=True)

        self.assertEqual(data.shape, (4,))
        self.assertTrue(np.shares_memory(data, np.frombuffer(captured, dtype=np.uint8)))
        self.assertTrue(data.flags.writeable)

    def test_capture_returns_the_read_buffer(self):
        import sys

        from core.audio_decode import _capture

        output = _capture([sys.executable, '-c', 'print("pcm", end="")'], timeout=5)
        self.assertIsInstance(output, bytearray)
        self.assertEqual(output, b'pcm')

    def _tolerant_decode(self, strict_error: BaseException, unfilled: int, filled: int):
        """Run the FFmpeg path with a failing strict pass and stubbed retries.

        ``unfilled`` / ``filled`` are the stereo frame counts of the tolerant
        pass without and with gap filling.
        """
        from core.audio_decode import AudioMetadata

        frame = np.zeros(2, dtype="<f4").tobytes()
        calls: list[list[str]] = []

        def run_tool(command: list[str], **kwargs: Any):
            calls.append(command)
            if "-xerror" in command:
                raise strict_error
            if any("aresample" in part for part in command):
                return bytearray(frame * filled), 8 * filled, b"[aac] damaged packet\n"
            return bytearray(), 8 * unfilled, b"[aac] damaged packet\n"

        notices: list[str] = []
        with (
            mock.patch("core.audio_decode._ffprobe", return_value=AudioMetadata(1000, 2)),
            mock.patch("core.audio_decode.resolve_ffmpeg", return_value="ffmpeg"),
            mock.patch("core.audio_decode._run_tool", side_effect=run_tool),
        ):
            result = load_audio("damaged.m4a", force_ffmpeg=True, on_warning=notices.append)
        return result, notices, calls

    def test_small_loss_is_accepted_with_a_notice(self):
        (data, rate), notices, calls = self._tolerant_decode(
            RuntimeError("decoder error"), unfilled=99_700, filled=100_000
        )
        self.assertEqual((data.shape, rate), ((2, 100_000), 1000))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(notices), 1)
        self.assertIn("300 ms", notices[0])

    def test_loss_above_budget_is_rejected(self):
        with self.assertRaisesRegex(AudioDecodeError, "too damaged"):
            self._tolerant_decode(RuntimeError("decoder error"), unfilled=99_000, filled=100_000)

    def test_repair_limit_tracks_the_silence_budget(self):
        from core.audio_decode import _repair_output_limit

        # 99_700 of 100_000 stereo frames is inside the 0.5% budget, so the cap
        # must leave that fill intact. A thousand real frames must not allow a
        # multi-megabyte pad.
        self.assertGreaterEqual(_repair_output_limit(8 * 99_700, 2), 8 * 100_000)
        self.assertLess(_repair_output_limit(8 * 1_000, 2), 8 * 1_100)
        self.assertEqual(_repair_output_limit(0, 2), 0)

    def test_gap_fill_over_the_budget_is_stopped(self):
        from core.audio_decode import (
            AudioMetadata,
            _decode_damaged,
            _OutputLimitExceeded,
            _repair_output_limit,
        )

        limits: list[int] = []

        def run_tool(command: list[str], **kwargs: Any):
            if any("aresample" in part for part in command):
                limit = kwargs.get("max_output_bytes")
                if not isinstance(limit, int):
                    raise AssertionError("gap fill must be given an integer byte cap")
                limits.append(limit)
                raise _OutputLimitExceeded(b"[aac] timestamp gap\n")
            return bytearray(), 8 * 1_000, b""

        with (
            mock.patch("core.audio_decode._run_tool", side_effect=run_tool),
            self.assertRaisesRegex(ValueError, "silence budget"),
        ):
            _decode_damaged("ffmpeg", "song.m4a", AudioMetadata(48_000, 2), None, None)
        self.assertEqual(limits, [_repair_output_limit(8 * 1_000, 2)])
        self.assertLess(limits[0], 8 * 1_100)

    def test_run_tool_stops_when_stdout_passes_the_cap(self):
        import sys

        from core.audio_decode import _OutputLimitExceeded, _run_tool

        script = 'import sys; sys.stdout.buffer.write(b"x" * (1 << 20)); sys.stdout.buffer.flush()'
        with self.assertRaises(_OutputLimitExceeded) as caught:
            _run_tool(
                [sys.executable, "-c", script],
                timeout=5,
                max_output_bytes=1024,
            )
        self.assertNotIn(b"x" * 64, caught.exception.errors)
        self.assertNotIn("xxxx", str(caught.exception))

    def test_concealed_errors_without_lost_audio_still_notify(self):
        (data, _rate), notices, _calls = self._tolerant_decode(
            RuntimeError("decoder error"), unfilled=100_000, filled=100_000
        )
        self.assertEqual(data.shape, (2, 100_000))
        self.assertEqual(len(notices), 1)
        self.assertIn("glitches", notices[0])

    def test_timeout_is_not_retried(self):
        with self.assertRaises(AudioDecodeError):
            self._tolerant_decode(TimeoutError("no PCM"), unfilled=100_000, filled=100_000)

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
