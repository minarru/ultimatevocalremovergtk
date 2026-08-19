"""Parse SDR scores and purpose buckets for model browsing."""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from bundled.constants import MODEL_SCORES_URL

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


_SCORES_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

#: Present in the score data as a speed measurement, not a separable stem.
_NON_STEM_KEYS = frozenset({"seconds_per_minute_m3"})

_BUNDLED_SCORES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bundled",
    "model_scores.json",
)

_cached_scores: Optional[Dict[str, Dict[str, float]]] = None
_cached_loaded_at: float = 0.0


def model_scores_enabled() -> bool:
    return os.environ.get("UVR_DISABLE_MODEL_SCORES", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def clear_model_scores_cache() -> None:
    global _cached_scores, _cached_loaded_at
    _cached_scores = None
    _cached_loaded_at = 0.0


def _cache_path() -> str:
    from core import paths

    return paths.migrate_cache_file("model_scores.json", paths.MODEL_SCORES_CACHE_FILE)


def _read_disk_cache() -> Optional[Dict[str, Any]]:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            if (time.time() - float(payload.get("fetched_at") or 0)) < _SCORES_CACHE_TTL_SECONDS:
                return payload["data"]
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_disk_cache(data: Mapping[str, Any]) -> None:
    from core.debug_log import debug

    try:
        cache_path = _cache_path()
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "data": data}, handle)
    except OSError as exc:
        debug("download", f"model scores cache write failed err={exc}")


def _read_bundled_scores() -> Dict[str, Any]:
    try:
        with open(_BUNDLED_SCORES_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _fetch_model_scores() -> Optional[Dict[str, Any]]:
    """Network fetch, isolated so tests can patch exactly this call."""
    from core.debug_log import debug
    from core.mdx_config_fetch import _urlopen

    try:
        with _urlopen(MODEL_SCORES_URL) as response:
            payload = json.load(response)
        return payload if isinstance(payload, dict) else None
    except Exception as exc:
        debug("download", f"model scores fetch failed err={type(exc).__name__}: {exc}")
        return None


def _aggregate_entry(entry: Mapping[str, Any]) -> Dict[str, float]:
    """Mean SDR per stem across an entry's tracks."""
    per_stem: Dict[str, List[float]] = {}
    for track in entry.get("track_scores") or []:
        if not isinstance(track, dict):
            continue
        for stem, metrics in (track.get("scores") or {}).items():
            if stem in _NON_STEM_KEYS or not isinstance(metrics, dict):
                continue
            value = metrics.get("SDR")
            if isinstance(value, (int, float)):
                per_stem.setdefault(str(stem), []).append(float(value))
    return {stem: round(statistics.mean(vals), 2) for stem, vals in per_stem.items() if vals}


def load_model_scores(*, force: bool = False) -> Dict[str, Dict[str, float]]:
    """Return ``{checkpoint_filename: {stem: mean_sdr}}``, lowercased keys.

    Live fetch, then the seven-day disk cache, then the bundled snapshot, so
    the badge works offline and in CI.
    """
    global _cached_scores, _cached_loaded_at

    from core.debug_log import debug

    if not model_scores_enabled():
        return {}

    now = time.time()
    if (
        not force
        and _cached_scores is not None
        and (now - _cached_loaded_at) < _SCORES_CACHE_TTL_SECONDS
    ):
        return _cached_scores

    raw = _read_disk_cache() if not force else None
    if raw is None:
        raw = _fetch_model_scores()
        if raw is not None:
            _write_disk_cache(raw)
    if raw is None:
        raw = _read_disk_cache() or _read_bundled_scores()

    aggregated = {
        str(name).casefold(): _aggregate_entry(entry)
        for name, entry in (raw or {}).items()
        if isinstance(entry, dict)
    }
    _cached_scores = aggregated
    _cached_loaded_at = now
    debug("download", f"model scores loaded entries={len(aggregated)}")
    return aggregated


def sdr_for_files(
    filenames: Iterable[str],
    scores: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> Dict[str, float]:
    """Return per-stem SDR for the first filename with a score.

    Matches on *any* filename in a catalogue entry, not just the primary
    checkpoint: Demucs v4 is keyed in the score data by its ``.yaml``.
    """
    table = load_model_scores() if scores is None else scores
    if not table:
        return {}
    for name in filenames:
        entry = table.get(os.path.basename(str(name)).casefold())
        if entry:
            return dict(entry)
    return {}


def primary_sdr(
    stem_scores: Mapping[str, float],
    target_stem: Optional[str] = None,
    *,
    stem_count: int = 2,
) -> Optional[Tuple[str, float]]:
    """Return ``(stem, sdr)`` for the model's headline score.

    Both the model's target stem and the score-data keys go through
    :func:`core.stems.bucket_for_model_stem` before comparison. The score data
    keys stems lowercase (``vocals``, ``instrumental``, ``other``) while a
    model's target is whatever its yaml said, so a raw casefold comparison
    still misses: a 2-stem model targeting ``other`` means *instrumental* and
    would find no score at all. ``stem_count`` is what disambiguates that from
    a 4-stem model's genuine ``other`` residual.

    The returned stem is the **score-data key**, not the bucket, so callers
    render the name the benchmark actually used.
    """
    from core.stems import StemBucket, bucket_for_model_stem

    if not stem_scores:
        return None
    if target_stem:
        wanted = bucket_for_model_stem(target_stem, stem_count=stem_count)
        if wanted is not StemBucket.UNKNOWN:
            for stem, value in stem_scores.items():
                if bucket_for_model_stem(stem, stem_count=stem_count) is wanted:
                    return (stem, value)
    stem, value = max(stem_scores.items(), key=lambda item: item[1])
    return (stem, value)


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


def purpose_for_label(label: str, *, intent: Optional[str] = None) -> str:
    """Return the purpose bucket, preferring curated catalogue intent."""
    resolved = str(intent or INTENT_UNKNOWN)
    if resolved == INTENT_UNKNOWN:
        resolved = infer_name_intent_from_label(label or "")
    return purpose_bucket(resolved)


def format_sdr_subtitle(
    sdr: Optional[float],
    size_text: str = "",
    *,
    stem: Optional[str] = None,
    extra: str = "",
) -> str:
    """Build a catalogue row subtitle: SDR (if known) -> extra -> size.

    ``stem`` names the stem the score belongs to. A bare number invites a
    comparison between different quantities: the same checkpoint can be 11.4
    on vocals and 16.0 on instrumental.

    ``extra`` is usually the stem list from catalogue metadata — appended
    whenever present so scored rows still show export stems.
    """
    parts: List[str] = []
    if sdr is not None:
        parts.append(f"{stem} {sdr:.1f} SDR" if stem else f"{sdr:.1f} SDR")
    if extra.strip():
        parts.append(extra.strip())
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


def filter_labels_by_purpose(
    labels: Iterable[str],
    purpose: str,
    *,
    intents: Optional[Mapping[str, str]] = None,
) -> List[str]:
    """Filter catalogue labels by purpose bucket (``all`` returns everything)."""
    if purpose in ("", PURPOSE_ALL, None):
        return list(labels)
    known = intents or {}
    return [
        label
        for label in labels
        if purpose_for_label(label, intent=known.get(label)) == purpose
    ]
