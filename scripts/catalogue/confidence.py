"""Optional remote stem-confidence review, separate from strict publication.

This review traverses remote mvsepless entries and range-reads checkpoints to
establish whether karaoke metadata is curated or guessed. It does not collect
or publish a second catalogue snapshot.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import (
    Any,
    Iterator,
    Mapping,
    Sequence,
)

from catalogue.cache import FetchPolicy
from core.access_policy import AccessPolicy
from scripts.model_tool_support import CatalogueTarget


@dataclass(frozen=True, slots=True)
class HashLookup:
    """Outcome of one remote checkpoint-tail fingerprint attempt."""

    digest: str = ""
    status: str = "no_url"
    error: str = ""


class HashCache:
    """Persistent successful checkpoint hashes keyed by their source URL."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._records: dict[str, dict[str, Any]] = {}
        self._dirty = False
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                self._records = {
                    str(key): value for key, value in payload.items() if isinstance(value, dict)
                }
        except (OSError, ValueError):
            pass

    def get(self, url: str) -> HashLookup | None:
        record = self._records.get(url)
        if not record or record.get("status") != "ok" or not record.get("digest"):
            return None
        return HashLookup(digest=str(record["digest"]), status="ok")

    def put(self, url: str, lookup: HashLookup) -> None:
        if lookup.status != "ok" or not lookup.digest:
            return
        self._records[url] = {
            "digest": lookup.digest,
            "status": "ok",
            "fetched_at": time.time(),
        }
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        from core.json_store import write_json_atomic

        try:
            write_json_atomic(self.path, self._records)
            self._dirty = False
        except OSError:
            pass


def default_hash_cache_path() -> str:
    from scripts.model_tool_support import cache_dir

    return os.path.join(cache_dir(), "checkpoint_tail_hashes.json")


@dataclass(slots=True)
class StemConfidenceEntry:
    """One human-review row from the optional remote confidence audit."""

    entry_id: str
    label: str
    stems: list[str] = field(default_factory=list)
    is_karaoke: bool = False
    is_karaoke_curated: bool = False
    is_bv: bool = False
    buckets: list[str] = field(default_factory=list)
    error: str = ""
    hash_status: str = ""
    hash_error: str = ""


def _confidence_access_policy(policy: FetchPolicy) -> AccessPolicy:
    from core.access_policy import AccessPolicy

    return AccessPolicy(
        allow_network=bool(policy.allow_network),
        allow_metadata_writes=False,
        allow_cache_writes=bool(policy.allow_cache_writes),
    )


def _confidence_targets(policy: FetchPolicy) -> list[CatalogueTarget]:
    """Load mvsepless targets with the generator's exact network policy."""
    from core.catalogue_coordinator import CatalogueCoordinator
    from core.catalogue_types import RefreshMode, SourceId
    from scripts.model_tool_support import iter_catalogue_targets

    coordinator = CatalogueCoordinator()
    try:
        source = coordinator.source(SourceId.MVSEPLESS)
        access = _confidence_access_policy(policy)
        # Audits need a complete target list now, unlike the UI's
        # stale-while-revalidate path. Read disk cache first; only a cold
        # online miss blocks for a fetch. Explicit --refresh remains FORCE.
        source.load(mode=RefreshMode.OFFLINE, policy=access)
        if policy.allow_network and (policy.refresh or source.state.content is None):
            source.load(mode=RefreshMode.FORCE, policy=access)
        content = source.state.content
        payload = dict(content.payload) if content is not None else {}
        return list(iter_catalogue_targets(payload, unsupported_only=False))
    finally:
        coordinator.close()


def _remote_checkpoint_hash(
    checkpoint_url: str,
    *,
    cache: HashCache | None = None,
    allow_network: bool = True,
    refresh: bool = False,
) -> HashLookup:
    if not checkpoint_url:
        return HashLookup(status="no_url")
    if cache is not None and not refresh:
        cached = cache.get(checkpoint_url)
        if cached is not None:
            return cached
    if not allow_network:
        return HashLookup(status="offline")
    from scripts.model_tool_support import checkpoint_tail_hash

    try:
        digest = checkpoint_tail_hash(checkpoint_url)
    except Exception as exc:  # one unreachable checkpoint is a finding, not a crash
        return HashLookup(status="fetch_failed", error=f"{type(exc).__name__}: {exc}")
    result = HashLookup(digest=digest, status="ok")
    if cache is not None:
        cache.put(checkpoint_url, result)
    return result


