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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from catalogue import (
    collect,
    render,
    stem_audit,
)
from catalogue.collect import (
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

from core.model_manifest import (
    BUNDLED_MODEL_MANIFEST_PATH,
    ModelManifestError,
    load_model_manifest_document,
)
from core.model_manifest.loader import _duplicate_aware_mapping

# Kept as the generator's patchable publication target while callers migrate
# from the former stem-only manifest name.
BUNDLED_MANIFEST_PATH = BUNDLED_MODEL_MANIFEST_PATH


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
            "  0  clean snapshot; write completed or no findings/drift\n"
            "  1  generated drift or semantic findings\n"
            "  2  degraded or unusable evidence\n"
            "  130  interrupted opt-in remote confidence audit\n"
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
            "download into the tree. Exit 1 on findings or generated drift, "
            "and 2 on degraded evidence."
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
    manifest: dict[str, object]


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


def _retained_refresh_report(path: str) -> Any:
    """Recover trusted publication provenance for a report-less warm run.

    The sidecar is accepted only when its document digest names the current
    Markdown file. This lets an offline/warm regeneration update semantic rows
    without erasing the last reviewed source-health evidence, while a stale or
    hand-copied sidecar remains untrusted.
    """
    from core.catalogue_types import RefreshMode, RefreshReport, SourceId

    try:
        with open(_ir_path_for(path), encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("document_sha256") != _document_digest(path):
            return None
        provenance = payload.get("provenance")
        if not isinstance(provenance, dict) or not provenance:
            return None
        mode = RefreshMode(str(provenance["mode"]))
        succeeded = tuple(SourceId(str(item)) for item in provenance.get("succeeded", ()))
        stale = tuple(SourceId(str(item)) for item in provenance.get("stale", ()))
        failed = tuple(
            (SourceId(str(item[0])), str(item[1]))
            for item in provenance.get("failed", ())
            if isinstance(item, (list, tuple)) and len(item) == 2
        )
        return RefreshReport(
            mode=mode,
            succeeded=succeeded,
            failed=failed,
            stale=stale,
            mixed_age=bool(provenance.get("mixed_age", False)),
            upstream_live=bool(provenance.get("upstream_live", False)),
            usable=bool(provenance.get("usable", False)),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
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
        # Offline is cache-only at every boundary, including the confidence
        # audit's legacy config and checkpoint-hash caches.
        refresh=args.refresh and not args.offline,
        # --check and --summary must leave the tree exactly as they found it.
        allow_metadata_writes=not (args.check or args.summary),
        allow_cache_writes=not (args.check or args.summary),
    )


def _text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_manifest_source(path: str | Path) -> tuple[dict[str, object], Any]:
    """Read and validate the unified source once before collection begins."""
    manifest_path = Path(path)
    try:
        document = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_aware_mapping,
        )
    except ModelManifestError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelManifestError(("manifest",), f"could not read manifest: {error}") from error
    if not isinstance(document, dict):
        raise ModelManifestError((), "must be an object")
    return document, load_model_manifest_document(document)


def _required_supplemental_evidence(ctx: collect.CatalogueContext) -> Tuple[str, ...]:
    """Name supplements required to produce a complete reviewed publication."""
    unavailable = list(ctx.unavailable_supplemental_evidence)
    missing_yamls = sorted(ctx.unavailable_yaml_evidence, key=str.casefold)
    if missing_yamls:
        preview = ", ".join(missing_yamls[:5])
        if len(missing_yamls) > 5:
            preview += f", ... (+{len(missing_yamls) - 5} more)"
        unavailable.append(
            f"per-model YAML/config metadata ({len(missing_yamls)} unavailable: {preview})"
        )
    return tuple(unavailable)


def _render_publication_bundle(
    entries: List[Any],
    *,
    ctx: collect.CatalogueContext,
    unsupported: int,
    report: Any,
    catalogue_text: str,
    document_sha256: str,
    audit: stem_audit.StemAuditResult,
    manifest_audit: stem_audit.ManifestCandidateResult,
    presentation: Mapping[str, Any] | None = None,
) -> PublicationBundle:
    """Render the complete in-memory candidate set from validated evidence."""
    intent_reference = render._reference_tsv_text(ctx.community_by_file)
    display_reference = render.presentation_reference_audit(
        entries,
        presentation=presentation,
    )
    stem_reference = render.stem_semantics_reference_tsv(audit.reference_rows)
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
        manifest=manifest_audit.document,
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


def _json_matches(path: str | Path, payload: object) -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, ValueError):
        return False
    return existing == payload


