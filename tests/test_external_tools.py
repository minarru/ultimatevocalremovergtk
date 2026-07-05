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

    def test_external_tools_status_keys(self):
        status = external_tools.external_tools_status()
        self.assertIn("ffmpeg", status)
        self.assertIn("rubberband", status)


if __name__ == "__main__":
    unittest.main()
