"""Parse SDR scores and purpose buckets for model browsing."""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    MODEL_SCORES_URL,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)
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
PURPOSE_STEMS = "stems"
PURPOSE_FX = "fx"
PURPOSE_REMOVAL = "removal"
PURPOSE_RESTORE = "restore"
PURPOSE_OTHER = "other"

PURPOSE_FILTER_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (PURPOSE_ALL, "All purposes"),
    (PURPOSE_VOCALS, "Vocals"),
    (PURPOSE_INSTRUMENTAL, "Instrumental"),
    (PURPOSE_KARAOKE, "Karaoke"),
    (PURPOSE_SPECIALTY, "Specialty"),
    (PURPOSE_STEMS, "Stems"),
    (PURPOSE_FX, "FX"),
    (PURPOSE_REMOVAL, "Removal"),
    (PURPOSE_RESTORE, "Restore"),
    (PURPOSE_OTHER, "Other"),
)

PURPOSE_PAGE_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (PURPOSE_VOCALS, "Vocals"),
    (PURPOSE_INSTRUMENTAL, "Instrumental"),
    (PURPOSE_KARAOKE, "Karaoke"),
    (PURPOSE_STEMS, "Stems"),
    (PURPOSE_FX, "FX"),
    (PURPOSE_REMOVAL, "Removal"),
    (PURPOSE_RESTORE, "Restore"),
)

_REMOVAL_PRIMARY_ROLES = frozenset(
    {
        "vocal.aspiration",
        "vocal.aspiration.removed",
        "mix.music.removed",
    }
)

_FX_LABEL_HINTS = (
    "crowd",
    "sfx",
    "explosion",
    "fighting",
    "foley",
    "footsteps",
    "ambiance",
    "ambience",
    "speechsep",
    "speech sep",
    "surround",
    "cinematic",
    "toon by",
    "anime",
)

ARCH_FILTER_ALL = "all"

NETWORK_CLASSIC_MDX = "classic_onnx"
NETWORK_MDX23C = "mdx23c"
NETWORK_MEL_BAND = "mel_band_roformer"
NETWORK_BS_ROFORMER = "bs_roformer"
NETWORK_SCNET = "scnet"
NETWORK_BANDIT = "bandit"

_MDX_NETWORK_COLLAPSE = {
    "scnet_masked": NETWORK_SCNET,
    "scnet_tran": NETWORK_SCNET,
    "bandit_v2": NETWORK_BANDIT,
}

MDX_NETWORK_FILTER_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (MDX_ARCH_TYPE, "MDX-Net"),
    (NETWORK_CLASSIC_MDX, "Classic MDX"),
    (NETWORK_MDX23C, "MDX23C"),
    (NETWORK_MEL_BAND, "Mel-Band Roformer"),
    (NETWORK_BS_ROFORMER, "BS-Roformer"),
    (NETWORK_SCNET, "SCNet"),
    (NETWORK_BANDIT, "Bandit"),
)

NETWORK_FILTER_OPTIONS: Tuple[Tuple[str, str], ...] = (
    (ARCH_FILTER_ALL, "Any network"),
    (VR_ARCH_TYPE, "VR Arch"),
    *MDX_NETWORK_FILTER_OPTIONS,
    (DEMUCS_ARCH_TYPE, "Demucs"),
    (APOLLO_ARCH_TYPE, "Apollo"),
)

MDX_NETWORK_SUBTYPES = frozenset(
    value for value, _label in MDX_NETWORK_FILTER_OPTIONS if value != MDX_ARCH_TYPE
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
        INTENT_DRUM_BASS_SEP,
        INTENT_MULTI_STEM,
    ):
        return PURPOSE_SPECIALTY
    if intent == INTENT_SPECIAL_FX:
        return PURPOSE_REMOVAL
    return PURPOSE_OTHER


def purpose_for_label(label: str, *, intent: Optional[str] = None) -> str:
    """Return the primary purpose bucket, preferring curated catalogue intent."""
    resolved = str(intent or INTENT_UNKNOWN)
    if resolved == INTENT_UNKNOWN:
        resolved = infer_name_intent_from_label(label or "")
    return purpose_bucket(resolved)


