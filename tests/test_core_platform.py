"""Tests for cross-platform path resolution."""

import os
import unittest
from unittest import mock

from uvr_core import platform as uvr_platform


class PlatformPathTests(unittest.TestCase):
    def test_user_data_dir_respects_env_override(self):
        with mock.patch.dict(os.environ, {"UVR_DATA_DIR": "/custom/data"}, clear=False):
            self.assertEqual(
                uvr_platform.user_data_dir("/ignored"),
                os.path.abspath("/custom/data"),
            )

    def test_user_data_dir_uses_writable_base_path(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("UVR_DATA_DIR", None)
            with mock.patch("os.access", return_value=True):
                self.assertEqual(uvr_platform.user_data_dir("/writable/root"), "/writable/root")

    def test_default_user_data_dir_linux(self):
        with mock.patch.object(uvr_platform, "system_name", return_value="Linux"):
            with mock.patch.dict(
                os.environ,
                {"XDG_DATA_HOME": "/xdg/data", "HOME": "/home/user"},
                clear=False,
            ):
                self.assertEqual(
                    uvr_platform.default_user_data_dir(),
                    "/xdg/data/ultimatevocalremover",
                )

    def test_default_user_data_dir_windows(self):
        with mock.patch.object(uvr_platform, "system_name", return_value="Windows"):
            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": "C:\\Users\\me\\AppData\\Local", "HOME": "C:\\Users\\me"},
                clear=False,
            ):
                expected = os.path.join(
                    "C:\\Users\\me\\AppData\\Local",
                    "UltimateVocalRemover",
                )
                self.assertEqual(uvr_platform.default_user_data_dir(), expected)

    def test_default_user_data_dir_macos(self):
        with mock.patch.object(uvr_platform, "system_name", return_value="Darwin"):
            with mock.patch.dict(os.environ, {"HOME": "/Users/me"}, clear=False):
                self.assertEqual(
                    uvr_platform.default_user_data_dir(),
                    "/Users/me/Library/Application Support/ultimatevocalremover",
                )

    def test_user_cache_dir_respects_env_override(self):
        with mock.patch.dict(os.environ, {"UVR_CACHE_DIR": "/tmp/uvr-cache"}, clear=False):
            self.assertEqual(uvr_platform.user_cache_dir(), "/tmp/uvr-cache")

    def test_default_user_cache_dir_linux(self):
        with mock.patch.object(uvr_platform, "system_name", return_value="Linux"):
            with mock.patch.dict(
                os.environ,
                {"XDG_CACHE_HOME": "/xdg/cache", "HOME": "/home/user"},
                clear=False,
            ):
                self.assertEqual(uvr_platform.default_user_cache_dir(), "/xdg/cache/uvr")


if __name__ == "__main__":
    unittest.main()
