"""Parse SDR scores and purpose buckets for model browsing."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from core.model_stem_semantics import (
    INTENT_DRUM_BASS_SEP,
    INTENT_DUAL_VOC_INST,
    INTENT_INSTRUMENTAL,
    INTENT_KARAOKE,
    INTENT_MULTI_STEM,
    INTENT_SPECIAL_FX,
    INTENT_SPECIALTY_STEM,
    INTENT_UNKNOWN,
    INTENT_VOCALS,
    infer_name_intent_from_label,
)

# Explicit float SDR in filenames / labels: ``_sdr_12.9755`` or ``sdr 12.97``.
_SDR_FLOAT_RE = re.compile(r"(?i)(?:^|[^a-z0-9])sdr[_\s-]*(\d+\.\d+)")
# Integer-coded SDR in filenames / labels: ``sdr_1297`` / ``SDR 1143`` → 12.97 / 11.43.
_SDR_INT_RE = re.compile(r"(?i)(?:^|[^a-z0-9])sdr[_\s-]*(\d{3,4})(?:[^0-9.]|$)")
# Viperx-style abbreviated mapper labels: ``…-Viperx-1297``.
_VIPERX_ABBREV_RE = re.compile(r"(?i)viperx[-_]?(\d{4})\b")

PURPOSE_ALL = "all"
PURPOSE_VOCALS = "vocals"
PURPOSE_INSTRUMENTAL = "instrumental"
PURPOSE_KARAOKE = "karaoke"
PURPOSE_SPECIALTY = "specialty"
PURPOSE_OTHER = "other"

PURPOSE_FILTER_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (PURPOSE_ALL, "All purposes"),
    (PURPOSE_VOCALS, "Vocals"),
    (PURPOSE_INSTRUMENTAL, "Instrumental"),
    (PURPOSE_KARAOKE, "Karaoke"),
    (PURPOSE_SPECIALTY, "Specialty"),
    (PURPOSE_OTHER, "Other"),
)

SORT_NAME = "name"
SORT_SDR = "sdr"

SORT_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (SORT_NAME, "Sort by name"),
    (SORT_SDR, "Sort by SDR"),
)


def parse_sdr_score(*texts: Optional[str]) -> Optional[float]:
    """Return the best SDR float found in any of the given strings, or ``None``."""
    best: Optional[float] = None
    for text in texts:
        if not text:
            continue
        value = _parse_sdr_from_text(str(text))
        if value is None:
            continue
        if best is None or value > best:
            best = value
    return best


def _parse_sdr_from_text(text: str) -> Optional[float]:
    match = _SDR_FLOAT_RE.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    match = _SDR_INT_RE.search(text)
    if match:
        decoded = _decode_int_sdr(match.group(1))
        if decoded is not None:
            return decoded

    match = _VIPERX_ABBREV_RE.search(text)
    if match:
        return _decode_int_sdr(match.group(1))
    return None


def _decode_int_sdr(token: str) -> Optional[float]:
    try:
        value = int(token)
    except ValueError:
        return None
    if value < 100:
        return None
    # 1143 → 11.43, 1297 → 12.97, 1053 → 10.53
    return value / 100.0


def purpose_bucket(intent: str) -> str:
    """Map a stem-semantics intent to a Download Center purpose filter bucket."""
    if intent == INTENT_KARAOKE:
        return PURPOSE_KARAOKE
    if intent in (INTENT_VOCALS, INTENT_DUAL_VOC_INST):
        return PURPOSE_VOCALS
    if intent == INTENT_INSTRUMENTAL:
        return PURPOSE_INSTRUMENTAL
    if intent in (
        INTENT_SPECIALTY_STEM,
        INTENT_SPECIAL_FX,
        INTENT_DRUM_BASS_SEP,
        INTENT_MULTI_STEM,
    ):
        return PURPOSE_SPECIALTY
    return PURPOSE_OTHER


def purpose_for_label(label: str) -> str:
    return purpose_bucket(infer_name_intent_from_label(label or ""))


def format_sdr_subtitle(sdr: Optional[float], size_text: str = "") -> str:
    """Build a catalogue row subtitle with optional SDR and size."""
    parts: List[str] = []
    if sdr is not None:
        parts.append(f"{sdr:.1f} SDR")
    size = (size_text or "").strip()
    if size:
        parts.append(size)
    return " · ".join(parts)


def sort_labels_by_sdr(
    labels: Sequence[str],
    *,
    score_texts: Optional[Sequence[Sequence[Optional[str]]]] = None,
) -> List[str]:
    """Sort labels by SDR descending, then name. Unscored labels follow scored ones."""

    def key(index_label: Tuple[int, str]) -> Tuple[int, float, str]:
        index, label = index_label
        texts: List[Optional[str]] = [label]
        if score_texts is not None and index < len(score_texts):
            texts.extend(score_texts[index])
        sdr = parse_sdr_score(*texts)
        # Scored first (0), unscored after (1); higher SDR first.
        if sdr is None:
            return (1, 0.0, label.casefold())
        return (0, -sdr, label.casefold())

    indexed = list(enumerate(labels))
    indexed.sort(key=key)
    return [label for _i, label in indexed]


def filter_labels_by_purpose(labels: Iterable[str], purpose: str) -> List[str]:
    """Filter catalogue labels by purpose bucket (``all`` returns everything)."""
    if purpose in ("", PURPOSE_ALL, None):
        return list(labels)
    return [label for label in labels if purpose_for_label(label) == purpose]