def _role_is_cinematic(role: Optional[str]) -> bool:
    return str(role or "").startswith("cinematic.")


def _role_is_effect(role: Optional[str]) -> bool:
    return str(role or "").startswith("effect.")


def _is_removal_primary(role: Optional[str]) -> bool:
    value = str(role or "")
    return value in _REMOVAL_PRIMARY_ROLES or _role_is_effect(value)


def _cinematic_in_roles(
    primary_role: Optional[str],
    output_roles: Optional[Sequence[str]],
) -> bool:
    if _role_is_cinematic(primary_role):
        return True
    return any(_role_is_cinematic(role) for role in output_roles or ())


def purpose_roles_from_projection(
    projection: Any,
) -> tuple[Optional[str], tuple[str, ...]]:
    """Return ``(logical_primary_role, output roles)`` from catalogue semantics."""
    if projection is None:
        return None, ()
    primary = getattr(projection, "logical_primary_role", None)
    routes = tuple(getattr(projection, "routes", ()) or ())
    outputs = tuple(
        str(role) for role in (getattr(route, "role", None) for route in routes) if role
    )
    return (str(primary) if primary else None), outputs


def purpose_roles_from_meta(meta: Any) -> tuple[Optional[str], tuple[str, ...]]:
    """Return reviewed stem roles used for Download Center page membership."""
    if meta is None:
        return None, ()
    return purpose_roles_from_projection(getattr(meta, "stem_semantics", None))


def purpose_pages_for_label(
    label: str,
    *,
    intent: Optional[str] = None,
    arch: Optional[str] = None,
    primary_role: Optional[str] = None,
    output_roles: Optional[Sequence[str]] = None,
) -> frozenset[str]:
    """Return the Download Center pages a catalogue row should appear on.

    Dual vocals/instrumental models belong on both Vocals and Instrumental.
    Apollo restoration models always belong on Restore, regardless of intent.
    Reviewed cinematic roles belong on FX; artefact subtraction and
    aspiration belong on Removal. Musical multi-stem and specialty instruments
    stay on Stems.
    """
    if arch == APOLLO_ARCH_TYPE:
        return frozenset({PURPOSE_RESTORE})
    resolved = str(intent or INTENT_UNKNOWN)
    if resolved == INTENT_UNKNOWN:
        resolved = infer_name_intent_from_label(label or "")
    if resolved == INTENT_KARAOKE:
        return frozenset({PURPOSE_KARAOKE})
    if resolved == INTENT_VOCALS:
        return frozenset({PURPOSE_VOCALS})
    if resolved == INTENT_DUAL_VOC_INST:
        return frozenset({PURPOSE_VOCALS, PURPOSE_INSTRUMENTAL})
    if resolved == INTENT_INSTRUMENTAL:
        return frozenset({PURPOSE_INSTRUMENTAL})
    if resolved == INTENT_SPECIAL_FX or _is_removal_primary(primary_role):
        return frozenset({PURPOSE_REMOVAL})
    if _cinematic_in_roles(primary_role, output_roles):
        return frozenset({PURPOSE_FX})
    folded = (label or "").casefold()
    if "aspiration" in folded or "musicless" in folded:
        return frozenset({PURPOSE_REMOVAL})
    if any(hint in folded for hint in _FX_LABEL_HINTS):
        return frozenset({PURPOSE_FX})
    return frozenset({PURPOSE_STEMS})


def label_matches_purpose(
    label: str,
    purpose: str,
    *,
    intent: Optional[str] = None,
    arch: Optional[str] = None,
    primary_role: Optional[str] = None,
    output_roles: Optional[Sequence[str]] = None,
) -> bool:
    """Return whether ``label`` belongs on a purpose filter or page."""
    if purpose in ("", PURPOSE_ALL, None):
        return True
    if purpose in (PURPOSE_SPECIALTY, PURPOSE_OTHER):
        return purpose_for_label(label, intent=intent) == purpose
    return purpose in purpose_pages_for_label(
        label,
        intent=intent,
        arch=arch,
        primary_role=primary_role,
        output_roles=output_roles,
    )


