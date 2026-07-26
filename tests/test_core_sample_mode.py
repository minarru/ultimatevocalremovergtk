import sys
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from core.sample_mode import prepare_input_paths
from core.settings import SettingsModel


class SampleModeTests(unittest.TestCase):
    def test_disabled_returns_original_paths(self):
        settings = SettingsModel({"model_sample_mode": False})
        paths = ["/tmp/song.wav"]
        self.assertEqual(prepare_input_paths(settings, paths), paths)

    def test_enabled_uses_clip_when_generation_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "input.wav")
            with open(source, "wb") as handle:
                handle.write(b"wav")

            settings = SettingsModel(
                {
                    "model_sample_mode": True,
                    "model_sample_mode_duration": 5,
                }
            )

            mock_librosa = MagicMock()
            mock_librosa.load.return_value = (np.zeros(44100), 44100)
            mock_sf = MagicMock()

            with patch("core.sample_mode.paths.SAMPLE_CLIP_PATH", tmp):
                with patch.dict(sys.modules, {"librosa": mock_librosa, "soundfile": mock_sf}):
                    result = prepare_input_paths(settings, [source])
            self.assertEqual(len(result), 1)
            self.assertNotEqual(result[0], source)
            mock_sf.write.assert_called_once()

    def test_clip_failure_reports_fallback_and_keeps_full_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "input.wav")
            with open(source, "wb") as handle:
                handle.write(b"wav")

            settings = SettingsModel(
                {
                    "model_sample_mode": True,
                    "model_sample_mode_duration": 5,
                }
            )
            reported: list[tuple[str, Exception]] = []

            mock_librosa = MagicMock()
            mock_librosa.load.side_effect = RuntimeError("decode failed")

            with patch("core.sample_mode.paths.SAMPLE_CLIP_PATH", tmp):
                with patch.dict(sys.modules, {"librosa": mock_librosa, "soundfile": MagicMock()}):
                    result = prepare_input_paths(
                        settings,
                        [source],
                        on_fallback=lambda path, exc: reported.append((path, exc)),
                    )
            self.assertEqual(result, [source])
            self.assertEqual(len(reported), 1)
            self.assertEqual(reported[0][0], source)
            self.assertIsInstance(reported[0][1], RuntimeError)


if __name__ == "__main__":
    unittest.main()
