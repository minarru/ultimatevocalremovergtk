#!/usr/bin/env python3
"""Audit is_karaoke/is_bv confidence and resolved stem buckets across the
mvsepless catalogue. For human review, not a pass/fail gate -- see
docs/superpowers/specs/2026-08-09-stem-export-semantics-design.md.

Curated is_karaoke/is_bv_model metadata lives in a table keyed by the
checkpoint's MD5 hash (models/*/model_data/model_data.json), not in the
mvsepless catalogue itself. To tell a curated model apart from a guessed
one without downloading full checkpoints, this script range-fetches just
the last ~10MB of each remote checkpoint -- the same span
core.mdx_c_registry.compute_checkpoint_hash hashes for a local file -- and
looks that hash up in the curated table. This costs a real HTTP range
request per catalogue entry.

Successful hashes are remembered under CACHE_DIR, so a repeat audit costs
nothing; failures are never cached, so a bad network day does not poison
later reports.

Usage:
    python scripts/stem_semantics_audit.py                    # print a table
    python scripts/stem_semantics_audit.py --guessed-only      # only the risk surface
    python scripts/stem_semantics_audit.py --only karaoke      # targeted review
    python scripts/stem_semantics_audit.py --limit 10          # first N entries
    python scripts/stem_semantics_audit.py --json /tmp/out.json
    python scripts/stem_semantics_audit.py --quiet             # suppress progress
    python scripts/stem_semantics_audit.py --no-cache          # re-fetch every hash

Progress and the closing summary are written to stderr so stdout remains
suitable for redirection. Ctrl-C exits with status 130 without replacing the
requested JSON report, keeping any hashes already paid for.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The same tail span core.mdx_c_registry.compute_checkpoint_hash hashes for
# a local checkpoint file.
_HASH_TAIL_BYTES = 10000 * 1024


@dataclass(frozen=True)
class HashLookup:
    """Outcome of a remote checkpoint fingerprint attempt.

    ``status`` is about the *fetch*, not the match: ``ok`` (digest obtained),
    ``no_url`` (nothing to fetch) or ``fetch_failed`` (unreachable, range
    request refused, timeout...). Keeping these apart is what stops an entry
    that was never checked from being reported as a name-based guess.
    """

    digest: str = ""
    status: str = "no_url"
    error: str = ""


@dataclass(frozen=True)
class CatalogueEvidenceCounts:
    """Provenanced vocabulary measurements; never semantic declarations."""

    literal_names: int
    normalized_names: int
    primary_names: int
    community_tokens: tuple[str, ...]


_COMPLEMENT_ONLY_NAMES = frozenset({"drum-bass", "no bass", "no drums", "no other"})


def _community_stem_tokens(stems_text: str) -> tuple[str, ...]:
    """Parse only literal output labels from the community evidence column."""
    tokens = []
    for raw in stems_text.split(","):
        token = raw.replace("*", "").strip()
        token = token.split("(", 1)[0].strip()
        if token and token.casefold() != "unknown":
            tokens.append(token)
    return tuple(tokens)


def catalogue_evidence_counts(entries: Any, community_by_file: Dict[str, Any]) -> CatalogueEvidenceCounts:
    """Count the approved evidence universe without changing runtime semantics."""
    current_files = {str(entry.weight_file).casefold() for entry in entries}
    literals = set(_COMPLEMENT_ONLY_NAMES)
    primary = set()
    community_tokens = set()
    for entry in entries:
        literals.update(str(stem) for stem in entry.instruments if str(stem))
        if entry.primary_stem:
            value = str(entry.primary_stem)
            literals.add(value)
            primary.add(value.casefold())
        if entry.target_instrument:
            literals.add(str(entry.target_instrument))
    for filename, ref in community_by_file.items():
        if filename.casefold() not in current_files:
            continue
        for token in _community_stem_tokens(str(ref.stems_text)):
            literals.add(token)
            community_tokens.add(token)
    return CatalogueEvidenceCounts(
        len(literals),
        len({value.casefold() for value in literals}),
        len(primary),
        tuple(sorted(community_tokens, key=str.casefold)),
    )


class HashCache:
    """Checkpoint tail hashes, remembered between runs.

    Each entry costs a ~10MB range request, so a repeat audit that re-fetched
    everything is the difference between a usable command and one nobody runs.
    Checkpoint tails are immutable once published, so successes are kept
    indefinitely; failures are not cached at all, or one bad network day would
    poison every later report.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._records: Dict[str, dict] = {}
        self._dirty = False
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict):
                self._records = {
                    key: value for key, value in payload.items() if isinstance(value, dict)
                }
        except (OSError, ValueError):
            # A corrupt or absent cache is a cold cache, not a failure.
            self._records = {}

    def get(self, url: str) -> Optional[HashLookup]:
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
            pass  # an unwritable cache must not fail the audit


def default_hash_cache_path() -> str:
    from scripts.model_tool_support import cache_dir

    return os.path.join(cache_dir(), "checkpoint_tail_hashes.json")


