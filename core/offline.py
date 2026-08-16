"""Deprecated compatibility context for explicitly cached catalogue callers.

Catalogue access policy is now passed to the catalogue services directly.
This context intentionally performs no process-global environment mutation.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator


@contextlib.contextmanager
def catalogue_offline(enabled: bool = True) -> Iterator[None]:
    del enabled
    yield
