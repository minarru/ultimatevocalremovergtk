"""Real compressed audio across shared decoder consumers; no model weights."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from core.external_tools import resolve_ffmpeg
from core.sample_mode import prepare_input_paths
from core.settings import Settings


@unittest.skipUnless(resolve_ffmpeg(), 'FFmpeg is required for compressed input fixtures')
class SharedDecoderIntegrationTests(unittest.TestCase):
    def test_aac_loading_sample_mode_and_error_metadata(self):
        from core.audio_decode import load_audio
        from core.audio_probe import audio_duration_seconds, probe_audio
        from core.error_context import probe_audio_file
        from engines.apollo import load_audio as apollo_load
        from engines.mix import prepare_mix
        from ml.spec_utils import load_audio as tools_load

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'original.wav'
            compressed = root / 'input.m4a'
            t = np.arange(16000, dtype=np.float32) / 8000
            audio = np.stack([0.2 * np.sin(2 * np.pi * f * t) for f in (220, 330)], axis=1)
            sf.write(source, audio, 8000, subtype='FLOAT')
            subprocess.run(
                [
                    str(resolve_ffmpeg()),
                    '-nostdin',
                    '-v',
                    'error',
                    '-i',
                    str(source),
                    '-c:a',
                    'aac',
                    str(compressed),
                ],
                check=True,
                timeout=20,
            )
            decoded, rate = load_audio(compressed, sr=44100)
            self.assertEqual(rate, 44100)
            self.assertEqual(decoded.shape[0], 2)
            self.assertTrue(np.isfinite(decoded).all())
            np.testing.assert_array_equal(prepare_mix(str(compressed)), decoded)
            np.testing.assert_array_equal(tools_load(str(compressed)), decoded)
            tensor, apollo_rate = apollo_load(compressed)
            np.testing.assert_array_equal(tensor.numpy(), decoded)
            self.assertEqual(apollo_rate, rate)
            probe = probe_audio(str(compressed))
            self.assertTrue(probe.readable)
            self.assertEqual(probe.channels, 2)
            duration = audio_duration_seconds(str(compressed))
            self.assertIsNotNone(duration)
            self.assertAlmostEqual(duration or 0, 2.0, delta=0.15)
            info = probe_audio_file(str(compressed))
            self.assertTrue(info['valid'])
            self.assertEqual((info['channels'], info['sample_rate']), (2, 8000))
            settings = Settings.from_flat(
                {'model_sample_mode': True, 'model_sample_mode_duration': 1}
            )
            with patch('core.sample_mode.paths.SAMPLE_CLIP_PATH', str(root / 'clips')):
                [clip] = prepare_input_paths(settings, [str(compressed)])
            clip_info = sf.info(clip)
            self.assertEqual(
                (clip_info.subtype, clip_info.frames, clip_info.channels), ('FLOAT', 8000, 2)
            )