@dataclass
class StemSemanticsEntry:
    entry_id: str
    label: str
    stems: List[str] = field(default_factory=list)
    is_karaoke: bool = False
    is_karaoke_curated: bool = False
    is_bv: bool = False
    buckets: List[str] = field(default_factory=list)
    error: str = ""
    #: matched | unmatched | no_url | fetch_failed -- see :class:`HashLookup`.
    hash_status: str = ""
    hash_error: str = ""


def _remote_checkpoint_hash(
    checkpoint_url: str, *, cache: Optional[HashCache] = None
) -> HashLookup:
    """UVR-style MD5 fingerprint of a remote checkpoint, range-fetched.

    Mirrors core.mdx_c_registry.compute_checkpoint_hash's local-file logic
    (hash the last _HASH_TAIL_BYTES, or the whole file when smaller) but
    reads over HTTP so auditing the catalogue doesn't require downloading
    full checkpoints. A failure is reported rather than raised -- one
    unreachable checkpoint must not abort the audit -- but it is reported
    *as a failure*, not as an absent fingerprint.
    """
    if not checkpoint_url:
        return HashLookup(status="no_url")
    if cache is not None:
        cached = cache.get(checkpoint_url)
        if cached is not None:
            return cached
    from scripts.model_tool_support import checkpoint_tail_hash

    try:
        digest = checkpoint_tail_hash(checkpoint_url)
    except Exception as exc:  # noqa: BLE001 - one unreachable checkpoint must not abort the audit
        return HashLookup(status="fetch_failed", error=f"{type(exc).__name__}: {exc}")
    lookup = HashLookup(digest=digest, status="ok")
    if cache is not None:
        cache.put(checkpoint_url, lookup)
    return lookup


def _curated_hash_table() -> Dict[str, dict]:
    """Merge the VR and MDX curated hash-metadata tables, keyed by MD5 hash."""
    from core import paths
    from core.model_data import load_model_hash_data

    table: Dict[str, dict] = {}
    for path in (paths.VR_HASH_JSON, paths.MDX_HASH_JSON):
        try:
            table.update(load_model_hash_data(path))
        except (FileNotFoundError, ValueError, OSError):
            pass
    return table


