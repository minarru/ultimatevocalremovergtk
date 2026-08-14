"""Catalogue-network guard for read-only CLI resolution.

``core.model_display._merged_for_display()`` fetches the politrees and
mvsepless catalogues over the network (30s timeout each). Commands that only
need display labels default to offline so they stay fast and hermetic; both
disable flags are read at call time, so setting them here takes effect.

``--online`` means "do not force these flags on". It does **not** clear
``UVR_DISABLE_POLITREES`` / ``UVR_DISABLE_MVSEPLESS`` if the caller already
set them.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator

_OFFLINE_ENV = ("UVR_DISABLE_POLITREES", "UVR_DISABLE_MVSEPLESS")


@contextlib.contextmanager
def catalogue_offline(enabled: bool = True) -> Iterator[None]:
    """Disable both catalogue network sources for the duration of the block."""
    if not enabled:
        yield
        return
    previous = {name: os.environ.get(name) for name in _OFFLINE_ENV}
    for name in _OFFLINE_ENV:
        os.environ[name] = "1"
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
