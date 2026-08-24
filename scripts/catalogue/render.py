#!/usr/bin/env python3
"""Render catalogue entries into Markdown, summary text, and TSV."""

from __future__ import annotations

import os
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Tuple

from catalogue.collect import (
    COMMUNITY_CACHE_DIR,
    POLITREES_CACHE_DIR,
    REFERENCE_TSV_PATH,
    ROOT,
    YAML_CACHE_DIR,
    CommunityRef,
    ModelEntry,
    reviewed_stem_signature,
)
from core.model_catalogue import (
    catalogue_presentation_id,
    project_catalogue_display,
)
from core.model_naming import load_model_display_manifest


def _reference_tsv_text(refs: Dict[str, CommunityRef]) -> str:
    rows = sorted(refs.values(), key=lambda item: item.filename.lower())
    lines = ["filename\tarch\tprimary_stem\tintent\tstems\tfriendly_name"]
    for ref in rows:
        lines.append(
            "\t".join(
                [
                    ref.filename,
                    ref.arch,
                    ref.primary_stem,
                    ref.intent or "unknown",
                    ref.stems_text.replace("\t", " "),
                    ref.friendly_name.replace("\t", " "),
                ]
            )
        )
    return "\n".join(lines) + "\n"


_DISPLAY_REFERENCE_HEADERS = (
    "family",
    "execution_arch",
    "source",
    "catalogue_generation",
    "catalogue_label",
    "canonical_id",
    "current_display",
    "weight_file",
    "presentation_flags",
    "waiver_reasons",
    "review_status",
)
_VR_GENERATION_RE = re.compile(r"^VR Arch Single Model (v\d+):", re.IGNORECASE)
_DEMUCS_GENERATION_RE = re.compile(r"^Demucs (v\d+):", re.IGNORECASE)
_HYPHENATED_STEM_COUNT_RE = re.compile(r"\b\d+-stems?\b", re.IGNORECASE)
_RUNTIME_FAMILY_BY_CATALOGUE_FAMILY = {
    "VR Architecture": "vr",
    "Demucs": "demucs",
    "Apollo": "apollo",
    "MDX-Net": "mdx",
    "MDX-Net ONNX": "mdx",
    "MDX23C": "mdx",
    "Roformer": "mdx",
    "SCNet": "mdx",
    "Bandit": "mdx",
}


def _tsv_cell(value: Any) -> str:
    """Keep one logical value on one TSV row."""
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def _catalogue_generation(label: str) -> str:
    for pattern in (_VR_GENERATION_RE, _DEMUCS_GENERATION_RE):
        match = pattern.match(label)
        if match:
            return match.group(1).lower()
    return ""


def _presentation_flags(entry: ModelEntry, display: str) -> List[str]:
    """Mechanical indicators for names that merit presentation review.

    These are audit hints, not renaming rules. In particular, a raw basename
    may be the only honest label for an unknown custom model.
    """
    stem = os.path.splitext(os.path.basename(entry.weight_file))[0]
    flags: List[str] = []
    if display.casefold() == stem.casefold():
        flags.append("raw-basename")
    if "_" in display:
        flags.append("underscore")
    if _HYPHENATED_STEM_COUNT_RE.search(display):
        flags.append("hyphenated-stem-count")
    if re.search(r"\bHigh Quality\b", display, re.IGNORECASE):
        flags.append("expanded-hq")
    if re.search(r" — \(\d+ Stems\)(?:\s|$)", display):
        flags.append("leading-stem-count")
    if re.search(r"\(\s*only weights\s*\)", display, re.IGNORECASE):
        flags.append("operational-note")

    head, separator, tail = display.partition(" — ")
    if separator and head:
        repeated_head = re.compile(
            rf"^(?:(?:\d+-stems?|\(\d+ Stems\))\s+)?"
            rf"(?:huge\s+)?{re.escape(head)}\b",
            re.IGNORECASE,
        )
        if repeated_head.search(tail):
            flags.append("repeated-family")
    if re.search(r"\bInstVoc\b", display):
        flags.append("instvoc")
    if re.search(r"\bsdr\b", display):
        flags.append("lowercase-sdr")
    if "[" in display or "]" in display:
        flags.append("embedded-id")
    return flags


