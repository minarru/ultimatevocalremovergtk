"""Sample clips preserve decoded precision and publish only complete WAV files."""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from core.sample_mode import (
    _clip_cache_path,
    fitted_sample_start,
    has_custom_start,
    prepare_input_paths,
    prune_sample_starts,
    sample_start,
)
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

    def _expected(self, start: int) -> np.ndarray:
        expected, _ = sf.read(self.source, start=start, frames=8000, dtype='float32')
        return expected

    def test_start_offsets_the_clip(self):
        self.settings.process.sample_starts = {str(self.source.resolve()): 0.5}
        [clip] = prepare_input_paths(self.settings, [str(self.source)])
        np.testing.assert_array_equal(sf.read(clip, dtype='float32')[0], self._expected(4000))

    def test_fitted_start_matches_an_unknown_length_and_a_short_file(self):
        self.assertEqual(fitted_sample_start(12.0, 30, None), 12.0)
        self.assertEqual(fitted_sample_start(15.0, 30, 40), 10.0)

    def test_start_is_pulled_back_to_fit_the_file(self):
        self.settings.process.sample_starts = {str(self.source.resolve()): 1.5}
        [clip] = prepare_input_paths(self.settings, [str(self.source)])
        np.testing.assert_array_equal(sf.read(clip, dtype='float32')[0], self._expected(8000))

    def test_zero_start_keeps_the_original_cache_name(self):
        digest = hashlib.md5(b'/tmp/music.m4a:5', usedforsecurity=False).hexdigest()[:12]
        clip = _clip_cache_path('/tmp/music.m4a', 5, 0.0)
        self.assertTrue(clip.endswith(f'music_5s_v2_{digest}.wav'))
        self.assertEqual(clip, _clip_cache_path('/tmp/music.m4a', 5))

    def test_each_start_gets_its_own_clip(self):
        first = prepare_input_paths(self.settings, [str(self.source)])
        self.settings.process.sample_starts = {str(self.source.resolve()): 0.5}
        second = prepare_input_paths(self.settings, [str(self.source)])
        self.assertNotEqual(first, second)
        self.assertEqual(len(list(self.cache.iterdir())), 2)

    def test_relative_input_path_finds_its_start(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)
        self.settings.process.sample_starts = {str(self.source.resolve()): 0.5}
        [clip] = prepare_input_paths(self.settings, ['input.flac'])
        np.testing.assert_array_equal(sf.read(clip, dtype='float32')[0], self._expected(4000))

    def test_start_helpers(self):
        starts = {'/in/a.wav': 12.0}
        self.assertEqual(sample_start(starts, '/in/a.wav'), 12.0)
        self.assertEqual(sample_start(starts, '/in/b.wav'), 0.0)
        self.assertTrue(has_custom_start(starts, ['/in/b.wav', '/in/a.wav']))
        self.assertFalse(has_custom_start(starts, ['/in/b.wav']))
        self.assertEqual(prune_sample_starts(starts, ['/in/b.wav']), {})
        self.assertEqual(prune_sample_starts(starts, ['/in/a.wav']), starts)

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
