#!/usr/bin/env python3
"""Generate docs/models-catalogue.md from the Download Center catalogue snapshot.

Membership comes from ``CatalogueCoordinator`` (TRvlvr → Politrees → extras →
mvsepless, plus Apollo). This script audits stem metadata against catalogue
naming intent so mislabeled vocal vs instrumental models can be spotted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from catalogue import collect  # noqa: E402
from catalogue import render  # noqa: E402
from catalogue.collect import (  # noqa: E402
    DISPLAY_REFERENCE_TSV_PATH,
    FetchPolicy,
    OUTPUT_PATH,
    REFERENCE_TSV_PATH,
    _document_digest,
    _ir_path_for,
    _unsupported_count,
    build_ir,
)


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Generate docs/models-catalogue.md from the Download Center snapshot "
            "(upstream, Politrees, extras, mvsepless, plus Apollo)."
        ),
        epilog=(
            "Fetch behaviour:\n"
            "  Default uses cache TTL (24h) and stale-while-revalidate, so a warm\n"
            "  cache can republish yesterday's membership. --refresh FORCE-reloads\n"
            "  coordinator sources and yaml/models.txt supplements. --offline never\n"
            "  fetches and will serve a stale (or empty) cache rather than going\n"
            "  to the network. A cold cache without --refresh is a fraction of the\n"
            "  live catalogue; the publication guard refuses to replace a good\n"
            "  document with that (exit 2) unless you pass --allow-degraded.\n"
            "\n"
            "Exit status:\n"
            "  0  wrote, or --check found no drift, or --summary printed\n"
            "  1  --check found drift (canonical text changed; header dates ignored)\n"
            "  2  this run's data is too degraded to publish or to judge drift\n"
            "\n"
            "Examples:\n"
            "  python scripts/generate_models_catalogue.py\n"
            "  python scripts/generate_models_catalogue.py --refresh\n"
            "  python scripts/generate_models_catalogue.py --check\n"
            "  python scripts/generate_models_catalogue.py --write-display-reference\n"
            "  python scripts/generate_models_catalogue.py --summary --offline\n"
        ),
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Read catalogue caches only. Never hits the network; a missing or "
            "stale cache is used as-is (possibly empty). Takes precedence over "
            "--refresh."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Ignore TTL and FORCE-reload Download Center membership "
            "(upstream, Politrees, extras, mvsepless) plus yaml/models.txt "
            "supplements. Without this, a warm cache can keep yesterday's "
            "membership. No effect with --offline."
        ),
    )
    parser.add_argument(
        "--allow-degraded",
        action="store_true",
        help=(
            "Write even when sources failed or the catalogue shrank by more "
            "than 10%% versus the last published document. Use only when the "
            "shrinkage is real. Does not fix an empty or poisoned cache — "
            "use --refresh for that. Ignored by --summary, which always prints."
        ),
    )
    parser.add_argument(
        "--no-ir",
        action="store_true",
        help=(
            "Skip the gitignored .ir.json sidecar next to the document "
            "(SHA-256-tied entry count used by the publication guard)."
        ),
    )
    parser.add_argument(
        "--write-tsv",
        action="store_true",
        help=(
            f"Also write {os.path.basename(REFERENCE_TSV_PATH)} from community "
            "models.txt. Off by default; --check then compares it too."
        ),
    )
    parser.add_argument(
        "--write-display-reference",
        action="store_true",
        help=(
            f"Also write {os.path.basename(DISPLAY_REFERENCE_TSV_PATH)} with "
            "the complete current display projection and mechanical quality "
            "flags. Off by default; --check then compares it too."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help=(
            "Write docs/models-catalogue.md (and optional TSVs/sidecar). "
            "This is the default when neither --check nor --summary is passed."
        ),
    )
    mode.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Print entry counts, flagged mismatches and unknown intent to "
            "stdout. Writes nothing: no document, sidecar, TSV, or yaml "
            "download into the tree. Prints even when the run is degraded."
        ),
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help=(
            "Compare the generated catalogue to the on-disk document and "
            "write nothing. Volatile header lines (Generated, provenance, "
            "cache ages) are ignored, so drift means the catalogue changed, "
            "not that time passed. Exit 1 on drift, 2 if this run is too "
            "degraded to judge. Also read-only for yaml downloads."
        ),
    )
    return parser.parse_args(argv)


#: A drop larger than this fraction of the previously published catalogue is
#: treated as evidence the run is broken rather than as real shrinkage.
_DEGRADED_DROP_RATIO = 0.10


@dataclass(frozen=True)
class PublicationVerdict:
    """Whether this run's entries may replace the published document."""

    ok: bool
    reason: str = ""


