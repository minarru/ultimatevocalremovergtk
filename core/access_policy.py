"""Process-wide network and metadata-write access policy."""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class AccessPolicy:
    allow_network: bool = True
    allow_metadata_writes: bool = True


_CURRENT = contextvars.ContextVar(
    "uvr_access_policy",
    default=AccessPolicy(allow_network=True, allow_metadata_writes=True),
)


def current_access_policy() -> AccessPolicy:
    return _CURRENT.get()


@contextlib.contextmanager
def access_policy(
    *, allow_network: bool, allow_metadata_writes: bool
) -> Iterator[None]:
    """Temporarily set the process-wide access policy for this context."""
    token = _CURRENT.set(
        AccessPolicy(
            allow_network=allow_network,
            allow_metadata_writes=allow_metadata_writes,
        )
    )
    try:
        yield
    finally:
        _CURRENT.reset(token)
