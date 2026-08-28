"""Bootstrap and verify the test process' private cache before app imports.

``unittest discover -s tests`` imports test modules as top-level modules and
therefore does not import :mod:`tests` itself.  This file sorts first during
discovery and deliberately imports the package so its process-lifetime cache
guard is established before any application module can freeze ``CACHE_DIR``.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from tests import _TEST_CACHE  # noqa: F401 - importing installs suite guards


class TestCacheIsolationTests(unittest.TestCase):
    def test_suite_cache_is_private_and_not_the_user_cache(self) -> None:
        from core import paths
        from core.platform import default_user_cache_dir

        cache_dir = os.path.realpath(paths.CACHE_DIR)
        temp_root = os.path.realpath(tempfile.gettempdir())

        self.assertNotEqual(cache_dir, os.path.realpath(default_user_cache_dir()))
        self.assertEqual(os.path.commonpath((cache_dir, temp_root)), temp_root)
        self.assertTrue(os.path.basename(cache_dir).startswith("uvr-tests-cache-"))


if __name__ == "__main__":
    unittest.main()
