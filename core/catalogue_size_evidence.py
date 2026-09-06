"""Checkpoint size/identity acquisition and per-URL-set warmup ownership."""

from __future__ import annotations

import threading
import time
from typing import Callable

from .debug_log import debug


class CatalogueSizeEvidenceService:
    def __init__(
        self,
        *,
        prefetch_sizes: Callable[[list[str]], dict[str, int]],
        prefetch_identity: Callable[[list[str]], dict[str, int]],
        apply_identities: Callable[[list[str]], None],
    ) -> None:
        self._prefetch_sizes = prefetch_sizes
        self._prefetch_identity = prefetch_identity
        self._apply_identities = apply_identities
        self._lock = threading.Lock()
        self.done_for: frozenset[str] | None = None

    def warm(self, urls: list[str]) -> dict[str, int]:
        """Acquire evidence once per URL set, retrying capped identity passes."""
        signature = frozenset(urls)
        if self.done_for == signature:
            debug("download", "size_cache_warmup skip already warm")
            return {"total": len(urls), "fresh": len(urls), "fetched": 0, "failed": 0}

        if not self._lock.acquire(blocking=False):
            debug("download", "size_cache_warmup skip already running")
            return {"total": 0, "fresh": 0, "fetched": 0, "failed": 0}

        from .debug_log import debug_elapsed

        try:
            debug("download", f"size_cache_warmup start urls={len(urls)}")
            started = time.perf_counter()
            stats = self._prefetch_sizes(urls)
            identity = self._prefetch_identity(urls)
            self._apply_identities(urls)
            # Only mark the URL set warm once the identity pass has nothing
            # left; it HEADs at most _IDENTITY_HEAD_CAP per call, and latching
            # here would strand the remainder for the rest of the session.
            # Re-running is cheap — the size pass skips every fresh entry.
            if identity.get("capped"):
                self.done_for = None
            else:
                self.done_for = signature
            debug_elapsed(
                "download",
                "size_cache_warmup done "
                f"total={stats['total']} fresh={stats['fresh']} "
                f"fetched={stats['fetched']} failed={stats['failed']} "
                f"identity_fetched={identity.get('fetched', 0)}",
                started,
            )
            return stats
        finally:
            self._lock.release()
