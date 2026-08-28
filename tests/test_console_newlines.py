"""Console log lines that are complete messages must end with a newline."""

from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock

from bundled.constants import PROCESS_STOPPED_BY_USER
from core.audio_tools import AudioTools
from core.settings import Settings
from engines.mdx_classic_batch import mdx_oom_reduce_batch_message


class ConsoleNewlineTests(unittest.TestCase):
    def test_process_stopped_ends_with_newline(self) -> None:
        self.assertTrue(PROCESS_STOPPED_BY_USER.endswith("\n"))

    def test_mdx_oom_reduce_batch_message_ends_with_newline(self) -> None:
        text = mdx_oom_reduce_batch_message(4)
        self.assertEqual(text, "CUDA OOM — reducing MDX batch size to 4\n")

    def test_match_inputs_processing_line_ends_with_newline(self) -> None:
        captured: list[str] = []
        settings = Settings.defaults()
        with tempfile.TemporaryDirectory() as tmp:
            settings.process.export_path = tmp
            tool = AudioTools(settings)
            matchering = mock.MagicMock()
            with (
                mock.patch.dict(sys.modules, {"matchering": matchering}),
                mock.patch.object(tool, "_save_format"),
            ):
                tool.match_inputs(("target.wav", "reference.wav"), "track", captured.append)
        self.assertTrue(captured)
        self.assertTrue(all(line.endswith("\n") for line in captured), captured)

    def test_align_saving_inverted_track_line_has_newline(self) -> None:
        import inspect

        from ml.spec_utils import align_audio

        source = inspect.getsource(align_audio)
        self.assertIn("Saving inverted track...\\n", source)