@dataclass(frozen=True)
class PresentationReferenceAudit:
    """Rendered reference plus strict quality outcomes for ``--check``."""

    text: str
    unreviewed: Tuple[Tuple[str, Tuple[str, ...]], ...]
    collisions: Tuple[Tuple[str, Tuple[str, ...]], ...]


def _catalogue_projection(entry: ModelEntry) -> Tuple[str, str]:
    try:
        family = _RUNTIME_FAMILY_BY_CATALOGUE_FAMILY[entry.family]
    except KeyError as exc:
        accepted = ", ".join(_RUNTIME_FAMILY_BY_CATALOGUE_FAMILY)
        raise ValueError(
            f"unsupported catalogue family {entry.family!r} for "
            f"{entry.catalogue_label!r}; accepted families: {accepted}"
        ) from exc
    if not entry.weight_file:
        raise ValueError(f"catalogue row has no primary artifact: {entry.catalogue_label!r}")
    files = {entry.weight_file: ""}
    if entry.config_yaml:
        files[entry.config_yaml] = ""
    meta = SimpleNamespace(
        label=entry.catalogue_label,
        display=entry.catalogue_label,
        files=files,
        checkpoint=entry.weight_file,
        stems=(),
    )
    model_id = catalogue_presentation_id(
        family,
        entry.catalogue_label,
        files,
        meta,
    )
    if model_id is None:
        raise ValueError(
            f"catalogue row has no unambiguous presentation primary: {entry.catalogue_label!r}"
        )
    return (
        model_id,
        project_catalogue_display(
            family,
            entry.catalogue_label,
            files,
            meta,
        ),
    )


def _canonical_model_id(entry: ModelEntry) -> str:
    return _catalogue_projection(entry)[0]


def _display_label(entry: ModelEntry) -> str:
    """Return the same exact projected label used by the UI and TSV audit."""
    return _catalogue_projection(entry)[1]


def presentation_reference_audit(
    entries: List[ModelEntry],
) -> PresentationReferenceAudit:
    """Project the complete catalogue through shared presentation and audit it."""
    projections = [_catalogue_projection(entry) for entry in entries]
    projected = [
        (entry, model_id) for entry, (model_id, _display) in zip(entries, projections, strict=True)
    ]
    displays = [display for _model_id, display in projections]
    display_counts: Dict[str, int] = {}
    for display in displays:
        key = unicodedata.normalize("NFKC", display).casefold()
        display_counts[key] = display_counts.get(key, 0) + 1

    manifest = load_model_display_manifest()
    waivers = manifest["waivers"]
    rows = []
    unreviewed_rows: List[Tuple[str, Tuple[str, ...]]] = []
    collision_members: Dict[str, List[str]] = {}
    collision_labels: Dict[str, str] = {}
    for (entry, model_id), display in zip(projected, displays, strict=True):
        flags = _presentation_flags(entry, display)
        collision_key = unicodedata.normalize("NFKC", display).casefold()
        if display_counts[collision_key] > 1:
            flags.append("duplicate-display")
            collision_members.setdefault(collision_key, []).append(model_id)
            collision_labels.setdefault(collision_key, display)
        exact_waivers: Mapping[str, str] = waivers.get(model_id, {})
        unreviewed = tuple(flag for flag in flags if flag not in exact_waivers)
        if unreviewed:
            unreviewed_rows.append((model_id, unreviewed))
        review_status = "clean" if not flags else "unreviewed" if unreviewed else "reviewed"
        waiver_reasons = " | ".join(
            f"{flag}: {exact_waivers[flag]}" for flag in flags if flag in exact_waivers
        )
        row = (
            entry.family,
            entry.arch or entry.family,
            entry.source,
            _catalogue_generation(entry.catalogue_label),
            entry.catalogue_label,
            model_id,
            display,
            entry.weight_file,
            ", ".join(flags),
            waiver_reasons,
            review_status,
        )
        rows.append(row)

    rows.sort(
        key=lambda row: (
            row[0].casefold(),
            row[6].casefold(),
            row[7].casefold(),
            row[4].casefold(),
        )
    )
    lines = ["\t".join(_DISPLAY_REFERENCE_HEADERS)]
    lines.extend("\t".join(_tsv_cell(cell) for cell in row) for row in rows)
    collisions = tuple(
        (
            collision_labels[key],
            tuple(sorted(model_ids, key=str.casefold)),
        )
        for key, model_ids in sorted(collision_members.items())
    )
    return PresentationReferenceAudit(
        text="\n".join(lines) + "\n",
        unreviewed=tuple(sorted(unreviewed_rows, key=lambda item: item[0].casefold())),
        collisions=collisions,
    )