def _candidate_parity_diagnostic(
    audit: stem_audit.StemAuditResult,
    stem_reference: str,
) -> stem_audit.StemAuditDiagnostic | None:
    expected = stem_audit.reference_rows_tsv(audit.reference_rows)
    if stem_reference == expected:
        return None
    return stem_audit.StemAuditDiagnostic(
        code="reference-candidate-mismatch",
        model_ids=audit.catalogue_model_ids,
        message="rendered semantic reference differs from immutable audit rows",
        expected=(_text_digest(expected),),
        actual=(_text_digest(stem_reference),),
    )


def _validate_publication_bundle(bundle: PublicationBundle) -> None:
    """Finish every fallible render/serialization check before publication."""
    json.dumps(bundle.manifest, indent=2, sort_keys=True)
    json.dumps(bundle.ir, indent=2, sort_keys=True)
    for text in (
        bundle.catalogue,
        bundle.intent_reference,
        bundle.display_reference.text,
        bundle.stem_reference,
    ):
        text.encode("utf-8")


def _artifact_drift(
    bundle: PublicationBundle,
    *,
    include_ir: bool,
) -> list[str]:
    drift = []
    if not _json_matches(BUNDLED_MANIFEST_PATH, bundle.manifest):
        drift.append(str(BUNDLED_MANIFEST_PATH))
    if not render._text_matches(OUTPUT_PATH, bundle.catalogue):
        drift.append(OUTPUT_PATH)
    if include_ir and not _ir_matches(_ir_path_for(OUTPUT_PATH), bundle.ir):
        drift.append(_ir_path_for(OUTPUT_PATH))
    if not render._text_matches(REFERENCE_TSV_PATH, bundle.intent_reference):
        drift.append(REFERENCE_TSV_PATH)
    if not render._text_matches(DISPLAY_REFERENCE_TSV_PATH, bundle.display_reference.text):
        drift.append(DISPLAY_REFERENCE_TSV_PATH)
    if not render._text_matches(STEM_SEMANTICS_REFERENCE_TSV_PATH, bundle.stem_reference):
        drift.append(STEM_SEMANTICS_REFERENCE_TSV_PATH)
    return drift


def _print_presentation_findings(audit: render.PresentationReferenceAudit) -> None:
    for model_id, flags in audit.unreviewed:
        print(
            f"Unreviewed presentation flag(s): {model_id}: {', '.join(flags)}",
            file=sys.stderr,
        )
    for display, model_ids in audit.collisions:
        print(
            f"Accidental case-insensitive display collision: {display!r}: {', '.join(model_ids)}",
            file=sys.stderr,
        )


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


def _print_manifest_diagnostics(result: stem_audit.ManifestCandidateResult) -> None:
    for diagnostic in result.diagnostics:
        model_ids = ", ".join(diagnostic.model_ids) or "(global)"
        print(
            f"Manifest audit {diagnostic.code}: {model_ids}: {diagnostic.message}",
            file=sys.stderr,
        )


