#!/usr/bin/env python3
"""Render catalogue entries into Markdown, summary text, and TSV."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from catalogue.collect import (
    COMMUNITY_CACHE_DIR,
    POLITREES_CACHE_DIR,
    REFERENCE_TSV_PATH,
    ROOT,
    YAML_CACHE_DIR,
    CommunityRef,
    ModelEntry,
    _display_label,
)


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
            lines.append(f"- **{_display_label(entry)}** ({entry.family}) — "
                         + "; ".join(entry.flags))
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


def _render(
    entries: List[ModelEntry], *, unsupported_count: int = 0, report: Any = None
) -> str:
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
                        _display_label(e)[:60],
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
        if e.name_intent == "instrumental"
        and e.target_instrument.lower() == "other"
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
    return "\n".join(
        line
        for line in text.splitlines()
        if not line.startswith(_VOLATILE_PREFIXES)
    )


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
        collected: List[str] = [
            str(getattr(item, "value", item)) for item in (tuple(items or ()))
        ]
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
        detail = "; ".join(
            f"{getattr(item[0], 'value', item[0])} ({item[1]})" for item in failed
        )
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
        stamps = [
            os.path.getmtime(os.path.join(cache_dir, name))
            for name in os.listdir(cache_dir)
        ]
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

