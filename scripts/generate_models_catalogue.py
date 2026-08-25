#!/usr/bin/env python3
"""Generate docs/models-catalogue.md from the Download Center catalogue snapshot.

Membership comes from ``CatalogueCoordinator`` (TRvlvr → Politrees → extras →
mvsepless, plus Apollo). This script audits stem metadata against catalogue
naming intent so mislabeled vocal vs instrumental models can be spotted.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from catalogue import (
    collect,
    render,
    stem_audit,
)  # noqa: E402
from catalogue.collect import (  # noqa: E402
    DISPLAY_REFERENCE_TSV_PATH,
    OUTPUT_PATH,
    REFERENCE_TSV_PATH,
    STEM_SEMANTICS_REFERENCE_TSV_PATH,
    FetchPolicy,
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
            "  0  wrote, or --check found no drift, or --summary completed\n"
            "  1  --check found drift (canonical text changed; header dates ignored)\n"
            "  2  this run's data is too degraded to publish or to judge drift\n"
            "\n"
            "Examples:\n"
            "  python scripts/generate_models_catalogue.py\n"
            "  python scripts/generate_models_catalogue.py --refresh\n"
            "  python scripts/generate_models_catalogue.py --check\n"
            "  python scripts/generate_models_catalogue.py --summary --offline\n"
            "  python scripts/generate_models_catalogue.py --audit-stem-confidence --guessed-only\n"
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
            f"Deprecated compatibility option. {os.path.basename(REFERENCE_TSV_PATH)} "
            "is always generated and compared."
        ),
    )
    parser.add_argument(
        "--write-display-reference",
        action="store_true",
        help=(
            f"Deprecated compatibility option. {os.path.basename(DISPLAY_REFERENCE_TSV_PATH)} "
            "is always generated and compared."
        ),
    )
    parser.add_argument(
        "--write-stem-semantics-reference",
        action="store_true",
        help=(
            f"Deprecated compatibility option. {os.path.basename(STEM_SEMANTICS_REFERENCE_TSV_PATH)} "
            "is always generated and compared."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help=(
            "Write the catalogue, IR sidecar, and all generated references. "
            "This is the default when neither --check nor --summary is passed."
        ),
    )
    mode.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Print entry counts, semantic findings, flagged mismatches and unknown intent to "
            "stdout. Writes nothing: no document, sidecar, TSV, or yaml "
            "download into the tree. Prints before reporting degraded evidence."
        ),
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help=(
            "Compare every generated artifact to its on-disk counterpart and "
            "write nothing. Volatile header lines (Generated, provenance, "
            "cache ages) are ignored, so drift means the catalogue changed, "
            "not that time passed. Exit 1 on drift, 2 if this run is too "
            "degraded to judge. Also read-only for yaml downloads."
        ),
    )
    mode.add_argument(
        "--audit-stem-confidence",
        action="store_true",
        help=(
            "Review mvsepless checkpoint confidence without generating or checking "
            "publication artifacts."
        ),
    )
    audit = parser.add_argument_group("stem confidence audit options")
    audit.add_argument(
        "--guessed-only",
        action="store_true",
        help="Only report entries whose karaoke confidence is not curated.",
    )
    audit.add_argument(
        "--only",
        default="",
        metavar="SUBSTR",
        help="Audit only entries whose id or label contains this substring.",
    )
    audit.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Audit at most this many entries after --only.",
    )
    audit.add_argument(
        "--json",
        dest="json_path",
        default=None,
        metavar="PATH",
        help="Atomically write the full stem-confidence report JSON to PATH.",
    )
    audit.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-model stem-confidence audit progress.",
    )
    audit.add_argument(
        "--no-cache",
        "--no-hash-cache",
        dest="no_hash_cache",
        action="store_true",
        help="Bypass remembered checkpoint-tail hashes for the confidence audit.",
    )
    args = parser.parse_args(argv)
    audit_options_used = any(
        (
            args.guessed_only,
            bool(args.only),
            args.limit is not None,
            args.json_path is not None,
            args.quiet,
            args.no_hash_cache,
        )
    )
    if audit_options_used and not args.audit_stem_confidence:
        parser.error("stem-confidence audit options require --audit-stem-confidence")
    if args.audit_stem_confidence and args.offline and args.no_hash_cache:
        parser.error("--offline cannot be combined with --no-cache")
    return args


#: A drop larger than this fraction of the previously published catalogue is
#: treated as evidence the run is broken rather than as real shrinkage.
_DEGRADED_DROP_RATIO = 0.10


@dataclass(frozen=True)
class PublicationVerdict:
    """Whether this run's entries may replace the published document."""

    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class PublicationBundle:
    """Every candidate generated from one collected catalogue snapshot."""

    catalogue: str
    intent_reference: str
    display_reference: render.PresentationReferenceAudit
    stem_reference: str
    ir: dict[str, Any]
    stem_audit: stem_audit.StemAuditResult


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
        allow_cache_writes=not (args.check or args.summary),
    )