def _previous_entry_count(path: str) -> Optional[int]:
    """Entry count from the last published run, if it can be recovered.

    Prefers the IR sidecar, which records the count as data. Falls back to
    re-parsing the rendered summary line for a document published before the
    sidecar existed, or when it is missing or unreadable.
    """
    try:
        with open(_ir_path_for(path), encoding="utf-8") as handle:
            payload = json.load(handle)
        count = payload.get("entry_count")
        recorded = payload.get("document_sha256") or ""
        # Only when the sidecar demonstrably describes *this* document. A
        # sidecar from a run whose document was replaced or restored is stale,
        # and trusting it would let a broken run clear a floor set by a good one.
        if isinstance(count, int) and recorded and recorded == _document_digest(path):
            return count
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = re.search(r"Total catalogue entries: \*\*(\d+)\*\*", line)
                if match:
                    return int(match.group(1))
    except OSError:
        return None
    return None


def _publication_verdict(
    *,
    entries: List[Any],
    report: Any,
    previous_count: Optional[int],
    allow_degraded: bool = False,
) -> PublicationVerdict:
    """Decide whether these entries may overwrite the published catalogue.

    The entry count is the trigger, not source health. Offline sources are
    simply not refreshed rather than reported as failed, so a cold cache
    yields report.usable True and report.failed empty while producing a
    fraction of the entries -- measured, an empty supplemental cache gave 88
    entries where the published document had 474. Failed and stale sources
    are still reported, as context for diagnosing the refusal.

    Legitimate shrinkage goes through --allow-degraded, which is the only
    thing that can distinguish it from a broken run.
    """
    if allow_degraded:
        return PublicationVerdict(ok=True, reason="--allow-degraded")

    if not getattr(report, "usable", True):
        return PublicationVerdict(
            ok=False,
            reason="catalogue snapshot is unusable (no source produced entries)",
        )

    if previous_count:
        floor = previous_count * (1 - _DEGRADED_DROP_RATIO)
        if len(entries) < floor:
            reason = f"{len(entries)} entries against {previous_count} previously"
            failed: Tuple[Any, ...] = tuple(getattr(report, "failed", ()) or ())
            stale: Tuple[Any, ...] = tuple(getattr(report, "stale", ()) or ())
            if failed:
                names = ", ".join(str(getattr(i[0], "value", i[0])) for i in failed)
                reason += f"; failed sources: {names}"
            if stale:
                names = ", ".join(str(getattr(i, "value", i)) for i in stale)
                reason += f"; stale sources: {names}"
            return PublicationVerdict(ok=False, reason=reason)
    return PublicationVerdict(ok=True)