def presentation_reference_tsv(entries: List[ModelEntry]) -> str:
    """Render the complete catalogue as deterministic presentation audit data."""
    return presentation_reference_audit(entries).text


def stem_semantics_reference_tsv(entries: List[ModelEntry]) -> str:
    """Render reviewed runtime semantics; guessed catalogue intent is evidence only."""
    from core.model_stem_manifest import (
        BUNDLED_MANIFEST_PATH,
        load_stem_manifest,
        resolve_model_stem_semantics,
    )
    from core.stem_roles import StemProcessingContext, StemRoleId

    registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
    lines = [
        "model_id\tmodel_display\tnative_signature\tprocessing_context\tnative_stem\t"
        "production\tbackend_primary\tbackend_target\tlogical_primary\trole_id\t"
        "canonical_name\tfilename_tag\tpair_id\tintent\tintent_source\treview_status\t"
        "evidence_or_waiver"
    ]
    for entry in sorted(entries, key=_canonical_model_id):
        model_id = _canonical_model_id(entry)
        native_signature = reviewed_stem_signature(model_id, entry.instruments)
        contexts = [StemProcessingContext.FULL_MIX]
        declaration = registry.models.get(model_id)
        if declaration is not None and StemProcessingContext.VOCAL_SPLIT in declaration.contexts:
            contexts.append(StemProcessingContext.VOCAL_SPLIT)
        for context in contexts:
            semantics = resolve_model_stem_semantics(
                model_id,
                native_stems=native_signature,
                backend_primary=entry.primary_stem,
                backend_target=entry.target_instrument,
                context=context,
                registry=registry,
            )
            context_roles = {output.role for output in semantics.outputs}
            for output in semantics.outputs:
                role = output.role.value if isinstance(output.role, StemRoleId) else output.role.tag
                definition = (
                    registry.roles.get(output.role) if isinstance(output.role, StemRoleId) else None
                )
                pair_id = next(
                    (
                        pair.id
                        for pair in registry.pairs.values()
                        if output.role in pair.roles and set(pair.roles).issubset(context_roles)
                    ),
                    "",
                )
                lines.append(
                    "\t".join(
                        _tsv_cell(value)
                        for value in (
                            model_id,
                            _display_label(entry),
                            "|".join(native_signature),
                            context.value,
                            output.native.raw if output.native else "",
                            output.production.value,
                            entry.primary_stem,
                            entry.target_instrument,
                            str(output.logical_primary).lower(),
                            role,
                            definition.display
                            if definition
                            else output.native.raw
                            if output.native
                            else role,
                            definition.filename_tag
                            if definition
                            else output.native.raw
                            if output.native
                            else role,
                            pair_id,
                            semantics.intent,
                            "reviewed_manifest",
                            semantics.status.value,
                            semantics.evidence or semantics.warning,
                        )
                    )
                )
    seen = {_canonical_model_id(entry) for entry in entries}
    for model_id, reason in sorted(registry.waivers.items()):
        if model_id in seen:
            lines.append(
                "\t".join(
                    (
                        model_id,
                        "",
                        "",
                        "full_mix",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "reviewed_waiver",
                        "waived",
                        reason,
                    )
                )
            )
    return "\n".join(lines) + "\n"


