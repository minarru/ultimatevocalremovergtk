"""Tests for external tool path resolution."""

import os
import tempfile
import unittest
from unittest import mock

from core import external_tools


class ExternalToolsTests(unittest.TestCase):
    def test_resolve_ffmpeg_env_override(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = tmp.name
        try:
            with mock.patch.dict(os.environ, {"UVR_FFMPEG": path}, clear=False):
                self.assertEqual(external_tools.resolve_ffmpeg(), path)
        finally:
            os.unlink(path)

    def test_resolve_rubberband_from_path(self):
        with mock.patch("shutil.which", return_value="/usr/bin/rubberband"):
            with mock.patch.dict(os.environ, {}, clear=True):
                os.environ.pop("UVR_RUBBERBAND", None)
                self.assertEqual(external_tools.resolve_rubberband(), "/usr/bin/rubberband")

    def test_ffprobe_override_precedes_sibling(self):
        with (
            tempfile.NamedTemporaryFile() as executable,
            mock.patch.dict(os.environ, {"UVR_FFPROBE": executable.name}),
            mock.patch.object(
                external_tools, "resolve_ffmpeg", side_effect=AssertionError("override must win")
            ),
        ):
            self.assertEqual(external_tools.resolve_ffprobe(), executable.name)

    def test_ffprobe_uses_executable_ffmpeg_sibling(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            sibling = os.path.join(directory, 'ffprobe')
            with open(sibling, 'w') as handle:
                handle.write('')
            os.chmod(sibling, 0o755)
            with mock.patch.object(
                external_tools, 'resolve_ffmpeg', return_value=os.path.join(directory, 'ffmpeg')
            ):
                self.assertEqual(external_tools.resolve_ffprobe(), sibling)

    def test_ffprobe_bundled_then_path(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(external_tools, 'resolve_ffmpeg', return_value=None),
            mock.patch.object(
                external_tools, '_bundled_tool', return_value='/bundle/ffprobe'
            ) as bundled,
            mock.patch('shutil.which', return_value='/usr/bin/ffprobe'),
        ):
            self.assertEqual(external_tools.resolve_ffprobe(), '/bundle/ffprobe')
            bundled.return_value = None
            self.assertEqual(external_tools.resolve_ffprobe(), '/usr/bin/ffprobe')

    def test_external_tools_status_keys(self):
        status = external_tools.external_tools_status()
        self.assertIn("ffmpeg", status)
        self.assertIn("rubberband", status)


if __name__ == "__main__":
    unittest.main()
