"""Preloading engines must leave unrelated Python warnings visible."""

import os
import subprocess
import sys
import textwrap
import unittest


class EngineWarningVisibilityTests(unittest.TestCase):
    def test_actual_preload_preserves_warning_filter_installed_before_import(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                textwrap.dedent('''
                import tests
                import warnings
                class SentinelWarning(UserWarning):
                    pass
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always", SentinelWarning)
                    from engines.separator_factory import preload_engine_modules
                    preload_engine_modules()
                    warnings.warn("task8-unrelated-warning", SentinelWarning)
                    assert any(isinstance(item.message, SentinelWarning) for item in caught), "engine preload hid unrelated warning"
            '''),
            ],
            env={**os.environ, "UVR_SKIP_SEPARATE_WARMUP": "1"},
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
