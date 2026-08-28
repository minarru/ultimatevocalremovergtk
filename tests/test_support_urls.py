"""Tests for fork support URLs."""

import unittest
import urllib.parse

from __version__ import VERSION
from bundled.constants import ISSUE_LINK
from core.support_urls import fork_issue_url


class ForkIssueUrlTests(unittest.TestCase):
    def test_points_at_github(self) -> None:
        url = fork_issue_url(log_text="sample error")
        self.assertTrue(
            url.startswith("https://github.com/minarru/ultimatevocalremovergtk/issues/new?")
        )

    def test_body_contains_version_and_log(self) -> None:
        url = fork_issue_url(log_text="Traceback Error\nRuntimeError: boom")
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        body = params["body"][0]
        self.assertIn(VERSION, body)
        self.assertIn("v5.6.0", body)
        self.assertIn("RuntimeError: boom", body)

    def test_truncates_very_long_logs(self) -> None:
        url = fork_issue_url(log_text="x" * 10000)
        self.assertLessEqual(len(url), 6000)
        parsed = urllib.parse.urlparse(url)
        body = urllib.parse.parse_qs(parsed.query)["body"][0]
        self.assertIn("truncated", body)

    def test_issue_link_constant(self) -> None:
        self.assertIn("github.com/minarru/ultimatevocalremovergtk", ISSUE_LINK)
        self.assertNotIn("Anjok07", ISSUE_LINK)
        self.assertNotIn("codeberg.org", ISSUE_LINK)


if __name__ == "__main__":
    unittest.main()