def render_summary_report(
    entries: List[ModelEntry], *, unsupported_count: int = 0, report: Any = None
) -> str:
    """Just the exceptions: what a maintainer is usually looking for.

    The full document is 7,000+ lines of per-model detail. During catalogue,
    stem-routing or metadata changes the question is almost always "what looks
    wrong now?", which is the flagged and unknown-intent sets plus counts.
    """
    flagged = [e for e in entries if e.flags]
    unknown = [e for e in entries if e.name_intent == "unknown"]
    with_meta = [e for e in entries if e.metadata_source not in ("unavailable", "")]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# UVR Model Catalogue — summary",
        "",
        f"Generated: {now} by `scripts/generate_models_catalogue.py --summary`.",
        "",
        *_provenance_lines(report),
        "## Counts",
        "",
        f"- Total catalogue entries: **{len(entries)}**",
        f"- Entries with resolved metadata: **{len(with_meta)}**",
        f"- Unknown intent remaining: **{len(unknown)}**",
        f"- Flagged mismatches: **{len(flagged)}**",
        f"- Unsupported mvsepless entries (omitted): **{unsupported_count}**",
        "",
    ]

    if flagged:
        lines += ["## Flagged mismatches", ""]
        for entry in flagged:
            lines.append(
                f"- **{_display_label(entry)}** ({entry.family}) — " + "; ".join(entry.flags)
            )
        lines.append("")
    if unknown:
        lines += ["## Unknown intent", ""]
        for entry in unknown:
            lines.append(f"- **{_display_label(entry)}** ({entry.family}, {entry.source})")
        lines.append("")
    degraded = _summary_health_warning(entries, report)
    if degraded:
        lines += [degraded, ""]
    elif not flagged and not unknown:
        lines += ["Nothing flagged, and every entry resolved an intent.", ""]
    return "\n".join(lines)


def _summary_health_warning(entries: List[ModelEntry], report: Any) -> str:
    """Why an empty exception list may mean a failed run, not a clean one.

    --summary deliberately runs ahead of the publication guard, so nothing
    else tells the reader the fetch collapsed; "nothing flagged" over zero
    entries would read as a clean bill of health for a total failure.
    """
    if report is not None and not getattr(report, "usable", True):
        return (
            "> **Snapshot unusable** — no source produced entries. These counts "
            "describe a failed fetch, not the catalogue."
        )
    if not entries:
        return (
            "> **No entries collected** — nothing was found to report on. "
            "Check the source provenance above before reading anything into this."
        )
    return ""


def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        safe = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in row]
        lines.append("| " + " | ".join(safe) + " |")
    return "\n".join(lines)