def _policy_for(args: argparse.Namespace) -> FetchPolicy:
    """Fetch policy implied by the CLI flags."""
    return FetchPolicy(
        allow_network=not args.offline,
        refresh=args.refresh,
        # --check and --summary must leave the tree exactly as they found it.
        allow_metadata_writes=not (args.check or args.summary),
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    policy = _policy_for(args)
    ctx = collect._build_catalogue_context(policy=policy)
    snapshot, entries = collect.collect_entries(ctx, policy=policy)
    unsupported = _unsupported_count(getattr(snapshot, "unsupported", None))
    report = getattr(snapshot, "report", None)

    if args.summary:
        # Ahead of the publication guard on purpose: a summary writes nothing,
        # so there is no artifact to protect, and a degraded run is exactly
        # when a maintainer wants to see what the catalogue currently looks
        # like. The provenance block reports the degradation.
        print(render.render_summary_report(entries, unsupported_count=unsupported, report=report))
        return 0

    verdict = _publication_verdict(
        entries=list(entries),
        report=report,
        previous_count=_previous_entry_count(OUTPUT_PATH),
        allow_degraded=args.allow_degraded,
    )
    if not verdict.ok:
        if args.check:
            print(
                f"Cannot judge {OUTPUT_PATH}: {verdict.reason}.\n"
                "This run's data is too degraded to tell drift from a bad fetch.",
                file=sys.stderr,
            )
        else:
            print(
                f"Refusing to write {OUTPUT_PATH}: {verdict.reason}.\n"
                "Pass --allow-degraded if the catalogue really did shrink.",
                file=sys.stderr,
            )
        return 2

    rendered = render._render(entries, unsupported_count=unsupported, report=report)
    tsv_text = ""
    if args.write_tsv:
        if ctx.community_by_file:
            tsv_text = render._reference_tsv_text(ctx.community_by_file)
        else:
            print(
                f"--write-tsv had no community data; leaving {REFERENCE_TSV_PATH} alone "
                "(the models.txt fetch produced nothing).",
                file=sys.stderr,
            )

    display_reference = None
    display_reference_text = ""
    if args.write_display_reference:
        display_reference = render.presentation_reference_audit(entries)
        display_reference_text = display_reference.text

    if args.check:
        drift = []
        if not render._text_matches(OUTPUT_PATH, rendered):
            drift.append(OUTPUT_PATH)
        if tsv_text and not render._text_matches(REFERENCE_TSV_PATH, tsv_text):
            drift.append(REFERENCE_TSV_PATH)
        if display_reference_text and not render._text_matches(
            DISPLAY_REFERENCE_TSV_PATH, display_reference_text
        ):
            drift.append(DISPLAY_REFERENCE_TSV_PATH)
        if display_reference is not None:
            for model_id, flags in display_reference.unreviewed:
                print(
                    f"Unreviewed presentation flag(s): {model_id}: {', '.join(flags)}",
                    file=sys.stderr,
                )
            for display, model_ids in display_reference.collisions:
                print(
                    "Accidental case-insensitive display collision: "
                    f"{display!r}: {', '.join(model_ids)}",
                    file=sys.stderr,
                )
        if drift:
            for path in drift:
                print(f"Out of date: {path}", file=sys.stderr)
            regenerate = "python scripts/generate_models_catalogue.py"
            if REFERENCE_TSV_PATH in drift:
                regenerate += " --write-tsv"
            if DISPLAY_REFERENCE_TSV_PATH in drift:
                regenerate += " --write-display-reference"
            print(f"Regenerate with: {regenerate}", file=sys.stderr)
        if drift or (
            display_reference is not None
            and (display_reference.unreviewed or display_reference.collisions)
        ):
            return 1
        print(f"Up to date: {OUTPUT_PATH}")
        return 0

    from core.json_store import write_json_atomic, write_text_atomic

    # A failed write must not truncate the checked-in catalogue document.
    write_text_atomic(OUTPUT_PATH, rendered)
    if not args.no_ir:
        # After the document, so the sidecar never describes a run whose
        # document failed to land.
        write_json_atomic(
            _ir_path_for(OUTPUT_PATH),
            build_ir(
                entries,
                report=report,
                unsupported_count=unsupported,
                document_sha256=_document_digest(OUTPUT_PATH),
            ),
        )
    flagged = sum(1 for e in entries if e.flags)
    unknown = sum(1 for e in entries if e.name_intent == "unknown")
    with_meta = sum(1 for e in entries if e.metadata_source not in ("unavailable", ""))
    print(
        f"Wrote {OUTPUT_PATH} ({len(entries)} models, {with_meta} with metadata, "
        f"{unknown} unknown, {flagged} flagged, {unsupported} unsupported omitted)"
    )
    # Only after the guard: a refused run must not mutate this artifact either.
    if tsv_text:
        write_text_atomic(REFERENCE_TSV_PATH, tsv_text)
        print(f"Wrote {REFERENCE_TSV_PATH}")
    if display_reference_text:
        write_text_atomic(DISPLAY_REFERENCE_TSV_PATH, display_reference_text)
        print(f"Wrote {DISPLAY_REFERENCE_TSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