def _read_text_or_none(path: str) -> Optional[str]:
    """Read an existing generated text artifact without creating it."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _required_supplemental_evidence(ctx: collect.CatalogueContext) -> Tuple[str, ...]:
    """Name supplements required to produce a complete reviewed publication."""
    return tuple(ctx.unavailable_supplemental_evidence)


def _render_publication_bundle(
    entries: List[Any],
    *,
    ctx: collect.CatalogueContext,
    unsupported: int,
    report: Any,
    catalogue_text: str,
    document_sha256: str,
) -> PublicationBundle:
    """Render and validate the complete output set before publication starts."""
    intent_reference = render._reference_tsv_text(ctx.community_by_file)
    display_reference = render.presentation_reference_audit(entries)
    stem_reference = render.stem_semantics_reference_tsv(entries)
    audit = stem_audit.audit_catalogue_stems(
        entries,
        ctx,
        expected_reference_text=stem_reference,
        actual_reference_text=_read_text_or_none(STEM_SEMANTICS_REFERENCE_TSV_PATH),
    )
    ir = build_ir(
        entries,
        report=report,
        unsupported_count=unsupported,
        document_sha256=document_sha256,
    )
    return PublicationBundle(
        catalogue=catalogue_text,
        intent_reference=intent_reference,
        display_reference=display_reference,
        stem_reference=stem_reference,
        ir=ir,
        stem_audit=audit,
    )


def _canonical_ir_for_diff(payload: Any) -> Any:
    """Ignore generation/provenance fields that do not change catalogue data."""
    if not isinstance(payload, dict):
        return payload
    canonical = dict(payload)
    canonical.pop("generated_at", None)
    canonical.pop("provenance", None)
    return canonical


def _ir_matches(path: str, payload: dict[str, Any]) -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, ValueError):
        return False
    return _canonical_ir_for_diff(existing) == _canonical_ir_for_diff(payload)


def _print_deprecated_reference_flags(args: argparse.Namespace) -> None:
    for flag in (
        "write_tsv",
        "write_display_reference",
        "write_stem_semantics_reference",
    ):
        if getattr(args, flag):
            option = "--" + flag.replace("_", "-")
            print(
                f"Warning: {option} is deprecated and has no effect; "
                "all generated references are always synchronized.",
                file=sys.stderr,
            )


def _print_structural_stem_diagnostics(result: stem_audit.StemAuditResult) -> None:
    for diagnostic in result.diagnostics:
        if not diagnostic.structural:
            continue
        model_ids = ", ".join(diagnostic.model_ids) or "(global)"
        print(
            f"Stem audit {diagnostic.code}: {model_ids}: {diagnostic.message}",
            file=sys.stderr,
        )


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    _print_deprecated_reference_flags(args)
    policy = _policy_for(args)
    if args.audit_stem_confidence:
        return stem_audit.run_stem_confidence_audit(
            policy=policy,
            guessed_only=args.guessed_only,
            only=args.only,
            limit=args.limit,
            json_path=args.json_path,
            quiet=args.quiet,
            no_hash_cache=args.no_hash_cache,
        )
    ctx = collect._build_catalogue_context(policy=policy)
    snapshot, entries = collect.collect_entries(ctx, policy=policy)
    unsupported = _unsupported_count(getattr(snapshot, "unsupported", None))
    report = getattr(snapshot, "report", None)

    # A check candidate must retain the current document's exact sidecar link
    # when Markdown differs only in volatile provenance/header lines. A write
    # instead binds the new IR to the new document bytes before either file is
    # replaced.
    rendered_catalogue = render._render(entries, unsupported_count=unsupported, report=report)
    document_sha256 = _text_digest(rendered_catalogue)
    if args.check and render._text_matches(OUTPUT_PATH, rendered_catalogue):
        document_sha256 = _document_digest(OUTPUT_PATH) or document_sha256
    bundle = _render_publication_bundle(
        entries,
        ctx=ctx,
        unsupported=unsupported,
        report=report,
        catalogue_text=rendered_catalogue,
        document_sha256=document_sha256,
    )

    missing_evidence = _required_supplemental_evidence(ctx)

    if args.summary:
        # Ahead of the publication guard on purpose: a summary writes nothing,
        # so there is no artifact to protect, and a degraded run is exactly
        # when a maintainer wants to see what the catalogue currently looks
        # like. The provenance block reports the degradation.
        print(
            render.render_summary_report(
                entries,
                unsupported_count=unsupported,
                report=report,
                stem_audit=bundle.stem_audit,
            )
        )
        if missing_evidence:
            print(
                "Supplemental evidence unavailable: " + ", ".join(missing_evidence),
                file=sys.stderr,
            )
            return 2
        return 0

    if missing_evidence:
        action = "judge" if args.check else "publish"
        print(
            f"Cannot {action} a complete catalogue: required supplemental "
            "evidence unavailable: " + ", ".join(missing_evidence),
            file=sys.stderr,
        )
        return 2

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

    if not bundle.stem_audit.structurally_valid:
        _print_structural_stem_diagnostics(bundle.stem_audit)
        return 1

    if args.check:
        drift = []
        if not render._text_matches(OUTPUT_PATH, bundle.catalogue):
            drift.append(OUTPUT_PATH)
        if not args.no_ir and not _ir_matches(_ir_path_for(OUTPUT_PATH), bundle.ir):
            drift.append(_ir_path_for(OUTPUT_PATH))
        if not render._text_matches(REFERENCE_TSV_PATH, bundle.intent_reference):
            drift.append(REFERENCE_TSV_PATH)
        if not render._text_matches(DISPLAY_REFERENCE_TSV_PATH, bundle.display_reference.text):
            drift.append(DISPLAY_REFERENCE_TSV_PATH)
        if not render._text_matches(STEM_SEMANTICS_REFERENCE_TSV_PATH, bundle.stem_reference):
            drift.append(STEM_SEMANTICS_REFERENCE_TSV_PATH)
        for model_id, flags in bundle.display_reference.unreviewed:
            print(
                f"Unreviewed presentation flag(s): {model_id}: {', '.join(flags)}",
                file=sys.stderr,
            )
        for display, model_ids in bundle.display_reference.collisions:
            print(
                "Accidental case-insensitive display collision: "
                f"{display!r}: {', '.join(model_ids)}",
                file=sys.stderr,
            )
        if drift:
            for path in drift:
                print(f"Out of date: {path}", file=sys.stderr)
            print("Regenerate with: python scripts/generate_models_catalogue.py", file=sys.stderr)
        if drift or bundle.display_reference.unreviewed or bundle.display_reference.collisions:
            return 1
        print(f"Up to date: {OUTPUT_PATH}")
        return 0

    from core.json_store import write_json_atomic, write_text_atomic

    # Every renderer and strict validator above has completed. Each generated
    # target is then atomically replaced, so a failed replacement cannot
    # truncate a checked-in artifact or publish an unvalidated candidate.
    write_text_atomic(OUTPUT_PATH, bundle.catalogue)
    if not args.no_ir:
        write_json_atomic(_ir_path_for(OUTPUT_PATH), bundle.ir)
    write_text_atomic(REFERENCE_TSV_PATH, bundle.intent_reference)
    write_text_atomic(DISPLAY_REFERENCE_TSV_PATH, bundle.display_reference.text)
    write_text_atomic(STEM_SEMANTICS_REFERENCE_TSV_PATH, bundle.stem_reference)
    flagged = sum(1 for e in entries if e.flags)
    unknown = sum(1 for e in entries if e.name_intent == "unknown")
    with_meta = sum(1 for e in entries if e.metadata_source not in ("unavailable", ""))
    print(
        f"Wrote {OUTPUT_PATH} ({len(entries)} models, {with_meta} with metadata, "
        f"{unknown} unknown, {flagged} flagged, {unsupported} unsupported omitted)"
    )
    for path in (
        _ir_path_for(OUTPUT_PATH),
        REFERENCE_TSV_PATH,
        DISPLAY_REFERENCE_TSV_PATH,
        STEM_SEMANTICS_REFERENCE_TSV_PATH,
    ):
        if path != _ir_path_for(OUTPUT_PATH) or not args.no_ir:
            print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