def _restore_bytes_atomic(path: str | Path, contents: bytes) -> None:
    """Restore one transaction snapshot without re-entering patched writers."""
    target = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(target))
    os.makedirs(directory, exist_ok=True)
    file_descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(target)}.", dir=directory
    )
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _publish_bundle(bundle: PublicationBundle, *, include_ir: bool) -> tuple[str, ...]:
    """Atomically replace one validated bundle, rolling back any late failure."""
    from core.json_store import write_json_atomic, write_text_atomic

    operations: list[tuple[str | Path, str, object]] = [
        (BUNDLED_MANIFEST_PATH, "json", bundle.manifest),
        (OUTPUT_PATH, "text", bundle.catalogue),
    ]
    if include_ir:
        operations.append((_ir_path_for(OUTPUT_PATH), "json", bundle.ir))
    operations.extend(
        (
            (REFERENCE_TSV_PATH, "text", bundle.intent_reference),
            (DISPLAY_REFERENCE_TSV_PATH, "text", bundle.display_reference.text),
            (STEM_SEMANTICS_REFERENCE_TSV_PATH, "text", bundle.stem_reference),
        )
    )
    snapshots: dict[str, bytes | None] = {}
    for path, _kind, _payload in operations:
        target = os.fspath(path)
        try:
            with open(target, "rb") as handle:
                snapshots[target] = handle.read()
        except FileNotFoundError:
            snapshots[target] = None

    try:
        for path, kind, payload in operations:
            target = os.fspath(path)
            if kind == "json":
                if not isinstance(payload, dict):
                    raise TypeError(f"JSON publication payload for {target} must be an object")
                write_json_atomic(target, payload)
            else:
                if not isinstance(payload, str):
                    raise TypeError(f"text publication payload for {target} must be text")
                write_text_atomic(target, payload)
    except BaseException:
        rollback_errors = []
        for path, _kind, _payload in reversed(operations):
            target = os.fspath(path)
            prior = snapshots[target]
            try:
                if prior is None:
                    try:
                        os.unlink(target)
                    except FileNotFoundError:
                        pass
                else:
                    _restore_bytes_atomic(target, prior)
            except OSError as error:
                rollback_errors.append(f"{target}: {error}")
        if rollback_errors:
            print(
                "Publication rollback failed: " + "; ".join(rollback_errors),
                file=sys.stderr,
            )
        raise
    return tuple(os.fspath(path) for path, _kind, _payload in operations)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
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
    try:
        manifest_document, unified_registry = _load_manifest_source(BUNDLED_MANIFEST_PATH)
    except ModelManifestError as error:
        print(f"Manifest audit manifest-invalid: {error}", file=sys.stderr)
        return 1
    _print_deprecated_reference_flags(args)
    ctx = collect._build_catalogue_context(policy=policy)
    reviewed_non_config_ids = frozenset(
        model_id
        for model_id, record in unified_registry.models.items()
        if not record.catalogue_evidence.config_yaml
    )
    snapshot, entries = collect.collect_entries(
        ctx,
        policy=policy,
        registry=unified_registry.stems,
        contracts=unified_registry.runtime,
        reviewed_non_config_ids=reviewed_non_config_ids,
        presentation=unified_registry.presentation,
        manifest_records=unified_registry.models,
    )
    unsupported = _unsupported_count(getattr(snapshot, "unsupported", None))
    report = getattr(snapshot, "report", None)
    missing_evidence = _required_supplemental_evidence(ctx)

    # Unavailable per-model evidence is a degraded acquisition, not hundreds
    # of guessed semantic defects. Report it before constructing any strict
    # artifact candidate or invoking the structural audit.
    if missing_evidence:
        if args.summary:
            print(
                render.render_summary_report(
                    entries,
                    unsupported_count=unsupported,
                    report=report,
                    presentation=unified_registry.presentation,
                )
            )
            print(
                "Supplemental evidence unavailable: " + ", ".join(missing_evidence),
                file=sys.stderr,
            )
            return 2
        action = "judge" if args.check else "publish"
        print(
            f"Cannot {action} a complete catalogue: required supplemental "
            "evidence unavailable: " + ", ".join(missing_evidence),
            file=sys.stderr,
        )
        return 2

    # A broken acquisition cannot supply meaningful manifest-coverage
    # diagnostics; preserve the degraded-evidence exit before phase 1.
    verdict = _publication_verdict(
        entries=list(entries),
        report=report,
        previous_count=_previous_entry_count(OUTPUT_PATH),
        allow_degraded=args.allow_degraded and not args.summary,
    )
    if not verdict.ok:
        if args.summary:
            print(
                render.render_summary_report(
                    entries,
                    unsupported_count=unsupported,
                    report=report,
                    presentation=unified_registry.presentation,
                )
            )
            print(
                f"Cannot judge {OUTPUT_PATH}: {verdict.reason}.",
                file=sys.stderr,
            )
        elif args.check:
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

    manifest_audit = stem_audit.build_manifest_candidate(
        entries,
        manifest_document,
        registry=unified_registry,
    )
    if manifest_audit.degraded:
        if args.summary:
            print(
                render.render_summary_report(
                    entries,
                    unsupported_count=unsupported,
                    report=report,
                    manifest_audit=manifest_audit,
                    presentation=unified_registry.presentation,
                )
            )
        _print_manifest_diagnostics(manifest_audit)
        return 2
    if not manifest_audit.structurally_valid:
        if args.summary:
            print(
                render.render_summary_report(
                    entries,
                    unsupported_count=unsupported,
                    report=report,
                    manifest_audit=manifest_audit,
                    presentation=unified_registry.presentation,
                )
            )
        _print_manifest_diagnostics(manifest_audit)
        return 1
    candidate_presentation = manifest_audit.presentation or unified_registry.presentation

    # Phase 1: validate the exact reconciled source/manifest snapshot before
    # any publication candidate is rendered.
    audit = stem_audit.audit_catalogue_stems(
        entries,
        ctx,
        registry=unified_registry.stems,
        current_model_ids=set(manifest_audit.current_model_ids),
    )
    if not audit.structurally_valid:
        if args.summary:
            print(
                render.render_summary_report(
                    entries,
                    unsupported_count=unsupported,
                    report=report,
                    stem_audit=audit,
                    presentation=candidate_presentation,
                )
            )
        _print_structural_stem_diagnostics(audit)
        return 1

    # Phase 2: render all candidates in memory and verify that the renderer is
    # byte-identical to the audit-owned structured reference rows.
    publication_report = report or _retained_refresh_report(OUTPUT_PATH)
    rendered_catalogue = render._render(
        entries,
        unsupported_count=unsupported,
        report=publication_report,
        presentation=candidate_presentation,
    )
    document_sha256 = _text_digest(rendered_catalogue)
    if (args.check or args.summary) and render._text_matches(OUTPUT_PATH, rendered_catalogue):
        document_sha256 = _document_digest(OUTPUT_PATH) or document_sha256
    bundle = _render_publication_bundle(
        entries,
        ctx=ctx,
        unsupported=unsupported,
        report=publication_report,
        catalogue_text=rendered_catalogue,
        document_sha256=document_sha256,
        audit=audit,
        manifest_audit=manifest_audit,
        presentation=candidate_presentation,
    )
    _validate_publication_bundle(bundle)
    candidate_diagnostic = _candidate_parity_diagnostic(audit, bundle.stem_reference)
    if candidate_diagnostic is not None:
        print(
            f"Stem audit {candidate_diagnostic.code}: {candidate_diagnostic.message}",
            file=sys.stderr,
        )
        return 1

    drift = _artifact_drift(bundle, include_ir=not args.no_ir)

    if args.summary:
        print(
            render.render_summary_report(
                entries,
                unsupported_count=unsupported,
                report=report,
                stem_audit=audit,
                manifest_audit=manifest_audit,
                presentation=candidate_presentation,
            )
        )
        _print_manifest_diagnostics(manifest_audit)
        _print_presentation_findings(bundle.display_reference)
        for path in drift:
            print(f"Out of date: {path}", file=sys.stderr)
        if (
            audit.diagnostics
            or manifest_audit.diagnostics
            or drift
            or bundle.display_reference.unreviewed
            or (bundle.display_reference.collisions)
        ):
            return 1
        return 0

    if args.check:
        _print_manifest_diagnostics(manifest_audit)
        _print_presentation_findings(bundle.display_reference)
        if drift:
            for path in drift:
                print(f"Out of date: {path}", file=sys.stderr)
            print("Regenerate with: python scripts/generate_models_catalogue.py", file=sys.stderr)
        if drift or bundle.display_reference.unreviewed or bundle.display_reference.collisions:
            return 1
        print(f"Up to date: {OUTPUT_PATH}")
        return 0

    if bundle.display_reference.collisions:
        _print_presentation_findings(bundle.display_reference)
        return 1

    # Every renderer and strict validator above has completed. Each generated
    # target is then atomically replaced as one rollback-protected transaction.
    written_paths = _publish_bundle(bundle, include_ir=not args.no_ir)
    flagged = sum(1 for e in entries if e.flags)
    unknown = sum(1 for e in entries if e.name_intent == "unknown")
    with_meta = sum(1 for e in entries if e.metadata_source not in ("unavailable", ""))
    print(
        f"Wrote {OUTPUT_PATH} ({len(entries)} models, {with_meta} with metadata, "
        f"{unknown} unknown, {flagged} flagged, {unsupported} unsupported omitted)"
    )
    for path in written_paths:
        if path != OUTPUT_PATH:
            print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