def _curated_hash_table() -> dict[str, dict[str, Any]]:
    from core import paths
    from core.model_data import load_model_hash_data

    table: dict[str, dict[str, Any]] = {}
    for path in (paths.VR_HASH_JSON, paths.MDX_HASH_JSON):
        try:
            table.update(load_model_hash_data(path))
        except (FileNotFoundError, ValueError, OSError):
            pass
    return table


def _confidence_config(target: CatalogueTarget, policy: FetchPolicy) -> dict[str, Any]:
    """Read a target config through the catalogue cache and access policy."""
    from catalogue import cache
    from core.model_data import load_mdx_c_config, load_mdx_c_config_data
    from scripts.model_tool_support import cache_dir, cache_name

    url = str(getattr(target, "config_url", ""))
    name = str(getattr(target, "config_name", "")) or "config.yaml"
    # Preserve the old standalone command's warm config cache while moving its
    # refresh-aware future fetches onto the catalogue cache policy.
    legacy_path = os.path.join(cache_dir(), cache_name(url, name))
    if not policy.refresh and os.path.isfile(legacy_path):
        return load_mdx_c_config(legacy_path)
    data, _path = cache.fetch_yaml_bytes(url, name, policy=policy)
    if data is None:
        mode = "offline" if not policy.allow_network else "cache/network"
        raise OSError(f"configuration unavailable from {mode}: {url or name}")
    return load_mdx_c_config_data(data)


def _confidence_entry_for_target(
    target: CatalogueTarget,
    curated_table: Mapping[str, dict[str, Any]],
    *,
    policy: FetchPolicy,
    cache: HashCache | None,
) -> StemConfidenceEntry:
    try:
        config = _confidence_config(target, policy)
    except Exception as exc:  # retain one-row-per-target review output
        return StemConfidenceEntry(
            entry_id=str(target.entry_id), label=str(target.label), error=str(exc)
        )

    training = config.get("training") or {}
    stems = [str(stem) for stem in (training.get("instruments") or [])]
    lookup = _remote_checkpoint_hash(
        str(getattr(target, "checkpoint_url", "")),
        cache=cache,
        allow_network=bool(policy.allow_network),
        refresh=bool(policy.refresh),
    )
    curated_data = curated_table.get(lookup.digest) if lookup.status == "ok" else None
    hash_status = (
        "matched"
        if lookup.status == "ok" and curated_data
        else "unmatched"
        if lookup.status == "ok"
        else lookup.status
    )
    from core.model_stem_semantics import confident_stem_bucket, resolve_karaoke_confidence

    is_bv = bool((curated_data or {}).get("is_bv_model") or getattr(target, "is_bv_model", False))
    is_karaoke, is_curated = resolve_karaoke_confidence(
        model_data=curated_data,
        model_name=str(target.label),
        config_yaml=str(getattr(target, "config_url", "")),
        weight_basename=str(getattr(target, "checkpoint_url", "")),
    )
    buckets = [
        confident_stem_bucket(
            stem,
            stem_count=len(stems) or 2,
            is_karaoke=is_karaoke,
            is_karaoke_curated=is_curated,
            is_bv=is_bv,
        )
        for stem in stems
    ]
    return StemConfidenceEntry(
        entry_id=str(target.entry_id),
        label=str(target.label),
        stems=stems,
        is_karaoke=is_karaoke,
        is_karaoke_curated=is_curated,
        is_bv=is_bv,
        buckets=buckets,
        hash_status=hash_status,
        hash_error=lookup.error,
    )


