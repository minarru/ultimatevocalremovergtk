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

Usage:
    python scripts/stem_semantics_audit.py                    # print a table
    python scripts/stem_semantics_audit.py --guessed-only      # only the risk surface
    python scripts/stem_semantics_audit.py --json /tmp/out.json
    python scripts/stem_semantics_audit.py --quiet             # suppress progress

Progress is written to stderr so stdout remains suitable for redirection.
Ctrl-C exits with status 130 without replacing the requested JSON report.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
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


def _remote_checkpoint_hash(checkpoint_url: str) -> HashLookup:
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
    from scripts.model_tool_support import checkpoint_tail_hash

    try:
        digest = checkpoint_tail_hash(checkpoint_url)
    except Exception as exc:  # noqa: BLE001 - one unreachable checkpoint must not abort the audit
        return HashLookup(status="fetch_failed", error=f"{type(exc).__name__}: {exc}")
    return HashLookup(digest=digest, status="ok")


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
    target: Any, curated_table: Dict[str, dict]
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
    lookup = _remote_checkpoint_hash(target.checkpoint_url)
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


def _iter_entries(
    *, guessed_only: bool = False, show_progress: bool = False
) -> Iterator[StemSemanticsEntry]:
    from scripts.model_tool_support import iter_catalogue_targets

    curated_table = _curated_hash_table()
    targets = list(iter_catalogue_targets(unsupported_only=False))
    total = len(targets)
    for index, target in enumerate(targets, 1):
        if show_progress:
            print(
                f"[{index:>{len(str(total))}}/{total}] {target.entry_id}: {target.label}",
                file=sys.stderr,
                flush=True,
            )
        result = _entry_for_target(target, curated_table)
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


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument(
        "--guessed-only",
        action="store_true",
        help="Only show entries whose is_karaoke came from a name guess, not curated metadata.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print per-model progress to stderr.",
    )
    args = parser.parse_args(argv)

    try:
        entries = list(
            _iter_entries(
                guessed_only=args.guessed_only,
                show_progress=not args.quiet,
            )
        )
    except KeyboardInterrupt:
        print("\nAudit interrupted; no report was written.", file=sys.stderr)
        return 130
    entries.sort(key=lambda e: e.is_karaoke_curated)  # guessed (False) sorts first

    print(render_table(entries))
    if args.json_path:
        _write_json(args.json_path, entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