def _render(entries: List[ModelEntry], *, unsupported_count: int = 0, report: Any = None) -> str:
    flagged = [e for e in entries if e.flags]
    unknown = [e for e in entries if e.name_intent == "unknown"]
    with_meta = [e for e in entries if e.metadata_source not in ("unavailable", "")]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# UVR Model Catalogue (TRvlvr + Politrees + extras + mvsepless)",
        "",
        f"Generated: {now} by `scripts/generate_models_catalogue.py`.",
        "",
        "Regenerate after catalogue updates:",
        "",
        "```bash",
        "python scripts/generate_models_catalogue.py",
        "```",
        "",
        "Intent sources: catalogue label, yaml/hash metadata, Politrees model_data,",
        "and [upseem/uvr5-cli-no-ui models.txt](https://github.com/upseem/uvr5-cli-no-ui/blob/main/models.txt)",
        f"(cached as `{os.path.relpath(REFERENCE_TSV_PATH, ROOT)}`).",
        "",
        "## How to read this",
        "",
        "- **Name intent** — from label, metadata, or community reference.",
        "- **Backend focus** — catalogue helper summarizing primary/target; export is concept/route based.",
        "- **Best result** — the stem users typically want from that model name.",
        "- **Flags** — vocal/instrumental labelling mismatches (only when metadata resolved).",
        "",
        "### Roformer `other` yaml quirk (not a bug)",
        "",
        "Instrumental Mel-Band / BS models often use `target_instrument: other` with",
        "`instruments: [other, vocals]`. That is a **2-stem vocal/instrumental** split.",
        "The GUI should show **Vocals** / **Instrumental** for 2-stem yaml pairs, not Demucs Other.",
        "",
        *_provenance_lines(report),
        "## Summary",
        "",
        f"- Total catalogue entries: **{len(entries)}**",
        f"- Entries with resolved metadata: **{len(with_meta)}**",
        f"- Unknown intent remaining: **{len(unknown)}**",
        f"- Flagged mismatches: **{len(flagged)}**",
        f"- Unsupported mvsepless entries (omitted): **{unsupported_count}**",
        "",
    ]

    if unknown:
        lines.extend(
            [
                "## Models with unknown intent",
                "",
                _md_table(
                    ["Family", "Model", "Metadata", "Primary/Target"],
                    [
                        [
                            e.family,
                            _display_label(e),
                            e.metadata_source,
                            e.target_instrument or e.primary_stem or "—",
                        ]
                        for e in unknown
                    ],
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Quick reference (all models)",
            "",
            _md_table(
                ["Family", "Model", "Intent", "Best result", "Backend", "Target", "Flags"],
                [
                    [
                        e.family,
                        _display_label(e),
                        e.name_intent,
                        (e.best_result[:50] + "…") if len(e.best_result) > 50 else e.best_result,
                        e.backend_focus,
                        e.target_instrument or e.primary_stem,
                        "; ".join(e.flags) or "—",
                    ]
                    for e in entries
                ],
            ),
            "",
        ]
    )

    karaoke_models = [e for e in entries if e.name_intent == "karaoke" or e.is_karaoke]
    if karaoke_models:
        lines.extend(
            [
                "## Karaoke models",
                "",
                "Karaoke models differ by architecture: VR HP-Karaoke uses **Instrumental** as",
                "`primary_stem`; MDX-Net Karaoke uses **Vocals** with `is_karaoke: true`.",
                "Roformer karaoke yamls typically target **vocals** (lead) with instrumental complement.",
                "",
                _md_table(
                    ["Model", "Primary", "Karaoke flag", "Best result"],
                    [
                        [
                            _display_label(e),
                            e.primary_stem or e.target_instrument,
                            "yes" if e.is_karaoke else "—",
                            e.best_result,
                        ]
                        for e in karaoke_models
                    ],
                ),
                "",
            ]
        )

    other_yaml_inst = [
        e
        for e in entries
        if e.name_intent == "instrumental" and e.target_instrument.lower() == "other"
    ]
    if other_yaml_inst:
        lines.extend(
            [
                "## Instrumental models with yaml stem `other`",
                "",
                "These models are **instrumental-first** in practice. The training yaml names the",
                "native output `other` (not `Instrumental`). Backend `primary_stem` is therefore",
                "`other`, which previously showed as Demucs-style “Other” in the GUI. Relabel to",
                "**Vocals** / **Instrumental** (yaml `other` is the backing track).",
                "",
                _md_table(
                    ["Model", "Config", "Instruments", "Best result"],
                    [
                        [
                            _display_label(e),
                            e.config_yaml,
                            ", ".join(e.instruments),
                            e.best_result,
                        ]
                        for e in other_yaml_inst
                    ],
                ),
                "",
            ]
        )

    if flagged:
        lines.extend(
            [
                "## Flagged mismatches",
                "",
                _md_table(
                    ["Label", "Intent", "Backend", "Target/Primary", "Best result", "Flags"],
                    [
                        [
                            _display_label(e),
                            e.name_intent,
                            e.backend_focus,
                            e.target_instrument or e.primary_stem,
                            e.best_result,
                            "; ".join(e.flags),
                        ]
                        for e in flagged
                    ],
                ),
                "",
            ]
        )

    current_family = None
    for entry in entries:
        if entry.family != current_family:
            current_family = entry.family
            lines.extend([f"## {current_family} (detail)", ""])
        short = _display_label(entry)
        lines.append(f"### {short}")
        lines.append("")
        lines.append(f"- **Source:** {entry.source}")
        lines.append(f"- **Weight:** `{entry.weight_file}`")
        if entry.config_yaml:
            lines.append(f"- **Config:** `{entry.config_yaml}`")
        if entry.arch:
            lines.append(f"- **Architecture:** {entry.arch}")
        lines.append(f"- **Name intent:** {entry.name_intent}")
        lines.append(f"- **Backend focus:** {entry.backend_focus}")
        if entry.primary_stem:
            lines.append(f"- **Primary stem (backend):** `{entry.primary_stem}`")
        if entry.instruments:
            lines.append(f"- **Instruments:** {', '.join(entry.instruments)}")
        if entry.target_instrument:
            lines.append(f"- **Target instrument:** `{entry.target_instrument}`")
        if entry.is_karaoke:
            lines.append("- **Karaoke model:** yes")
        lines.append(f"- **Best result:** {entry.best_result}")
        if entry.ui_export_note:
            lines.append(f"- **Save stems UI:** {entry.ui_export_note}")
        lines.append(f"- **Metadata:** {entry.metadata_source}")
        for note in entry.notes:
            lines.append(f"- **Note:** {note}")
        if entry.flags:
            lines.append(f"- **⚠ Flags:** {'; '.join(entry.flags)}")
        lines.append("")

    return "\n".join(lines)


#: Line prefixes that change on every run regardless of the catalogue. Drift
#: means the catalogue changed, not that time passed or a cache aged, so these
#: are excluded from the --check comparison.
_VOLATILE_PREFIXES = ("Generated: ", "- Snapshot ", "- Source ", "- Cache ")


def _canonical_for_diff(text: str) -> str:
    """``text`` with the volatile header lines removed, for drift comparison."""
    return "\n".join(line for line in text.splitlines() if not line.startswith(_VOLATILE_PREFIXES))


def _text_matches(path: str, text: str) -> bool:
    """Whether ``path`` already holds ``text``, ignoring volatile header lines."""
    try:
        with open(path, encoding="utf-8") as handle:
            existing = handle.read()
    except OSError:
        return False
    return _canonical_for_diff(existing) == _canonical_for_diff(text)


def _provenance_lines(report: Any) -> List[str]:
    """Where this document's data came from, and how healthy it was.

    Answers "was this generated from good data?" at review time -- a document
    regenerated from a half-stale snapshot otherwise looks identical to one
    built from a clean fetch.
    """
    if report is None:
        return []

    def names(items: Any) -> str:
        collected: List[str] = [str(getattr(item, "value", item)) for item in (tuple(items or ()))]
        return ", ".join(collected) if collected else "none"

    lines = [
        "## Source provenance",
        "",
        f"- Snapshot mode: `{getattr(getattr(report, 'mode', None), 'value', 'unknown')}`",
        f"- Source refreshed: {names(getattr(report, 'succeeded', ()))}",
        f"- Source stale: {names(getattr(report, 'stale', ()))}",
    ]
    failed: Tuple[Any, ...] = tuple(getattr(report, "failed", ()) or ())
    if failed:
        detail = "; ".join(f"{getattr(item[0], 'value', item[0])} ({item[1]})" for item in failed)
        lines.append(f"- Source failed: {detail}")
    else:
        lines.append("- Source failed: none")
    lines.append(f"- Source upstream live: {bool(getattr(report, 'upstream_live', False))}")

    for label, cache_dir in (
        ("politrees", POLITREES_CACHE_DIR),
        ("community", COMMUNITY_CACHE_DIR),
        ("yaml", YAML_CACHE_DIR),
    ):
        lines.append(f"- Cache {label}: {_cache_age_text(cache_dir)}")
    lines.append("")
    return lines


def _cache_age_text(cache_dir: str) -> str:
    """Newest entry age in a supplemental cache directory, in human terms."""
    try:
        stamps = [os.path.getmtime(os.path.join(cache_dir, name)) for name in os.listdir(cache_dir)]
    except OSError:
        return "absent"
    if not stamps:
        return "empty"
    age = time.time() - max(stamps)
    if age < 3600:
        return f"{age / 60:.0f}m old"
    if age < 86400:
        return f"{age / 3600:.0f}h old"
    return f"{age / 86400:.0f}d old"