def _collapse_mdx_network_kind(kind: str | None) -> str:
    if not kind:
        return MDX_ARCH_TYPE
    return _MDX_NETWORK_COLLAPSE.get(kind, kind)


def catalogue_network_id(
    *,
    family_arch: str,
    files: Iterable[str] = (),
    label: str = "",
) -> str:
    """Return the Download Center Network-filter id for one catalogue row."""
    if family_arch != MDX_ARCH_TYPE:
        return family_arch
    raw = [str(label or ""), *(str(name) for name in files)]
    folded = [part.casefold().replace("-", "_").replace(" ", "_") for part in raw if part]
    from core.model_inventory import mdx_kind_from_names

    return _collapse_mdx_network_kind(mdx_kind_from_names((*raw, *folded)))


def family_arch_for_network_filter(filter_id: str) -> str:
    """Map a Network combo value to the family used for downloads and folders."""
    if filter_id in ("", ARCH_FILTER_ALL, None):
        return ARCH_FILTER_ALL
    if filter_id == MDX_ARCH_TYPE or filter_id in MDX_NETWORK_SUBTYPES:
        return MDX_ARCH_TYPE
    return str(filter_id)


def network_filter_matches(
    filter_id: str,
    *,
    family_arch: str,
    network: str,
) -> bool:
    """Return whether a row belongs under the selected Network filter."""
    if filter_id in ("", ARCH_FILTER_ALL, None):
        return True
    if filter_id == MDX_ARCH_TYPE:
        return family_arch == MDX_ARCH_TYPE
    if filter_id in MDX_NETWORK_SUBTYPES:
        return family_arch == MDX_ARCH_TYPE and network == filter_id
    return family_arch == filter_id


def network_filter_hides_headers(filter_id: str) -> bool:
    """Section headers stay for Any network and the MDX-Net umbrella."""
    return filter_id not in ("", ARCH_FILTER_ALL, None, MDX_ARCH_TYPE)


def download_center_hint_for_method(method_key: str) -> Tuple[str, str]:
    """Return ``(purpose_page, network_filter)`` for an empty-model banner.

    Untargeted opens (menu, keyboard shortcut) should omit this hint so the
    window stays on Vocals / Any network, or on whatever the user last browsed.
    """
    key = str(method_key or "")
    if key in {VR_ARCH_PM, VR_ARCH_TYPE}:
        return (PURPOSE_VOCALS, VR_ARCH_TYPE)
    if key == MDX_ARCH_TYPE:
        return (PURPOSE_VOCALS, MDX_ARCH_TYPE)
    if key == DEMUCS_ARCH_TYPE:
        return (PURPOSE_STEMS, DEMUCS_ARCH_TYPE)
    if key == APOLLO_ARCH_TYPE:
        return (PURPOSE_RESTORE, APOLLO_ARCH_TYPE)
    return (PURPOSE_VOCALS, ARCH_FILTER_ALL)


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
    arches: Optional[Mapping[str, str]] = None,
    primary_roles: Optional[Mapping[str, str]] = None,
    output_roles: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[str]:
    """Filter catalogue labels by purpose page or legacy bucket.

    ``all`` returns everything. Vocals and Instrumental both include dual
    vocals/instrumental models. ``specialty`` / ``other`` keep their original
    single-bucket meaning for CLI callers.
    """
    if purpose in ("", PURPOSE_ALL, None):
        return list(labels)
    known = intents or {}
    arch_map = arches or {}
    role_map = primary_roles or {}
    outputs_map = output_roles or {}
    return [
        label
        for label in labels
        if label_matches_purpose(
            label,
            purpose,
            intent=known.get(label),
            arch=arch_map.get(label),
            primary_role=role_map.get(label),
            output_roles=outputs_map.get(label),
        )
    ]
