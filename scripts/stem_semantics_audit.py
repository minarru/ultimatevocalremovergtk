#!/usr/bin/env python3
"""Audit is_karaoke/is_bv confidence and resolved stem buckets across the
mvsepless catalogue. For human review, not a pass/fail gate -- see
docs/superpowers/specs/2026-08-09-stem-export-semantics-design.md.

Usage:
    python scripts/stem_semantics_audit.py                    # print a table
    python scripts/stem_semantics_audit.py --guessed-only      # only the risk surface
    python scripts/stem_semantics_audit.py --json /tmp/out.json
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


def _entry_for_target(target: Any, catalogue_entry: dict) -> StemSemanticsEntry:
    from core.model_data import load_mdx_c_config
    from core.model_stem_semantics import confident_stem_bucket, resolve_karaoke_confidence
    from scripts.model_probe import _cache_dir, _fetch_config

    try:
        config_path = _fetch_config(target.config_url, _cache_dir())
        config = load_mdx_c_config(config_path)
    except Exception as exc:  # noqa: BLE001 - one bad entry must not abort the audit
        return StemSemanticsEntry(entry_id=target.entry_id, label=target.label, error=str(exc))

    training = config.get("training") or {}
    stems = [str(s) for s in (training.get("instruments") or [])]
    is_bv = bool(catalogue_entry.get("is_bv_model"))
    is_karaoke, is_curated = resolve_karaoke_confidence(
        model_data=catalogue_entry,
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
    )


def _iter_entries(*, guessed_only: bool = False) -> Iterator[StemSemanticsEntry]:
    from core.mvsepless_catalog import load_mvsepless_models
    from scripts.model_probe import iter_catalogue_targets

    catalogue = load_mvsepless_models() or {}
    for target in iter_catalogue_targets(catalogue, unsupported_only=False):
        entry = catalogue.get(target.entry_id) or {}
        result = _entry_for_target(target, entry)
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
            f"bv={e.is_bv!s:5s} stems={e.stems} buckets={e.buckets}"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument(
        "--guessed-only",
        action="store_true",
        help="Only show entries whose is_karaoke came from a name guess, not curated metadata.",
    )
    args = parser.parse_args(argv)

    entries = list(_iter_entries(guessed_only=args.guessed_only))
    entries.sort(key=lambda e: e.is_karaoke_curated)  # guessed (False) sorts first

    print(render_table(entries))
    if args.json_path:
        with open(args.json_path, "w") as f:
            json.dump([asdict(e) for e in entries], f, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
