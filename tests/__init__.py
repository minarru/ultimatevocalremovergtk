"""Test package with private cache and no-live-network guards."""

import os
import tempfile

# ``core.paths`` freezes cache paths at import time. Establish a process-lifetime
# scratch root before importing any application module so catalogue fixtures can
# never replace the user's real cached sources.
_TEST_CACHE = tempfile.TemporaryDirectory(prefix="uvr-tests-cache-")
os.environ["UVR_CACHE_DIR"] = _TEST_CACHE.name

from . import net_guard  # noqa: E402 - cache root must precede application imports

net_guard.install()
