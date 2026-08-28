"""Self-tests for the opt-in private GTK unittest guard."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests import private_gtk

_REPO = Path(__file__).resolve().parents[1]


class _PrivateDisplay:
    def get_name(self) -> str:
        return "codex-gtk"


_PrivateDisplay.__name__ = "GdkWaylandDisplay"


class PrivateGtkGuardTests(unittest.TestCase):
    def test_guard_absent_preserves_display_related_skip_behavior(self) -> None:
        script = """
import os
import unittest
from tests.private_gtk import require_private_gtk

os.environ.pop("UVR_REQUIRE_PRIVATE_GTK", None)
require_private_gtk()

class DisplayCase(unittest.TestCase):
    def runTest(self):
        raise unittest.SkipTest("GTK display unavailable")

result = unittest.TestResult()
DisplayCase().run(result)
assert result.wasSuccessful()
assert len(result.skipped) == 1
assert not result.failures
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=_REPO,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_required_guard_fails_display_skips_but_keeps_unrelated_skips(self) -> None:
        import gi

        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk

        with (
            mock.patch.dict(os.environ, {"UVR_REQUIRE_PRIVATE_GTK": "1"}),
            mock.patch.object(Gdk.Display, "get_default", return_value=_PrivateDisplay()),
        ):
            private_gtk.require_private_gtk()

        class DynamicDisplaySkip(unittest.TestCase):
            def runTest(self) -> None:
                raise unittest.SkipTest("Wayland display unavailable")

        @unittest.skip("GTK widget construction needs a display")
        class DecoratedDisplaySkip(unittest.TestCase):
            def test_widget(self) -> None:
                self.fail("decorated skip should not execute")

        @unittest.skip("optional slow integration")
        class UnrelatedSkip(unittest.TestCase):
            def test_optional(self) -> None:
                self.fail("unrelated skip should remain skipped")

        with mock.patch.dict(os.environ, {"UVR_REQUIRE_PRIVATE_GTK": "1"}):
            dynamic_result = unittest.TestResult()
            DynamicDisplaySkip().run(dynamic_result)
            self.assertEqual(len(dynamic_result.failures), 1)
            self.assertEqual(dynamic_result.skipped, [])
            self.assertIn(
                "UVR_REQUIRE_PRIVATE_GTK=1 forbids display-related SkipTest",
                dynamic_result.failures[0][1],
            )

            display_result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(DecoratedDisplaySkip)
            )
            self.assertEqual(len(display_result.failures), 1)
            self.assertEqual(display_result.skipped, [])

            unrelated_result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(UnrelatedSkip)
            )
            self.assertTrue(unrelated_result.wasSuccessful())
            self.assertEqual(len(unrelated_result.skipped), 1)
            self.assertEqual(unrelated_result.failures, [])

        with mock.patch.dict(os.environ):
            os.environ.pop("UVR_REQUIRE_PRIVATE_GTK", None)
            restored_result = unittest.TestResult()
            DynamicDisplaySkip().run(restored_result)
            self.assertTrue(restored_result.wasSuccessful())
            self.assertEqual(len(restored_result.skipped), 1)
            self.assertEqual(restored_result.failures, [])


if __name__ == "__main__":
    unittest.main()