def select_confidence_targets(
    targets: Sequence[CatalogueTarget], *, only: str = "", limit: int | None = None
) -> list[CatalogueTarget]:
    picked = list(targets)
    if only:
        needle = only.casefold()
        picked = [
            target
            for target in picked
            if needle in str(getattr(target, "entry_id", "")).casefold()
            or needle in str(getattr(target, "label", "")).casefold()
        ]
    if limit is not None and limit >= 0:
        picked = picked[:limit]
    return picked


def iter_stem_confidence_entries(
    *,
    policy: FetchPolicy,
    guessed_only: bool = False,
    show_progress: bool = False,
    only: str = "",
    limit: int | None = None,
    cache: HashCache | None = None,
) -> Iterator[StemConfidenceEntry]:
    targets = select_confidence_targets(_confidence_targets(policy), only=only, limit=limit)
    curated_table = _curated_hash_table()
    total = len(targets)
    for index, target in enumerate(targets, 1):
        if show_progress:
            print(
                f"[{index:>{len(str(total))}}/{total}] {target.entry_id}: {target.label}",
                file=sys.stderr,
                flush=True,
            )
        entry = _confidence_entry_for_target(target, curated_table, policy=policy, cache=cache)
        if guessed_only and entry.is_karaoke_curated:
            continue
        yield entry


def render_stem_confidence_table(entries: Sequence[StemConfidenceEntry]) -> str:
    lines = []
    for entry in entries:
        if entry.error:
            lines.append(f"{entry.entry_id:40s} ERROR={entry.error}")
            continue
        confidence = "curated" if entry.is_karaoke_curated else "guessed"
        lines.append(
            f"{entry.entry_id:40s} karaoke={entry.is_karaoke!s:5s} ({confidence:7s}) "
            f"hash={entry.hash_status:12s} bv={entry.is_bv!s:5s} "
            f"stems={entry.stems} buckets={entry.buckets}"
        )
    return "\n".join(lines)


def render_stem_confidence_summary(entries: Sequence[StemConfidenceEntry]) -> str:
    from collections import Counter

    statuses = Counter(entry.hash_status for entry in entries if not entry.error)
    curated = sum(1 for entry in entries if not entry.error and entry.is_karaoke_curated)
    guessed = sum(1 for entry in entries if not entry.error and not entry.is_karaoke_curated)
    config_errors = sum(1 for entry in entries if entry.error)
    parts = [f"{len(entries)} entries", f"{curated} curated", f"{guessed} guessed"]
    for status in ("matched", "unmatched", "no_url", "offline", "fetch_failed"):
        if statuses.get(status):
            parts.append(f"{statuses[status]} {status}")
    if config_errors:
        parts.append(f"{config_errors} config error")
    return "  ".join(parts)


def write_stem_confidence_json(path: str, entries: Sequence[StemConfidenceEntry]) -> None:
    """Atomically replace a requested JSON report after a complete audit."""
    tmp_path = f"{path}.part"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump([asdict(entry) for entry in entries], handle, indent=2)
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def run_stem_confidence_audit(
    *,
    policy: FetchPolicy,
    guessed_only: bool = False,
    only: str = "",
    limit: int | None = None,
    json_path: str | None = None,
    quiet: bool = False,
    no_hash_cache: bool = False,
) -> int:
    """Run the optional remote review without touching publication artifacts."""
    cache = None if no_hash_cache else HashCache(default_hash_cache_path())
    try:
        entries = list(
            iter_stem_confidence_entries(
                policy=policy,
                guessed_only=guessed_only,
                show_progress=not quiet,
                only=only,
                limit=limit,
                cache=cache,
            )
        )
    except KeyboardInterrupt:
        if cache is not None:
            cache.save()
        print("\nStem-confidence audit interrupted; no report was written.", file=sys.stderr)
        return 130
    if cache is not None:
        cache.save()
    entries.sort(key=lambda entry: entry.is_karaoke_curated)
    print(render_stem_confidence_table(entries))
    print(render_stem_confidence_summary(entries), file=sys.stderr)
    if json_path:
        write_stem_confidence_json(json_path, entries)
    return 0
