"""Tests for fork release metadata and semver helpers."""
import typing

import json
import unittest
from unittest.mock import patch

from core.downloads import DownloadManager
from core.version_info import (
    clear_release_cache,
    is_newer,
    load_release_metadata,
    parse_version,
    release_update_status,
)


class ParseVersionTests(unittest.TestCase):
    def test_parse_with_v_prefix(self) -> None:
        self.assertEqual(parse_version("v1.0.0"), (1, 0, 0))

    def test_parse_without_prefix(self) -> None:
        self.assertEqual(parse_version("2.3.4"), (2, 3, 4))

    def test_is_newer(self) -> None:
        self.assertTrue(is_newer("v1.1.0", "v1.0.0"))
        self.assertFalse(is_newer("v1.0.0", "v1.0.0"))
        self.assertFalse(is_newer("v1.0.0", "v1.1.0"))


class ReleaseUpdateStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_release_cache()

    def tearDown(self) -> None:
        clear_release_cache()

    def test_remote_newer_release(self) -> None:
        payload = json.dumps(
            {
                "latest_version": "v9.9.9",
                "update_url": "https://example.com/release",
                "distribution": "source",
                "upgrade_instructions": "git pull",
            }
        ).encode("utf-8")

        class FakeResponse:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args: typing.Any):
                return False

        with patch("core.version_info._urlopen", return_value=FakeResponse()):
            status = release_update_status(force_refresh=True)

        self.assertFalse(status["is_current"])
        self.assertEqual(status["latest"], "v9.9.9")
        self.assertEqual(status["update_link"], "https://example.com/release")
        self.assertTrue(status["is_online"])
        self.assertEqual(status["upgrade_instructions"], "git pull")

    def test_offline_bundled_current(self) -> None:
        with patch("core.version_info._urlopen", side_effect=OSError("offline")):
            status = release_update_status(force_refresh=True)

        self.assertTrue(status["is_current"])
        self.assertFalse(status["is_online"])
        self.assertEqual(status["latest"], "v1.1.0")

    def test_download_manager_delegates(self) -> None:
        manager = DownloadManager()
        # Same offline stub as the sibling tests; without it this reached the
        # real release endpoint.
        with patch("core.version_info._urlopen", side_effect=OSError("offline")):
            status = manager.update_status()
        self.assertEqual(status["version"], "v1.1.0")
        self.assertIn("upstream_base", status)
        self.assertIn("is_current", status)


class LoadReleaseMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_release_cache()

    def tearDown(self) -> None:
        clear_release_cache()

    def test_load_returns_dict(self) -> None:
        with patch("core.version_info._urlopen", side_effect=OSError("offline")):
            data, online = load_release_metadata(force_refresh=True)
        self.assertIsInstance(data, dict)
        self.assertFalse(online)


if __name__ == "__main__":
    unittest.main()