def _entry_for_target(
    target: Any, curated_table: Dict[str, dict], *, cache: Optional[HashCache] = None
) -> StemSemanticsEntry:
    from core.model_data import load_mdx_c_config
    from core.model_stem_semantics import confident_stem_bucket, resolve_karaoke_confidence
    from scripts.model_tool_support import cache_dir, fetch_config

    try:
        config_path = fetch_config(target.config_url, cache_dir())
        config = load_mdx_c_config(config_path)
    except Exception as exc:  # noqa: BLE001 - one bad entry must not abort the audit
        return StemSemanticsEntry(entry_id=target.entry_id, label=target.label, error=str(exc))

    training = config.get("training") or {}
    stems = [str(s) for s in (training.get("instruments") or [])]
    lookup = _remote_checkpoint_hash(target.checkpoint_url, cache=cache)
    curated_data = curated_table.get(lookup.digest) if lookup.status == "ok" else None
    if lookup.status != "ok":
        hash_status = lookup.status
    else:
        hash_status = "matched" if curated_data else "unmatched"
    is_bv = bool(
        (curated_data or {}).get("is_bv_model")
        or getattr(target, "is_bv_model", False)
    )
    is_karaoke, is_curated = resolve_karaoke_confidence(
        model_data=curated_data,
        model_name=target.label,
        config_yaml=target.config_url,
        weight_basename=target.checkpoint_url,
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
    return StemSemanticsEntry(
        entry_id=target.entry_id,
        label=target.label,
        stems=stems,
        is_karaoke=is_karaoke,
        is_karaoke_curated=is_curated,
        is_bv=is_bv,
        buckets=buckets,
        hash_status=hash_status,
        hash_error=lookup.error,
    )


def select_targets(
    targets: List[Any], *, only: str = "", limit: Optional[int] = None
) -> List[Any]:
    """Narrow the catalogue for a targeted review.

    ``only`` matches a substring of either the entry id or the label, so a
    reviewer can name a model the way it is written in either place.
    """
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


def _iter_entries(
    *,
    guessed_only: bool = False,
    show_progress: bool = False,
    only: str = "",
    limit: Optional[int] = None,
    cache: Optional[HashCache] = None,
) -> Iterator[StemSemanticsEntry]:
    from scripts.model_tool_support import iter_catalogue_targets

    curated_table = _curated_hash_table()
    targets = select_targets(
        list(iter_catalogue_targets(unsupported_only=False)), only=only, limit=limit
    )
    total = len(targets)
    for index, target in enumerate(targets, 1):
        if show_progress:
            print(
                f"[{index:>{len(str(total))}}/{total}] {target.entry_id}: {target.label}",
                file=sys.stderr,
                flush=True,
            )
        result = _entry_for_target(target, curated_table, cache=cache)
        if guessed_only and result.is_karaoke_curated:
            continue
        yield result


def render_table(entries: List[StemSemanticsEntry]) -> str:
    lines = []
    for e in entries:
        if e.error:
            lines.append(f"{e.entry_id:40s} ERROR={e.error}")
            continue
        confidence = "curated" if e.is_karaoke_curated else "guessed"
        lines.append(
            f"{e.entry_id:40s} karaoke={e.is_karaoke!s:5s} ({confidence:7s}) "
            f"hash={e.hash_status:12s} bv={e.is_bv!s:5s} "
            f"stems={e.stems} buckets={e.buckets}"
        )
    return "\n".join(lines)


def render_summary(entries: List[StemSemanticsEntry]) -> str:
    """Tally confidence and evidence, so the table's shape is readable at a glance."""
    from collections import Counter

    statuses = Counter(e.hash_status for e in entries if not e.error)
    curated = sum(1 for e in entries if not e.error and e.is_karaoke_curated)
    guessed = sum(1 for e in entries if not e.error and not e.is_karaoke_curated)
    config_errors = sum(1 for e in entries if e.error)

    parts = [
        f"{len(entries)} entries",
        f"{curated} curated",
        f"{guessed} guessed",
    ]
    for status in ("matched", "unmatched", "no_url", "fetch_failed"):
        if statuses.get(status):
            parts.append(f"{statuses[status]} {status}")
    if config_errors:
        parts.append(f"{config_errors} config error")
    return "  ".join(parts)


def _write_json(path: str, entries: List[StemSemanticsEntry]) -> None:
    """Atomically replace ``path`` so interruption cannot leave partial JSON."""
    tmp_path = f"{path}.part"
    try:
        with open(tmp_path, "w") as f:
            json.dump([asdict(e) for e in entries], f, indent=2)
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        default=None,
        metavar="PATH",
        help=(
            "Write the full per-entry report JSON here. The human table is "
            "still printed to stdout."
        ),
    )
    parser.add_argument(
        "--guessed-only",
        action="store_true",
        help=(
            "Only entries whose is_karaoke came from a filename guess, not "
            "from curated hash-table metadata in models/*/model_data/. That "
            "is the review surface: curated rows are already trusted."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print per-model progress to stderr.",
    )
    parser.add_argument(
        "--only",
        default="",
        metavar="SUBSTR",
        help="Audit only entries whose id or label contains this substring.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Audit at most this many entries (after --only).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help=(
            "Ignore remembered successful checkpoint-tail hashes and re-fetch "
            "every one. Failures are never cached, so a bad network day cannot "
            "poison later reports even without this flag."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check the current catalogue against local reviewed manifest declarations.",
    )
    return parser


def strict_catalogue_check() -> tuple[bool, str]:
    """Audit exact evidence through the runtime resolver, never guessed intent."""
    from catalogue import collect, render

    from core.model_stem_manifest import (
        BUNDLED_MANIFEST_PATH,
        load_stem_manifest,
        resolve_model_stem_semantics,
    )
    from core.stem_roles import StemProcessingContext, StemReviewStatus

    policy = collect.FetchPolicy(allow_network=False, allow_cache_writes=False,
                                 allow_metadata_writes=False)
    context = collect._build_catalogue_context(policy=policy)
    _snapshot, entries = collect.collect_entries(context, policy=policy)
    registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
    counts = catalogue_evidence_counts(entries, context.community_by_file)
    missing = []
    mismatches = []
    for entry in entries:
        model_id = render._canonical_model_id(entry)
        if model_id in registry.waivers:
            continue
        resolved = resolve_model_stem_semantics(
            model_id, native_stems=entry.instruments, backend_primary=entry.primary_stem,
            backend_target=entry.target_instrument, context=StemProcessingContext.FULL_MIX,
            registry=registry,
        )
        if resolved.status is not StemReviewStatus.REVIEWED:
            mismatches.append(model_id)
        if model_id not in registry.models:
            missing.append(model_id)
    summary = (
        f"models={len(entries)} literal_names={counts.literal_names} "
        f"normalized_names={counts.normalized_names} primary_names={counts.primary_names}\n"
        f"complement_only={len(_COMPLEMENT_ONLY_NAMES)} unreviewed={len(missing)} "
        f"signature_mismatches={len(mismatches)} collisions=0"
    )
    return not missing and not mismatches, summary


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.check:
        ok, summary = strict_catalogue_check()
        print(summary)
        return 0 if ok else 1

    cache = None if args.no_cache else HashCache(default_hash_cache_path())
    try:
        entries = list(
            _iter_entries(
                guessed_only=args.guessed_only,
                show_progress=not args.quiet,
                only=args.only,
                limit=args.limit,
                cache=cache,
            )
        )
    except KeyboardInterrupt:
        # Keep whatever hashes were already paid for before the interrupt.
        if cache is not None:
            cache.save()
        print("\nAudit interrupted; no report was written.", file=sys.stderr)
        return 130
    if cache is not None:
        cache.save()
    entries.sort(key=lambda e: e.is_karaoke_curated)  # guessed (False) sorts first

    print(render_table(entries))
    print(render_summary(entries), file=sys.stderr)
    if args.json_path:
        _write_json(args.json_path, entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
