"""Sample clips preserve decoded precision and publish only complete WAV files."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from core.sample_mode import _clip_cache_path, prepare_input_paths
from core.settings import Settings


class SampleModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'input.flac'
        self.cache = self.root / 'clips'
        self.audio = np.column_stack((np.linspace(-0.2, 0.3, 16000), np.zeros(16000)))
        sf.write(self.source, self.audio, 8000, subtype='PCM_24')
        self.settings = Settings.from_flat(
            {'model_sample_mode': True, 'model_sample_mode_duration': 1}
        )
        self.paths = patch('core.sample_mode.paths.SAMPLE_CLIP_PATH', str(self.cache))
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def test_disabled_returns_original_paths(self):
        self.settings.process.sample_mode = False
        self.assertEqual(prepare_input_paths(self.settings, [str(self.source)]), [str(self.source)])
        self.assertFalse(self.cache.exists())

    def test_clip_is_float_wav_with_native_rate_channels_and_duration(self):
        [clip] = prepare_input_paths(self.settings, [str(self.source)])
        info = sf.info(clip)
        self.assertEqual(Path(clip).suffix, '.wav')
        self.assertEqual((info.format, info.subtype), ('WAV', 'FLOAT'))
        self.assertEqual((info.frames, info.samplerate, info.channels), (8000, 8000, 2))
        expected, _ = sf.read(self.source, frames=8000, dtype='float32')
        actual, _ = sf.read(clip, dtype='float32')
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(list(self.cache.iterdir()), [Path(clip)])

    def test_cached_clip_is_reused_without_decoding(self):
        clips = prepare_input_paths(self.settings, [str(self.source)])
        with patch('soundfile.SoundFile', side_effect=AssertionError('decoded cached input')):
            self.assertEqual(prepare_input_paths(self.settings, [str(self.source)]), clips)

    def test_cache_name_is_versioned_and_independent_of_input_extension(self):
        clip = _clip_cache_path('/tmp/music.m4a', 5)
        self.assertTrue(clip.endswith('.wav'))
        self.assertIn('v2', Path(clip).name)

    def test_partial_write_is_removed_and_fallback_reported(self):
        failures = []

        def fail_write(path: str, *args: object, **kwargs: object) -> None:
            Path(path).write_bytes(b'partial')
            raise OSError('disk full')

        with patch('soundfile.write', side_effect=fail_write):
            paths = prepare_input_paths(
                self.settings, [str(self.source)], on_fallback=lambda p, e: failures.append((p, e))
            )
        self.assertEqual(paths, [str(self.source)])
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0][1], OSError)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_failed_publication_removes_temporary_clip(self):
        failures = []
        with patch('core.sample_mode.os.replace', side_effect=OSError('rename failed')):
            paths = prepare_input_paths(
                self.settings, [str(self.source)], on_fallback=lambda p, e: failures.append(e)
            )
        self.assertEqual(paths, [str(self.source)])
        self.assertEqual(len(failures), 1)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_missing_source_is_preserved(self):
        missing = str(self.root / 'missing.wav')
        self.assertEqual(prepare_input_paths(self.settings, [missing]), [missing])


if __name__ == '__main__':
    unittest.main()
