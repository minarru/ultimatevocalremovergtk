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
    # ``None`` preserves the legacy contract: callers that only deny metadata
    # writes also deny cache writes. Callers with distinct requirements can
    # now permit one capability without silently permitting the other.
    allow_cache_writes: bool | None = None

    def __post_init__(self) -> None:
        if self.allow_cache_writes is None:
            object.__setattr__(
                self, "allow_cache_writes", self.allow_metadata_writes
            )


_DEFAULT_POLICY = AccessPolicy(allow_network=True, allow_metadata_writes=True)

_CURRENT = contextvars.ContextVar(
    "uvr_access_policy",
    default=_DEFAULT_POLICY,
)


def current_access_policy() -> AccessPolicy:
    return _CURRENT.get()


@contextlib.contextmanager
def access_policy(
    *,
    allow_network: bool,
    allow_metadata_writes: bool,
    allow_cache_writes: bool | None = None,
) -> Iterator[None]:
    """Temporarily set the process-wide access policy for this context."""
    token = _CURRENT.set(
        AccessPolicy(
            allow_network=allow_network,
            allow_metadata_writes=allow_metadata_writes,
            allow_cache_writes=allow_cache_writes,
        )
    )
    try:
        yield
    finally:
        _CURRENT.reset(token)
